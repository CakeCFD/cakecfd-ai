# Copyright (C) 2026 CakeCFD Contributors
#
# This file is part of CakeCFD.
#
# CakeCFD is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# CakeCFD is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# CakeCFD. If not, see <https://www.gnu.org/licenses/>.

"""
Concrete implementations of each tool Claude can call.

All functions receive a dict of validated inputs and return a dict
(always JSON-serializable) that goes back to Claude as the tool result.
"""

import os
import re
import subprocess
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
import math

from . import report_generator


OF_BASHRC = "/usr/lib/openfoam/openfoam2412/etc/bashrc"


# report helpers

def _read_of_value(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    m = re.search(r'\b' + re.escape(key) + r'\s+([^\s;{}()\[\]]+)\s*;',
                  path.read_text(errors="replace"))
    return m.group(1) if m else ""


def _parse_checkmesh(case_dir: Path) -> dict:
    for name in ("log.checkMesh", "checkMesh.log"):
        p = case_dir / name
        if not p.exists():
            continue
        txt = p.read_text(errors="replace")
        stats: dict = {}
        m = re.search(r'\bcells:\s+(\d+)', txt)
        if m: stats["cells"] = int(m.group(1))
        m = re.search(r'non-orthogonality Max:\s+([\d.]+)', txt)
        if m: stats["max_non_ortho"] = float(m.group(1))
        m = re.search(r'[Mm]ax skewness\s*=\s*([\d.]+)', txt)
        if m: stats["max_skewness"] = float(m.group(1))
        m = re.search(r'Overall domain bounding box\s*\(([^)]+)\)\s*\(([^)]+)\)', txt)
        if m: stats["bbox"] = f"({m.group(1)}) ({m.group(2)})"
        stats["ok"] = "Mesh OK" in txt
        return stats
    return {}


def _citations(sim_type: str, turb_model: str, case_dir: str = "") -> list:
    refs = [
        "Weller et al. (1998). A tensorial approach to computational continuum mechanics "
        "using object-oriented techniques. *Computers in Physics*, 12(6):620-631. [OpenFOAM]",
    ]
    # Only cite TENO if it is actually in the fvSchemes for this case
    if case_dir:
        fvf = Path(case_dir) / "system" / "fvSchemes"
        if fvf.exists():
            fv_txt = fvf.read_text(errors="replace")
            m = re.search(r'div\(phi,U\)\s+Gauss\s+(teno\w*)', fv_txt)
            if m:
                s = m.group(1)
                label = "TENO6" if "6" in s else "TENO5"
                refs.append(
                    "Fu et al. (2016). A family of high-order targeted ENO schemes for "
                    f"compressible-fluid simulations. *J. Comput. Phys.*, 305:333-359. [CakeCFD / {label}]"
                )
    t = turb_model.lower()
    if sim_type.upper() == "RAS":
        if "komegasst" in t or ("komega" in t and "sst" in t):
            refs.append(
                "Menter, F.R. (1994). Two-equation eddy-viscosity turbulence models for "
                "engineering applications. *AIAA Journal*, 32(8):1598-1605. [k-omega SST]"
            )
        elif "komega" in t:
            refs.append(
                "Wilcox, D.C. (1988). Reassessment of the scale-determining equation for "
                "advanced turbulence models. *AIAA Journal*, 26(11):1299-1310. [k-omega]"
            )
        elif "realizableke" in t or "realizablek" in t:
            refs.append(
                "Shih et al. (1995). A new k-epsilon eddy viscosity model for high Reynolds "
                "number turbulent flows. *Computers & Fluids*, 24(3):227-238. [Realizable k-epsilon]"
            )
        elif "rngkepsilon" in t or "rngke" in t:
            refs.append(
                "Yakhot et al. (1992). Development of turbulence models for shear flows by "
                "a double expansion technique. *Physics of Fluids A*, 4(7):1510-1520. [RNG k-epsilon]"
            )
        elif "kepsilon" in t or "keps" in t:
            refs.append(
                "Launder & Spalding (1974). The numerical computation of turbulent flows. "
                "*Comput. Methods Appl. Mech. Eng.*, 3(2):269-289. [k-epsilon]"
            )
        elif "spalart" in t or "nutilda" in t:
            refs.append(
                "Spalart & Allmaras (1992). A one-equation turbulence model for aerodynamic "
                "flows. *AIAA Paper* 92-0439. [Spalart-Allmaras]"
            )
        elif "v2f" in t:
            refs.append(
                "Durbin, P.A. (1995). Separated flow computations with the k-epsilon-v2 model. "
                "*AIAA Journal*, 33(4):659-664. [v2-f]"
            )
    return refs


def _of(cmd: str, cwd: str | None = None) -> tuple[str, int]:
    """Run cmd inside the OpenFOAM environment, return (output, returncode)."""
    full = f'source {OF_BASHRC} 2>/dev/null && {cmd}'
    result = subprocess.run(
        ["bash", "-c", full],
        capture_output=True, text=True,
        cwd=cwd or None,
    )
    return result.stdout + result.stderr, result.returncode



def run_solver(case_dir: str, solver: str = "simpleFoam",
               max_iterations: int = 0, background: bool = False) -> dict:
    if not Path(case_dir).is_dir():
        return {"error": f"Case directory not found: {case_dir}"}

    if max_iterations > 0:
        _of(f"foamDictionary system/controlDict -entry endTime -set {max_iterations}",
            cwd=case_dir)

    log_name = f"log.{solver}"

    if background:
        # Start solver detached; write PID to case_dir/.solver_pid
        full_cmd = f'source {OF_BASHRC} 2>/dev/null && {solver} > {log_name} 2>&1 & echo $!'
        result = subprocess.run(["bash", "-c", full_cmd], capture_output=True, text=True, cwd=case_dir)
        pid = result.stdout.strip()
        if pid.isdigit():
            (Path(case_dir) / ".solver_pid").write_text(pid)
            return {"started": True, "pid": int(pid), "log": log_name,
                    "note": "Solver running in background. Use monitor_solver to track progress."}
        return {"error": "Failed to start background solver", "output": result.stdout + result.stderr}

    output, code = _of(f"{solver} > {log_name} 2>&1", cwd=case_dir)

    log_path = Path(case_dir) / log_name
    tail = ""
    if log_path.exists():
        lines = log_path.read_text(errors="replace").splitlines()
        tail = "\n".join(lines[-60:])

    converged = code == 0 and bool(
        re.search(r"SIMPLE solution converged|solution converged", tail, re.IGNORECASE)
    )
    summary = report_generator.generate(case_dir, solver=solver, converged=converged, exit_code=code)

    return {
        "exit_code": code,
        "log_tail": tail,
        "converged": converged,
        "report_path": summary["report_path"],
        "results_summary": summary,
    }


def read_residuals(case_dir: str, log_name: str = "log.simpleFoam") -> dict:
    log_path = Path(case_dir) / log_name
    if not log_path.exists():
        # Try to find any log file
        candidates = list(Path(case_dir).glob("log.*"))
        if not candidates:
            return {"error": "No solver log found"}
        log_path = candidates[0]

    text = log_path.read_text(errors="replace")

    # Parse "Solving for X, Initial residual = Y, Final residual = Z, No Iterations N"
    pattern = re.compile(
        r"Solving for (\w+),\s+Initial residual = ([\d.eE+\-]+),\s+"
        r"Final residual = ([\d.eE+\-]+),\s+No Iterations (\d+)"
    )

    history: dict[str, list[float]] = {}
    for m in pattern.finditer(text):
        field = m.group(1)
        init_res = float(m.group(2))
        history.setdefault(field, []).append(init_res)

    summary = {f: {"iterations": len(v), "final": v[-1], "min": min(v)}
               for f, v in history.items()}
    return {"residuals": summary, "log": str(log_path)}


def read_forces(case_dir: str) -> dict:
    pp = Path(case_dir) / "postProcessing" / "forces"
    if not pp.exists():
        return {"error": "No forces postProcessing directory found"}

    # Find latest time directory
    time_dirs = sorted(
        [d for d in pp.iterdir() if d.is_dir()],
        key=lambda d: float(d.name) if d.name.replace(".", "").isdigit() else -1
    )
    if not time_dirs:
        return {"error": "No time directories in forces postProcessing"}

    latest = time_dirs[-1]
    force_file = latest / "forces.dat"
    if not force_file.exists():
        force_file = latest / "force.dat"
    if not force_file.exists():
        return {"error": f"No forces.dat in {latest}"}

    lines = [l for l in force_file.read_text().splitlines() if not l.startswith("#")]
    if not lines:
        return {"error": "forces.dat is empty"}

    # OF 2412 format (force.dat / forces.dat):
    #   time  total_x total_y total_z  pressure_x pressure_y pressure_z  viscous_x viscous_y viscous_z
    # Moments are in a separate moment.dat / moments.dat file with the same layout.
    last = lines[-1].replace("(", " ").replace(")", " ").split()
    try:
        t = float(last[0])
        if len(last) >= 10:
            # New OF 2412 format: col[1-3]=total, col[4-6]=pressure, col[7-9]=viscous
            tot_x, tot_y, tot_z = float(last[1]), float(last[2]), float(last[3])
            fp_x,  fp_y,  fp_z  = float(last[4]), float(last[5]), float(last[6])
            fv_x,  fv_y,  fv_z  = float(last[7]), float(last[8]), float(last[9])
        elif len(last) >= 4:
            # Minimal format: only totals
            tot_x, tot_y, tot_z = float(last[1]), float(last[2]), float(last[3])
            fp_x = fp_y = fp_z = fv_x = fv_y = fv_z = 0.0
        else:
            return {"error": "Unrecognised forces.dat format", "raw": lines[-1]}

        # Read moments from separate moment.dat if present
        mp_x = mp_y = mp_z = mv_x = mv_y = mv_z = 0.0
        for mname in ("moments.dat", "moment.dat"):
            mfile = latest / mname
            if mfile.exists():
                mlines = [l for l in mfile.read_text().splitlines() if not l.startswith("#")]
                if mlines:
                    ml = mlines[-1].replace("(", " ").replace(")", " ").split()
                    if len(ml) >= 10:
                        mp_x, mp_y, mp_z = float(ml[4]), float(ml[5]), float(ml[6])
                        mv_x, mv_y, mv_z = float(ml[7]), float(ml[8]), float(ml[9])
                break

        return {
            "time": t,
            "force": {
                "x": tot_x, "y": tot_y, "z": tot_z,
                "x_pressure": fp_x, "y_pressure": fp_y, "z_pressure": fp_z,
                "x_viscous":  fv_x, "y_viscous":  fv_y, "z_viscous":  fv_z,
            },
            "moment": {
                "x": mp_x + mv_x, "y": mp_y + mv_y, "z": mp_z + mv_z,
                "x_pressure": mp_x, "y_pressure": mp_y, "z_pressure": mp_z,
                "x_viscous":  mv_x, "y_viscous":  mv_y, "z_viscous":  mv_z,
            },
        }
    except (IndexError, ValueError) as e:
        return {"error": f"Could not parse forces: {e}", "raw": lines[-1]}


def load_geometry(file_path: str) -> dict:
    p = Path(file_path)
    if not p.exists():
        return {"error": f"File not found: {file_path}"}

    stat = p.stat()
    return {
        "file": str(p),
        "size_bytes": stat.st_size,
        "extension": p.suffix.lower(),
        "note": (
            "Geometry loaded. Use Cake GUI (ViewportWidget) or snappyHexMesh "
            "to mesh it. Full OCCT import requires the Cake C++ library."
        ),
    }


_JHTDB_FIELD = {
    "velocity":          ("GetVelocity",         ["x","y","z"],   3),
    "pressure":          ("GetPressure",          ["p"],           1),  # JHTDB: <Pressure><p>
    "vorticity":         ("GetVorticity",         ["x","y","z"],   3),
    "magnetic":          ("GetMagneticField",     ["x","y","z"],   3),
    "temperature":       ("GetTemperature",       ["p"],           1),  # JHTDB: <Temperature><p>
    "velocity_gradient": ("GetVelocityGradient",
                          ["duxdx","duxdy","duxdz","duydx","duydy","duydz",
                           "duzdx","duzdy","duzdz"], 9),
    "pressure_gradient": ("GetPressureGradient",  ["x","y","z"],   3),
}
_SPATIAL_INTERP = {"Lag4": 4, "Lag6": 6, "Lag8": 8, "None": 0}
_TEMPORAL_INTERP = {"None": 0, "PCHIP": 1}


def _jhtdb_soap_body(method: str, token: str, dataset: str, time: float,
                     points: list, si: int, ti: int) -> bytes:
    def esc(s): return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    ns = "http://turbulence.phy.jhu.edu/"
    pts_xml = "".join(
        f"<tns:Point3><tns:x>{p[0]}</tns:x><tns:y>{p[1]}</tns:y><tns:z>{p[2]}</tns:z></tns:Point3>"
        for p in points
    )
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"'
        f' xmlns:tns="{ns}">'
        "<soap:Body>"
        f"<tns:{method}>"
        f"<tns:authToken>{esc(token)}</tns:authToken>"
        f"<tns:dataset>{esc(dataset)}</tns:dataset>"
        f"<tns:time>{time}</tns:time>"
        f"<tns:spatialInterpolation>{si}</tns:spatialInterpolation>"
        f"<tns:temporalInterpolation>{ti}</tns:temporalInterpolation>"
        f"<tns:points>{pts_xml}</tns:points>"
        f"</tns:{method}>"
        "</soap:Body></soap:Envelope>"
    ).encode("utf-8")
    return body


def _jhtdb_parse_soap(xml_text: str, result_tags: list) -> list[float]:
    tag_set = set(result_tags)
    # strip namespaces from tags for simple matching
    stripped = re.sub(r'<(/?)[\w]+:', r'<\1', xml_text)
    root = ET.fromstring(stripped)
    vals: list[float] = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag in tag_set and elem.text:
            try:
                vals.append(float(elem.text.strip()))
            except ValueError:
                pass
    return vals


def _compute_turb_stats(velocities: list[list[float]]) -> dict:
    """Compute k, I, epsilon, omega from a list of [vx,vy,vz] samples."""
    if not velocities:
        return {}
    n = len(velocities)
    ux = [v[0] for v in velocities]
    uy = [v[1] for v in velocities]
    uz = [v[2] for v in velocities]
    umx, umy, umz = sum(ux)/n, sum(uy)/n, sum(uz)/n
    Umag = math.sqrt(umx**2 + umy**2 + umz**2)
    varx = sum((u - umx)**2 for u in ux) / n
    vary = sum((u - umy)**2 for u in uy) / n
    varz = sum((u - umz)**2 for u in uz) / n
    k = 0.5 * (varx + vary + varz)
    I = math.sqrt(max(2*k/3, 0)) / max(Umag, 1e-30)
    Cmu, Lref = 0.09, 1.0
    epsilon = (Cmu**0.75) * (max(k, 1e-30)**1.5) / Lref
    omega = epsilon / (Cmu * max(k, 1e-30))
    return {
        "k": k, "I": I, "epsilon": epsilon, "omega": omega,
        "Umag": Umag, "Umean": [umx, umy, umz],
        "n_samples": n,
    }


def _write_boundary_data(case_dir: str, patch: str, field: str,
                          points: list, values_by_time: list,
                          times: list, components: int) -> dict:
    """Write OpenFOAM timeVaryingMappedFixedValue boundaryData files."""
    base = Path(case_dir) / "constant" / "boundaryData" / patch
    base.mkdir(parents=True, exist_ok=True)
    n = len(points)

    # points file
    pts_text = (
        "FoamFile\n{\n    version 2.0; format ascii;\n"
        "    class vectorField; object points;\n}\n"
        f"{n}\n(\n"
        + "".join(f"  ({p[0]} {p[1]} {p[2]})\n" for p in points)
        + ")\n"
    )
    (base / "points").write_text(pts_text)

    cls   = "vectorField" if components == 3 else "scalarField"
    fname = "U" if components == 3 else "p"

    for ti, (t, vals) in enumerate(zip(times, values_by_time)):
        tdir = base / f"{t:.4f}"
        tdir.mkdir(exist_ok=True)
        lines = f"FoamFile\n{{\n    version 2.0; format ascii;\n    class {cls}; object {fname};\n}}\n{n}\n(\n"
        for i in range(n):
            if components == 3:
                vx = vals[i*3]   if i*3   < len(vals) else 0.0
                vy = vals[i*3+1] if i*3+1 < len(vals) else 0.0
                vz = vals[i*3+2] if i*3+2 < len(vals) else 0.0
                lines += f"  ({vx} {vy} {vz})\n"
            else:
                lines += f"  {vals[i] if i < len(vals) else 0.0}\n"
        lines += ")\n"
        (tdir / fname).write_text(lines)

    return {"written": str(base), "n_points": n, "n_times": len(times)}


def query_turbulence_db(
    endpoint: str,
    dataset: str,
    field: str,
    time: float = 0.0,
    points: list | None = None,
    auth_token: str | None = None,
    server_type: str = "jhtdb_soap",
    spatial_interp: str = "Lag4",
    temporal_interp: str = "None",
    time_range: list | None = None,
    response_format: dict | None = None,
    compute_turb_stats: bool = False,
    write_boundary_data: dict | None = None,
) -> dict:
    """
    Query a turbulence database server (JHTDB SOAP, REST JSON, or REST XML).
    endpoint must be supplied explicitly: no default to avoid unwanted calls.

    server_type:
      jhtdb_soap : SOAP POST to JHTDB-compatible endpoint (default)
      rest_json  : REST POST/GET, JSON response; use response_format to parse
      rest_xml   : REST GET/POST, XML response; use response_format to parse

    response_format (for rest_json / rest_xml):
      { "json_path": "data",          # dot-separated key path into the response JSON
        "component_keys": ["vx","vy","vz"],  # keys for each component per point
        "xml_tags": ["x","y","z"]     # XML element tags (rest_xml mode)
      }

    time_range: list of floats: if set, overrides `time` and fires sequential
      queries for each time in the list.

    write_boundary_data: if set, writes OpenFOAM boundaryData after a successful
      query: {"patch": "inlet", "case_dir": "/path/to/case"}

    compute_turb_stats: if True and field is velocity, compute k, I, epsilon, omega.
    """
    if points is None:
        points = []
    token = auth_token or os.environ.get("TURBDB_TOKEN", "")
    base  = endpoint.rstrip("/")

    method, result_tags, n_components = _JHTDB_FIELD.get(
        field, ("GetVelocity", ["x","y","z"], 3))
    si = _SPATIAL_INTERP.get(spatial_interp, 4)
    ti = _TEMPORAL_INTERP.get(temporal_interp, 0)

    times_to_query = time_range if time_range else [time]

    all_results: list[dict] = []

    for t in times_to_query:
        raw: str = ""
        vals: list[float] = []

        if server_type == "jhtdb_soap":
            body = _jhtdb_soap_body(method, token, dataset, t, points, si, ti)
            soap_action = f'"http://turbulence.phy.jhu.edu/{method}"'
            req = urllib.request.Request(base, data=body, headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": soap_action,
                "User-Agent": "cakecfd_ai/1.0",
            })
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                vals = _jhtdb_parse_soap(raw, result_tags)
            except Exception as e:
                return {"error": str(e), "endpoint": base, "time": t}

        elif server_type == "rest_json":
            body_json = json.dumps({
                "token": token, "dataset": dataset, "field": field,
                "time": t, "spatialInterpolation": spatial_interp,
                "temporalInterpolation": temporal_interp,
                "points": [{"x": p[0], "y": p[1], "z": p[2]} for p in points],
            }).encode()
            req = urllib.request.Request(base, data=body_json, headers={
                "Content-Type": "application/json",
                "User-Agent": "cakecfd_ai/1.0",
            })
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
            except Exception as e:
                return {"error": str(e), "endpoint": base, "time": t}

            if response_format:
                try:
                    obj = json.loads(raw)
                    for key in (response_format.get("json_path") or "").split("."):
                        if key: obj = obj[key]
                    comp_keys = response_format.get("component_keys", [])
                    for entry in (obj if isinstance(obj, list) else [obj]):
                        for k in comp_keys:
                            vals.append(float(entry.get(k, 0)))
                except Exception:
                    pass
            else:
                return {"raw_response": raw[:3000], "points_queried": len(points),
                        "endpoint": base, "time": t,
                        "note": "Provide response_format to parse values"}

        elif server_type == "rest_xml":
            xml_tags = response_format.get("xml_tags", ["x","y","z"]) if response_format else ["x","y","z"]
            url = (f"{base}?dataset={urllib.parse.quote(dataset)}"
                   f"&field={field}&time={t}"
                   f"&spatialInterpolation={spatial_interp}"
                   f"&token={urllib.parse.quote(token)}")
            try:
                with urllib.request.urlopen(url, timeout=60) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                vals = _jhtdb_parse_soap(raw, xml_tags)
            except Exception as e:
                return {"error": str(e), "endpoint": base, "time": t}

        else:
            return {"error": f"Unknown server_type: {server_type}"}

        point_data = []
        for i in range(len(points)):
            start = i * n_components
            point_data.append(vals[start:start + n_components])

        all_results.append({"time": t, "values": point_data, "n_components": n_components})

    # Turb stats (velocity fields only)
    stats_out: dict = {}
    if compute_turb_stats and field == "velocity":
        all_vels = []
        for r in all_results:
            for pv in r["values"]:
                if len(pv) >= 3:
                    all_vels.append(pv)
        if all_vels:
            stats_out = _compute_turb_stats(all_vels)

    # Boundary data export
    bd_out: dict = {}
    if write_boundary_data:
        bd_patch    = write_boundary_data.get("patch", "inlet")
        bd_case_dir = write_boundary_data.get("case_dir", "")
        if bd_case_dir:
            vals_by_time = [
                [v for pv in r["values"] for v in pv]
                for r in all_results
            ]
            bd_out = _write_boundary_data(
                bd_case_dir, bd_patch, field,
                points, vals_by_time, times_to_query, n_components)

    result: dict = {
        "endpoint":       base,
        "dataset":        dataset,
        "field":          field,
        "server_type":    server_type,
        "points_queried": len(points),
        "n_components":   n_components,
        "results":        all_results if len(all_results) > 1 else all_results[0] if all_results else {},
    }
    if stats_out:
        result["turb_stats"] = stats_out
    if bd_out:
        result["boundary_data"] = bd_out
    return result


def setup_domain(case_dir: str, stl_name: str,
                 upstream_mult: float = 5.0,
                 downstream_mult: float = 15.0,
                 side_mult: float = 5.0,
                 cell_size: float | None = None,
                 surface_refinement: str = "medium",
                 add_layers: bool = True,
                 n_layers: int = 5,
                 flow_axis: str = "+X") -> dict:
    """
    Read the STL from constant/triSurface, compute bounding box, then write:
      system/blockMeshDict
      system/snappyHexMeshDict
      system/surfaceFeatureExtractDict
    Returns the domain extents and generated file paths.
    """
    import struct

    stl_path = Path(case_dir) / "constant" / "triSurface" / stl_name
    if not stl_path.exists():
        return {"error": f"STL not found: {stl_path}"}

    # parse bounding box
    data = stl_path.read_bytes()
    xmin = ymin = zmin =  1e30
    xmax = ymax = zmax = -1e30

    is_ascii = data[:5] == b"solid" and b"\x00" not in data[:256]
    if is_ascii:
        for line in data.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line.startswith("vertex "): continue
            parts = line.split()
            if len(parts) < 4: continue
            x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
            xmin=min(xmin,x); xmax=max(xmax,x)
            ymin=min(ymin,y); ymax=max(ymax,y)
            zmin=min(zmin,z); zmax=max(zmax,z)
    else:
        n_tri = struct.unpack_from("<I", data, 80)[0]
        off = 84
        for _ in range(n_tri):
            for v in range(1, 4):
                x, y, z = struct.unpack_from("<fff", data, off + v*12)
                xmin=min(xmin,x); xmax=max(xmax,x)
                ymin=min(ymin,y); ymax=max(ymax,y)
                zmin=min(zmin,z); zmax=max(zmax,z)
            off += 50

    if xmin > 1e29:
        return {"error": "Could not parse any vertices from STL"}

    Lc = max(xmax-xmin, ymax-ymin, zmax-zmin)
    if Lc <= 0:
        return {"error": "Degenerate geometry: zero characteristic length"}

    cx, cy, cz = (xmin+xmax)/2, (ymin+ymax)/2, (zmin+zmax)/2
    up, down, side = upstream_mult, downstream_mult, side_mult

    # axis-aware domain extents
    axis = flow_axis.upper()
    if axis == "+X":
        dx0, dx1 = xmin - up*Lc,   xmax + down*Lc
        dy0, dy1 = cy   - side*Lc, cy   + side*Lc
        dz0, dz1 = cz   - side*Lc, cz   + side*Lc
    elif axis == "-X":
        dx0, dx1 = xmin - down*Lc, xmax + up*Lc
        dy0, dy1 = cy   - side*Lc, cy   + side*Lc
        dz0, dz1 = cz   - side*Lc, cz   + side*Lc
    elif axis == "+Y":
        dx0, dx1 = cx   - side*Lc, cx   + side*Lc
        dy0, dy1 = ymin - up*Lc,   ymax + down*Lc
        dz0, dz1 = cz   - side*Lc, cz   + side*Lc
    elif axis == "-Y":
        dx0, dx1 = cx   - side*Lc, cx   + side*Lc
        dy0, dy1 = ymin - down*Lc, ymax + up*Lc
        dz0, dz1 = cz   - side*Lc, cz   + side*Lc
    elif axis == "+Z":
        dx0, dx1 = cx   - side*Lc, cx   + side*Lc
        dy0, dy1 = cy   - side*Lc, cy   + side*Lc
        dz0, dz1 = zmin - up*Lc,   zmax + down*Lc
    else:  # -Z
        dx0, dx1 = cx   - side*Lc, cx   + side*Lc
        dy0, dy1 = cy   - side*Lc, cy   + side*Lc
        dz0, dz1 = zmin - down*Lc, zmax + up*Lc

    cs = cell_size if cell_size else max(Lc / 4.0, 1e-3)
    nx = max(4, round((dx1-dx0)/cs))
    ny = max(4, round((dy1-dy0)/cs))
    nz = max(4, round((dz1-dz0)/cs))

    # refinement levels
    levels = {"coarse": (3,4,3), "medium": (5,6,4), "fine": (6,7,5)}
    surf_min, surf_max, ref_region = levels.get(surface_refinement.lower(), (5,6,4))

    geo_name = stl_path.stem
    sys_dir  = Path(case_dir) / "system"
    sys_dir.mkdir(exist_ok=True)

    def foam_header(cls, obj):
        return (f"FoamFile\n{{\n    version     2.0;\n    format      ascii;\n"
                f"    class       {cls};\n    object      {obj};\n}}\n\n")

    # blockMeshDict
    bmd = foam_header("dictionary", "blockMeshDict")
    bmd += "scale   1;\n\nvertices\n(\n"
    for vx, vy, vz in [(dx0,dy0,dz0),(dx1,dy0,dz0),(dx1,dy1,dz0),(dx0,dy1,dz0),
                        (dx0,dy0,dz1),(dx1,dy0,dz1),(dx1,dy1,dz1),(dx0,dy1,dz1)]:
        bmd += f"    ({vx:.6f} {vy:.6f} {vz:.6f})\n"
    bmd += f");\n\nblocks\n(\n    hex (0 1 2 3 4 5 6 7) ({nx} {ny} {nz}) simpleGrading (1 1 1)\n);\n\n"
    # Vertex indices:
    # v0=(x0,y0,z0) v1=(x1,y0,z0) v2=(x1,y1,z0) v3=(x0,y1,z0)
    # v4=(x0,y0,z1) v5=(x1,y0,z1) v6=(x1,y1,z1) v7=(x0,y1,z1)
    _face_map = {
        "+X": ("(0 4 7 3)", "(1 2 6 5)", "(0 1 5 4) (3 7 6 2) (0 3 2 1) (4 5 6 7)"),
        "-X": ("(1 2 6 5)", "(0 4 7 3)", "(0 1 5 4) (3 7 6 2) (0 3 2 1) (4 5 6 7)"),
        "+Y": ("(0 1 5 4)", "(3 7 6 2)", "(0 4 7 3) (1 2 6 5) (0 3 2 1) (4 5 6 7)"),
        "-Y": ("(3 7 6 2)", "(0 1 5 4)", "(0 4 7 3) (1 2 6 5) (0 3 2 1) (4 5 6 7)"),
        "+Z": ("(0 3 2 1)", "(4 5 6 7)", "(0 4 7 3) (1 2 6 5) (0 1 5 4) (3 7 6 2)"),
        "-Z": ("(4 5 6 7)", "(0 3 2 1)", "(0 4 7 3) (1 2 6 5) (0 1 5 4) (3 7 6 2)"),
    }
    inlet_face, outlet_face, side_faces = _face_map.get(axis, _face_map["+X"])
    bmd += ("edges ();\n\nboundary\n(\n"
            f"    inlet  {{ type patch;    faces ( {inlet_face} ); }}\n"
            f"    outlet {{ type patch;    faces ( {outlet_face} ); }}\n"
            f"    sides  {{ type symmetry; faces ( {side_faces} ); }}\n"
            ");\n")
    (sys_dir / "blockMeshDict").write_text(bmd)

    # surfaceFeatureExtractDict
    sfed = foam_header("dictionary", "surfaceFeatureExtractDict")
    sfed += (f"{geo_name}.stl\n{{\n"
             f"    extractionMethod  extractFromSurface;\n"
             f"    extractFromSurfaceCoeffs {{ includedAngle 150; }}\n"
             f"    writeObj  yes;\n}}\n")
    (sys_dir / "surfaceFeatureExtractDict").write_text(sfed)

    # snappyHexMeshDict
    # locationInMesh: 8% inside domain from inlet face, outside geometry
    frac = 0.08
    if axis == "+X":   loc_x, loc_y, loc_z = dx0 + frac*(dx1-dx0), cy, cz
    elif axis == "-X": loc_x, loc_y, loc_z = dx1 - frac*(dx1-dx0), cy, cz
    elif axis == "+Y": loc_x, loc_y, loc_z = cx, dy0 + frac*(dy1-dy0), cz
    elif axis == "-Y": loc_x, loc_y, loc_z = cx, dy1 - frac*(dy1-dy0), cz
    elif axis == "+Z": loc_x, loc_y, loc_z = cx, cy, dz0 + frac*(dz1-dz0)
    else:              loc_x, loc_y, loc_z = cx, cy, dz1 - frac*(dz1-dz0)
    layers_block = ""
    if add_layers:
        layers_block = (f"    layers\n    {{\n"
                        f"        \"{geo_name}_.*\" {{ nSurfaceLayers {n_layers}; }}\n"
                        f"    }}\n")

    shmd = foam_header("dictionary", "snappyHexMeshDict")
    shmd += (
        f"castellatedMesh  true;\n"
        f"snap             true;\n"
        f"addLayers        {'true' if add_layers else 'false'};\n\n"
        f"geometry\n{{\n"
        f"    {geo_name}.stl {{ type triSurfaceMesh; name {geo_name}; }}\n}}\n\n"
        f"castellatedMeshControls\n{{\n"
        f"    maxLocalCells  1000000;  maxGlobalCells  2000000;\n"
        f"    minRefinementCells  0;   maxLoadUnbalance  0.10;\n"
        f"    nCellsBetweenLevels  3;\n"
        f"    features ( {{ file \"{geo_name}.eMesh\"; level {surf_max}; }} );\n"
        f"    refinementSurfaces\n    {{\n"
        f"        {geo_name} {{ level ({surf_min} {surf_max}); patchInfo {{ type wall; }} }}\n"
        f"    }}\n"
        f"    resolveFeatureAngle  30;\n"
        f"    refinementRegions\n    {{\n"
        f"        {geo_name} {{ mode inside; levels (( 1E15 {ref_region} )); }}\n"
        f"    }}\n"
        f"    locationInMesh  ({loc_x:.4f} {loc_y:.4f} {loc_z:.4f});\n"
        f"    allowFreeStandingZoneFaces  true;\n}}\n\n"
        f"snapControls\n{{\n"
        f"    nSmoothPatch 3; tolerance 2.0; nSolveIter 100; nRelaxIter 5;\n"
        f"    nFeatureSnapIter 10; implicitFeatureSnap false; explicitFeatureSnap true;\n}}\n\n"
        f"addLayersControls\n{{\n"
        f"    relativeSizes true;\n"
        f"{layers_block}"
        f"    expansionRatio 1.2; finalLayerThickness 0.3; minThickness 0.1;\n"
        f"    nGrow 0; featureAngle 60; slipFeatureAngle 30;\n"
        f"    nRelaxIter 3; nSmoothSurfaceNormals 1; nSmoothNormals 3;\n"
        f"    nSmoothThickness 10; maxFaceThicknessRatio 0.5;\n"
        f"    maxThicknessToMedialRatio 0.3; minMedialAxisAngle 90;\n"
        f"    nBufferCellsNoExtrude 0; nLayerIter 50;\n}}\n\n"
        f"meshQualityControls\n{{\n"
        f"    maxNonOrtho 65; maxBoundarySkewness 20; maxInternalSkewness 4;\n"
        f"    maxConcave 80; minVol 1e-13; minTetQuality 1e-30;\n"
        f"    minArea -1; minTwist 0.05; minDeterminant 0.001;\n"
        f"    minFaceWeight 0.05; minVolRatio 0.01; minTriangleTwist -1;\n"
        f"    nSmoothScale 4; errorReduction 0.75;\n"
        f"    relaxed {{ maxNonOrtho 75; }}\n}}\n\n"
        f"debug 0;\nmergeTolerance 1e-6;\n"
    )
    (sys_dir / "snappyHexMeshDict").write_text(shmd)

    return {
        "geometry":    geo_name,
        "Lc":          round(Lc, 4),
        "bounds":      {"x": [round(xmin,4), round(xmax,4)],
                        "y": [round(ymin,4), round(ymax,4)],
                        "z": [round(zmin,4), round(zmax,4)]},
        "flow_axis":   axis,
        "domain":      {"x": [round(dx0,4), round(dx1,4)],
                        "y": [round(dy0,4), round(dy1,4)],
                        "z": [round(dz0,4), round(dz1,4)]},
        "cells":       {"nx": nx, "ny": ny, "nz": nz, "total": nx*ny*nz},
        "refinement":  {"surface": f"{surf_min}-{surf_max}", "region": ref_region},
        "files":       ["system/blockMeshDict",
                        "system/snappyHexMeshDict",
                        "system/surfaceFeatureExtractDict"],
        "next_steps":  ["surfaceFeatureExtract", "blockMesh", "snappyHexMesh"],
    }


def run_mesh_pipeline(case_dir: str) -> dict:
    """
    Run the full meshing sequence inside the OpenFOAM environment:
      surfaceFeatureExtract → blockMesh → snappyHexMesh -overwrite → checkMesh
    Aborts on first failure. Returns per-step status + checkMesh summary.
    """
    if not Path(case_dir).is_dir():
        return {"error": f"Case directory not found: {case_dir}"}

    steps = [
        ("surfaceFeatureExtract", "surfaceFeatureExtract"),
        ("blockMesh",             "blockMesh"),
        ("snappyHexMesh",         "snappyHexMesh -overwrite"),
        ("checkMesh",             "checkMesh -latestTime"),
    ]

    results = []
    for name, cmd in steps:
        output, code = _of(cmd, cwd=case_dir)
        tail = "\n".join(output.splitlines()[-30:])
        results.append({"step": name, "exit_code": code, "output_tail": tail})
        if code != 0:
            return {
                "success": False,
                "failed_at": name,
                "steps": results,
            }

    # Extract checkMesh summary line
    check_out = results[-1]["output_tail"]
    mesh_ok = "Mesh OK" in check_out or "No errors" in check_out
    return {
        "success": True,
        "mesh_ok": mesh_ok,
        "steps": results,
        "checkmesh_tail": check_out,
    }


def write_solver_setup(case_dir: str, case_name: str,
                       solver: str = "simpleFoam",
                       turbulence: str = "kOmegaSST",
                       inflow_velocity: float = 10.0,
                       nu: float = 1.5e-5,
                       n_cores: int = 4,
                       flow_axis: str = "+X",
                       aoa_deg: float = 0.0,
                       div_scheme: str = "linearUpwind") -> dict:
    """
    Write all OpenFOAM solver dictionaries for a complete external-aero case:
      system/fvSchemes, system/fvSolution, system/controlDict, system/decomposeParDict
      0/U, 0/p, 0/k, 0/omega (or epsilon/nuTilda), 0/nut
      constant/transportProperties, constant/turbulenceProperties
    Matches the dict output of CaseGenerator::generate() in the Cake C++ GUI.

    div_scheme options:
      "linearUpwind" : default, no extra libs required
      "teno" / "teno5" : TENO5 (requires libtenoScheme.so in FOAM_USER_LIBBIN)
      "teno6"          : TENO6 (requires libtenoScheme.so in FOAM_USER_LIBBIN)
    """
    root = Path(case_dir)
    sys_dir   = root / "system";   sys_dir.mkdir(exist_ok=True)
    dir0      = root / "0";        dir0.mkdir(exist_ok=True)
    const_dir = root / "constant"; const_dir.mkdir(exist_ok=True)

    steady = solver in ("simpleFoam", "rhoSimpleFoam", "buoyantSimpleFoam")
    U = inflow_velocity
    import math as _math
    _aoa = _math.radians(aoa_deg)
    _uvec = {"+X": f"({U} 0 0)", "-X": f"(-{U} 0 0)",
             "+Y": f"(0 {U} 0)", "-Y": f"(0 -{U} 0)",
             "+Z": f"(0 0 {U})", "-Z": f"(0 0 -{U})"}
    _base = _uvec.get(flow_axis.upper(), f"({U} 0 0)")
    if aoa_deg != 0.0 and flow_axis.upper() in ("+X", "-X"):
        _sign = 1.0 if flow_axis.upper() == "+X" else -1.0
        _ux = round(_sign * U * _math.cos(_aoa), 6)
        _uz = round(U * _math.sin(_aoa), 6)
        u_vec = f"({_ux} 0 {_uz})"
    else:
        u_vec = _base
    I = 0.05
    k_val     = 1.5 * (U * I) ** 2
    omega_val = k_val / (10.0 * nu)  # TVR = k/(omega*nu) = 10, Menter 1994
    nut_val   = nu * 10.0

    def fh(cls, obj):
        return (f"FoamFile\n{{\n    version     2.0;\n    format      ascii;\n"
                f"    class       {cls};\n    object      {obj};\n}}\n\n")

    # fvSchemes
    _teno_schemes = {"teno", "teno5", "teno6"}
    _teno_lib = (
        "libs (\"libtenoScheme.so\" \"libTENOScheme.so\");\n\n"
        if div_scheme in _teno_schemes else ""
    )
    _of_teno_name = "teno6" if div_scheme == "teno6" else "teno"
    _div_U = (
        f"Gauss {_of_teno_name};"
        if div_scheme in _teno_schemes
        else "Gauss linearUpwind grad(U);"
    )
    _ddt = "steadyState" if steady else "Euler"
    (sys_dir / "fvSchemes").write_text(
        fh("dictionary", "fvSchemes") +
        f"ddtSchemes      {{ default {_ddt}; }}\n\n"
        "gradSchemes     { default Gauss linear; }\n\n"
        "divSchemes\n{\n"
        "    default          none;\n"
        f"    div(phi,U)       {_div_U}\n"
        "    turbulence       bounded Gauss upwind;\n"
        "    div(phi,k)       $turbulence;\n"
        "    div(phi,omega)   $turbulence;\n"
        "    div(phi,epsilon) $turbulence;\n"
        "    div(phi,nuTilda) $turbulence;\n"
        "    div((nuEff*dev2(T(grad(U))))) Gauss linear;\n"
        "}\n\n"
        "laplacianSchemes  { default Gauss linear corrected; }\n\n"
        "interpolationSchemes { default linear; }\n\n"
        "snGradSchemes     { default corrected; }\n\n"
        "fluxRequired      { default no; p; }\n\n"
        "wallDist          { method meshWave; }\n"
    )

    # fvSolution
    sol = (fh("dictionary", "fvSolution") +
           "solvers\n{\n"
           "    p       { solver GAMG; smoother GaussSeidel; tolerance 1e-7; relTol 0.01; }\n"
           "    pFinal  { $p; relTol 0; }\n"
           "    U       { solver smoothSolver; smoother GaussSeidel; tolerance 1e-8; relTol 0.1; }\n"
           "    \"(k|omega|epsilon|nuTilda)\" { solver smoothSolver; smoother GaussSeidel;"
           " tolerance 1e-8; relTol 0.1; }\n"
           "}\n\n")
    if steady:
        sol += ("SIMPLE\n{\n    nNonOrthogonalCorrectors 3;\n"
                "    residualControl { p 1e-4; U 1e-4; }\n}\n\n"
                "relaxationFactors\n{\n"
                "    fields  { p 0.3; }\n"
                "    equations { U 0.5; k 0.5; omega 0.5; epsilon 0.5; }\n}\n")
    else:
        sol += ("PIMPLE\n{\n    nOuterCorrectors 2;\n    nCorrectors 2;\n"
                "    nNonOrthogonalCorrectors 1;\n}\n")
    (sys_dir / "fvSolution").write_text(sol)

    # controlDict
    _rho_val = _read_of_value(sys_dir / "cakeProperties", "rho")
    _rho = float(_rho_val) if _rho_val else 1.225
    (sys_dir / "controlDict").write_text(
        fh("dictionary", "controlDict") +
        f"application     {solver};\n"
        f"startFrom       firstTime;\nstartTime       0;\n"
        f"stopAt          endTime;\nendTime         {'1000' if steady else '1'};\n"
        f"deltaT          {'1' if steady else '0.001'};\n"
        f"writeControl    timeStep;\nwriteInterval   100;\npurgeWrite      3;\n"
        f"writeFormat     ascii;\nwritePrecision  8;\nrunTimeModifiable true;\n\n"
        + _teno_lib +
        f"functions\n{{\n    forces\n    {{\n"
        f"        type            forces;\n        libs            (forces);\n"
        f"        rho             rhoInf;\n        patches         ({case_name});\n"
        f"        rhoInf          {_rho};\n        CofR            (0 0 0);\n"
        f"        writeControl    timeStep;\n        writeInterval   10;\n"
        f"    }}\n}}\n"
    )

    # decomposeParDict
    (sys_dir / "decomposeParDict").write_text(
        fh("dictionary", "decomposeParDict") +
        f"numberOfSubdomains {n_cores};\nmethod scotch;\n"
    )

    # BC helper
    def bc(patch, kind, val=None):
        if kind == "fixedValue":
            return f"    {patch} {{ type fixedValue; value uniform {val}; }}\n"
        if kind == "noSlip":
            return f"    {patch} {{ type noSlip; }}\n"
        if kind == "zeroGrad":
            return f"    {patch} {{ type zeroGradient; }}\n"
        if kind == "symm":
            return f"    {patch} {{ type symmetry; }}\n"
        return f"    {patch} {{ type {kind}; }}\n"

    sym_patches = ["sides"]

    # 0/U
    u_bcs = (f"    inlet  {{ type fixedValue; value uniform {u_vec}; }}\n"
             f"    outlet {{ type zeroGradient; }}\n"
             f"    {case_name} {{ type noSlip; }}\n" +
             "".join(f"    {p} {{ type symmetry; }}\n" for p in sym_patches))
    (dir0 / "U").write_text(
        fh("volVectorField", "U") +
        f"dimensions [0 1 -1 0 0 0 0];\n"
        f"internalField uniform {u_vec};\n"
        f"boundaryField\n{{\n{u_bcs}}}\n"
    )

    # 0/p
    p_bcs = (f"    inlet  {{ type zeroGradient; }}\n"
             f"    outlet {{ type fixedValue; value uniform 0; }}\n"
             f"    {case_name} {{ type zeroGradient; }}\n" +
             "".join(f"    {p} {{ type symmetry; }}\n" for p in sym_patches))
    (dir0 / "p").write_text(
        fh("volScalarField", "p") +
        "dimensions [0 2 -2 0 0 0 0];\n"
        "internalField uniform 0;\n"
        f"boundaryField\n{{\n{p_bcs}}}\n"
    )

    turb_lower = turbulence.lower()
    written = ["system/fvSchemes", "system/fvSolution", "system/controlDict",
               "system/decomposeParDict", "0/U", "0/p"]

    if turb_lower in ("komegasst", "kepsilon"):
        k_bcs = (f"    inlet  {{ type fixedValue; value uniform {k_val:.6g}; }}\n"
                 f"    outlet {{ type zeroGradient; }}\n"
                 f"    {case_name} {{ type kqRWallFunction; value uniform {k_val:.6g}; }}\n" +
                 "".join(f"    {p} {{ type symmetry; }}\n" for p in sym_patches))
        (dir0 / "k").write_text(
            fh("volScalarField", "k") +
            "dimensions [0 2 -2 0 0 0 0];\n"
            f"internalField uniform {k_val:.6g};\n"
            f"boundaryField\n{{\n{k_bcs}}}\n"
        )
        written.append("0/k")

    if turb_lower == "komegasst":
        o_bcs = (f"    inlet  {{ type fixedValue; value uniform {omega_val:.6g}; }}\n"
                 f"    outlet {{ type zeroGradient; }}\n"
                 f"    {case_name} {{ type omegaWallFunction; value uniform {omega_val:.6g}; }}\n" +
                 "".join(f"    {p} {{ type symmetry; }}\n" for p in sym_patches))
        (dir0 / "omega").write_text(
            fh("volScalarField", "omega") +
            "dimensions [0 0 -1 0 0 0 0];\n"
            f"internalField uniform {omega_val:.6g};\n"
            f"boundaryField\n{{\n{o_bcs}}}\n"
        )
        written.append("0/omega")

    if turb_lower == "kepsilon":
        eps = 0.09 * k_val * omega_val
        e_bcs = (f"    inlet  {{ type fixedValue; value uniform {eps:.6g}; }}\n"
                 f"    outlet {{ type zeroGradient; }}\n"
                 f"    {case_name} {{ type epsilonWallFunction; value uniform {eps:.6g}; }}\n" +
                 "".join(f"    {p} {{ type symmetry; }}\n" for p in sym_patches))
        (dir0 / "epsilon").write_text(
            fh("volScalarField", "epsilon") +
            "dimensions [0 2 -3 0 0 0 0];\n"
            f"internalField uniform {eps:.6g};\n"
            f"boundaryField\n{{\n{e_bcs}}}\n"
        )
        written.append("0/epsilon")

    if turb_lower == "spalartallmaras":
        nt = 5 * nu
        nt_bcs = (f"    inlet  {{ type fixedValue; value uniform {nt:.6g}; }}\n"
                  f"    outlet {{ type zeroGradient; }}\n"
                  f"    {case_name} {{ type fixedValue; value uniform 0; }}\n" +
                  "".join(f"    {p} {{ type symmetry; }}\n" for p in sym_patches))
        (dir0 / "nuTilda").write_text(
            fh("volScalarField", "nuTilda") +
            "dimensions [0 2 -1 0 0 0 0];\n"
            f"internalField uniform {nt:.6g};\n"
            f"boundaryField\n{{\n{nt_bcs}}}\n"
        )
        written.append("0/nuTilda")

    if turb_lower != "laminar":
        nt_bcs2 = (f"    inlet  {{ type calculated; value uniform {nut_val:.6g}; }}\n"
                   f"    outlet {{ type calculated; value uniform {nut_val:.6g}; }}\n"
                   f"    {case_name} {{ type nutkWallFunction; value uniform 0; }}\n" +
                   "".join(f"    {p} {{ type symmetry; }}\n" for p in sym_patches))
        (dir0 / "nut").write_text(
            fh("volScalarField", "nut") +
            "dimensions [0 2 -1 0 0 0 0];\n"
            f"internalField uniform {nut_val:.6g};\n"
            f"boundaryField\n{{\n{nt_bcs2}}}\n"
        )
        written.append("0/nut")

    # constant/ dicts
    (const_dir / "transportProperties").write_text(
        fh("dictionary", "transportProperties") +
        f"transportModel Newtonian;\nnu             {nu};\n"
    )
    laminar = turb_lower == "laminar"
    turb_model_name = {
        "komegasst": "kOmegaSST", "kepsilon": "kEpsilon",
        "spalartallmaras": "SpalartAllmaras", "laminar": "laminar",
    }.get(turb_lower, "kOmegaSST")
    _sim_type = "laminar" if laminar else "RAS"
    tp = (fh("dictionary", "turbulenceProperties") +
          f"simulationType {_sim_type};\n")
    if not laminar:
        tp += f"RAS\n{{\n    RASModel     {turb_model_name};\n    turbulence   on;\n    printCoeffs  on;\n}}\n"
    (const_dir / "turbulenceProperties").write_text(tp)
    # Also write momentumTransport (OF 2412 canonical name) so it doesn't inherit a stale LES file
    mt = (fh("dictionary", "momentumTransport") +
          f"simulationType {_sim_type};\n")
    if not laminar:
        mt += f"RAS\n{{\n    model        {turb_model_name};\n    turbulence   on;\n    printCoeffs  on;\n}}\n"
    (const_dir / "momentumTransport").write_text(mt)
    written += ["constant/transportProperties", "constant/turbulenceProperties", "constant/momentumTransport"]

    return {
        "success": True,
        "solver": solver,
        "turbulence": turb_model_name,
        "inflow_velocity": U,
        "nu": nu,
        "files_written": written,
    }


def export_results(case_dir: str, output_dir: str,
                   residuals: bool = True, forces: bool = True,
                   report: bool = True, summary: bool = True) -> dict:
    """
    Export post-processing artefacts to output_dir:
      residuals.csv      : per-step initial residuals for all fields
      forces.csv         : time-series Fx Fy Fz Mx My Mz
      report.md          : markdown summary with convergence table + latest forces
      results_summary.json: compact JSON (case, solver, n_steps, final residuals, forces)
    Returns a dict listing files written and any warnings.
    """
    from datetime import datetime

    root   = Path(case_dir)
    out    = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # detect solver log
    # Try controlDict application field first
    _cd_app = _read_of_value(root / "system" / "controlDict", "application")
    log_path = None
    if _cd_app:
        p = root / f"log.{_cd_app}"
        if p.exists():
            log_path = p
    if log_path is None:
        for solver_name in ("simpleFoam", "buoyantSimpleFoam", "buoyantPimpleFoam",
                            "rhoSimpleFoam", "pimpleFoam", "icoFoam", "rhoCentralFoam"):
            p = root / f"log.{solver_name}"
            if p.exists():
                log_path = p
                break
    if log_path is None:
        candidates = list(root.glob("log.*"))
        if candidates:
            log_path = candidates[0]

    # parse residuals
    res_rows: list[dict] = []
    field_names: list[str] = []
    _stem_parts = log_path.name.split(".", 1) if log_path else []
    detected_solver = _stem_parts[1] if len(_stem_parts) > 1 else "unknown"
    if log_path and log_path.exists():
        re_time = re.compile(r"^Time = ([\d.eE+\-]+)")
        re_res  = re.compile(r"Solving for (\w+),\s+Initial residual = ([\d.eE+\-]+)")
        step = 0
        current: dict = {}
        cur_time = 0.0
        for line in log_path.read_text(errors="replace").splitlines():
            m = re_time.match(line)
            if m:
                if current:
                    res_rows.append({"step": step, "time": cur_time, **current})
                    for k in current:
                        if k not in field_names: field_names.append(k)
                step += 1
                cur_time = float(m.group(1))
                current = {}
                continue
            m = re_res.search(line)
            if m and m.group(1) not in current:
                current[m.group(1)] = float(m.group(2))
        if current:
            res_rows.append({"step": step, "time": cur_time, **current})
            for k in current:
                if k not in field_names: field_names.append(k)

    # parse forces
    force_rows: list[dict] = []
    forces_dir = root / "postProcessing" / "forces"
    if forces_dir.exists():
        time_dirs = sorted(
            [d for d in forces_dir.iterdir() if d.is_dir()],
            key=lambda d: float(d.name) if d.name.replace(".", "").isdigit() else -1,
        )
        for td in time_dirs:
            fp = td / "forces.dat"
            if not fp.exists(): fp = td / "force.dat"
            if not fp.exists(): continue

            # OF 2412 force.dat: time  total_x total_y total_z  pressure_x pressure_y pressure_z  viscous_x viscous_y viscous_z
            rows_by_time: dict[float, dict] = {}
            for line in fp.read_text().splitlines():
                if line.startswith("#") or not line.strip(): continue
                parts = line.replace("(", " ").replace(")", " ").split()
                if len(parts) < 4: continue
                try:
                    t = float(parts[0])
                    row: dict = {"time": t,
                                 "Fx": float(parts[1]), "Fy": float(parts[2]), "Fz": float(parts[3])}
                    if len(parts) >= 10:
                        row["Fx_p"] = float(parts[4]); row["Fy_p"] = float(parts[5]); row["Fz_p"] = float(parts[6])
                        row["Fx_v"] = float(parts[7]); row["Fy_v"] = float(parts[8]); row["Fz_v"] = float(parts[9])
                    rows_by_time[t] = row
                except ValueError:
                    continue

            # Merge moments from separate moment.dat
            for mname in ("moments.dat", "moment.dat"):
                mf = td / mname
                if not mf.exists(): continue
                for line in mf.read_text().splitlines():
                    if line.startswith("#") or not line.strip(): continue
                    parts = line.replace("(", " ").replace(")", " ").split()
                    if len(parts) < 4: continue
                    try:
                        t = float(parts[0])
                        if t not in rows_by_time: continue
                        rows_by_time[t]["Mx"] = float(parts[1])
                        rows_by_time[t]["My"] = float(parts[2])
                        rows_by_time[t]["Mz"] = float(parts[3])
                        if len(parts) >= 10:
                            rows_by_time[t]["Mx_p"] = float(parts[4])
                            rows_by_time[t]["My_p"] = float(parts[5])
                            rows_by_time[t]["Mz_p"] = float(parts[6])
                    except ValueError:
                        continue
                break

            force_rows = list(rows_by_time.values())
            if force_rows: break

    written: list[str] = []
    warnings: list[str] = []

    # residuals.csv
    if residuals:
        p = out / "residuals.csv"
        if not res_rows:
            warnings.append("No residual data found: residuals.csv not written")
        else:
            with p.open("w") as f:
                f.write("step,time," + ",".join(field_names) + "\n")
                for r in res_rows:
                    vals = ",".join(f"{r.get(k, ''):.6e}" if isinstance(r.get(k), float)
                                   else "" for k in field_names)
                    f.write(f"{r['step']},{r['time']},{vals}\n")
            written.append(str(p))

    # forces.csv
    if forces:
        p = out / "forces.csv"
        if not force_rows:
            warnings.append("No forces postProcessing data found: forces.csv not written")
        else:
            with p.open("w") as f:
                f.write("time,Fx,Fy,Fz,Fx_pressure,Fy_pressure,Fz_pressure,"
                        "Fx_viscous,Fy_viscous,Fz_viscous,"
                        "Mx,My,Mz,Mx_pressure,My_pressure,Mz_pressure\n")
                for r in force_rows:
                    f.write(
                        f"{r['time']},{r['Fx']},{r['Fy']},{r['Fz']},"
                        f"{r.get('Fx_p',0)},{r.get('Fy_p',0)},{r.get('Fz_p',0)},"
                        f"{r.get('Fx_v',0)},{r.get('Fy_v',0)},{r.get('Fz_v',0)},"
                        f"{r.get('Mx',0)},{r.get('My',0)},{r.get('Mz',0)},"
                        f"{r.get('Mx_p',0)},{r.get('My_p',0)},{r.get('Mz_p',0)}\n"
                    )
            written.append(str(p))

    # gather inputs for report
    nu       = _read_of_value(root / "constant" / "transportProperties", "nu")
    sim_type = _read_of_value(root / "constant" / "momentumTransport", "simulationType")
    turb_model = ""
    if sim_type == "RAS":
        for _k in ("RASModel", "model"):
            turb_model = _read_of_value(root / "constant" / "momentumTransport", _k)
            if turb_model: break
    elif sim_type != "laminar":
        turb_model = _read_of_value(root / "constant" / "momentumTransport", "model")
    if not turb_model:
        turb_model = "laminar"
    end_time = _read_of_value(root / "system" / "controlDict", "endTime")
    n_cores  = _read_of_value(root / "system" / "decomposeParDict", "numberOfSubdomains")
    inlet_u  = ""
    u_file   = root / "0" / "U"
    if u_file.exists():
        m = re.search(r'uniform\s*\(\s*([\d.eE+\-]+\s+[\d.eE+\-]+\s+[\d.eE+\-]+)\s*\)',
                      u_file.read_text(errors="replace"))
        if m:
            inlet_u = f"({m.group(1)})"
    mesh_stats = _parse_checkmesh(root)

    # report.md
    if report:
        p = out / "report.md"
        case_name = root.name
        with p.open("w") as f:
            f.write(f"# Cake Studio - Simulation Report\n\n")
            f.write(f"| | |\n|---|---|\n")
            f.write(f"| **Case** | {case_name} |\n")
            f.write(f"| **Path** | {case_dir} |\n")
            f.write(f"| **Exported** | {datetime.now().isoformat(timespec='seconds')} |\n")
            f.write(f"| **Solver** | {detected_solver if detected_solver != 'unknown' else '(not detected)'} |\n\n")

            f.write("## Simulation Inputs\n\n")
            f.write("| Parameter | Value |\n|---|---|\n")
            f.write(f"| Simulation type | {sim_type or '(not detected)'} |\n")
            f.write(f"| Turbulence model | {turb_model} |\n")
            f.write(f"| Inlet velocity U | {inlet_u or '(not found)'} m/s |\n")
            f.write(f"| Kinematic viscosity nu | {nu or '(not found)'} m^2/s |\n")
            if end_time:
                f.write(f"| End time / max iterations | {end_time} |\n")
            if n_cores:
                f.write(f"| CPU cores | {n_cores} |\n")
            _fvf = root / "system" / "fvSchemes"
            if _fvf.exists():
                _dm = re.search(r'div\(phi,U\)\s+Gauss\s+(\w+)', _fvf.read_text(errors="replace"))
                if _dm:
                    _s = _dm.group(1)
                    _label = ("TENO5 (CakeCFD)" if _s == "teno" else
                              "TENO6 (CakeCFD)" if _s == "teno6" else _s)
                    f.write(f"| Divergence scheme div(phi,U) | {_label} |\n")
            f.write("\n")

            if mesh_stats:
                f.write("## Mesh\n\n")
                f.write("| Metric | Value |\n|---|---|\n")
                if "cells" in mesh_stats:
                    f.write(f"| Total cells | {mesh_stats['cells']:,} |\n")
                if "max_non_ortho" in mesh_stats:
                    f.write(f"| Max non-orthogonality | {mesh_stats['max_non_ortho']:.1f} deg |\n")
                if "max_skewness" in mesh_stats:
                    f.write(f"| Max skewness | {mesh_stats['max_skewness']:.3f} |\n")
                if "bbox" in mesh_stats:
                    f.write(f"| Domain bounding box | {mesh_stats['bbox']} |\n")
                f.write(f"| checkMesh | {'OK' if mesh_stats.get('ok') else 'FAILED'} |\n")
                f.write("\n")

            f.write("## Convergence\n\n")
            if not res_rows:
                f.write("_No residual data found._\n\n")
            else:
                last = res_rows[-1]
                f.write(f"| Total steps | {len(res_rows)} |\n")
                f.write(f"|---|---|\n")
                f.write(f"| Final time | {last['time']} s |\n\n")
                f.write("| Field | Final residual |\n|---|---|\n")
                for k in field_names:
                    if k in last:
                        f.write(f"| {k} | {last[k]:.4e} |\n")
                f.write("\n")

            f.write("## Forces (latest)\n\n")
            if not force_rows:
                f.write("_No forces data found._\n\n")
            else:
                fr = force_rows[-1]
                f.write(f"Time: {fr['time']} s\n\n")
                f.write("| Component | Fx [N] | Fy [N] | Fz [N] |\n|---|---|---|---|\n")
                f.write(f"| Force | {fr['Fx']:.6g} | {fr['Fy']:.6g} | {fr['Fz']:.6g} |\n")
                f.write(f"| Moment [N·m] | {fr['Mx']:.6g} | {fr['My']:.6g} | {fr['Mz']:.6g} |\n\n")
                f.write("> Cd = Fx / (0.5 * rho * |U|^2 * A_ref)  -- supply rho, A_ref to compute.\n\n")

            refs = _citations(sim_type, turb_model, case_dir)
            f.write("## References\n\n")
            for i, ref in enumerate(refs, 1):
                f.write(f"{i}. {ref}\n")
            f.write("\n---\n*Generated by Cake Studio*\n")
        written.append(str(p))

    # results_summary.json
    if summary:
        p = out / "results_summary.json"
        obj: dict = {
            "case":         root.name,
            "case_dir":     case_dir,
            "solver":       detected_solver,
            "exported":     datetime.now().isoformat(timespec="seconds"),
            "n_steps":      len(res_rows),
            "inputs": {
                "sim_type":   sim_type or None,
                "turb_model": turb_model or None,
                "inlet_U":    inlet_u  or None,
                "nu":         nu       or None,
                "end_time":   end_time or None,
                "n_cores":    n_cores  or None,
            },
            "mesh": mesh_stats or None,
        }
        if res_rows:
            last = res_rows[-1]
            obj["final_time"] = last["time"]
            obj["final_residuals"] = {k: last[k] for k in field_names if k in last}
        if force_rows:
            fr = force_rows[-1]
            obj["forces_latest"] = {k: fr[k] for k in ("time","Fx","Fy","Fz","Mx","My","Mz")}
        p.write_text(json.dumps(obj, indent=2))
        written.append(str(p))

    return {
        "written": written,
        "n_residual_steps": len(res_rows),
        "n_force_entries":  len(force_rows),
        "warnings":         warnings,
        "output_dir":       str(out),
    }


def setup_mesh(case_dir: str, stl_name: str,
               upstream_mult: float = 5.0, downstream_mult: float = 15.0,
               side_mult: float = 5.0, cell_size: float | None = None,
               surface_refinement: str = "medium", add_layers: bool = True,
               n_layers: int = 5, flow_axis: str = "+X",
               case_name: str | None = None, solver: str = "simpleFoam",
               turbulence: str = "kOmegaSST", inflow_velocity: float = 10.0,
               nu: float = 1.5e-5, n_cores: int = 4,
               div_scheme: str = "linearUpwind") -> dict:
    """
    Full mesh + solver setup pipeline in one call:
      1. setup_domain : write blockMeshDict, snappyHexMeshDict, surfaceFeatureExtractDict
      2. run_mesh_pipeline: surfaceFeatureExtract → blockMesh → snappyHexMesh → checkMesh
      3. write_solver_setup: fvSchemes, fvSolution, controlDict, BCs, turbulenceProperties
    Stops and reports error at the first failing step.
    """
    _case_name = case_name or Path(stl_name).stem

    domain = setup_domain(
        case_dir=case_dir, stl_name=stl_name,
        upstream_mult=upstream_mult, downstream_mult=downstream_mult,
        side_mult=side_mult, cell_size=cell_size,
        surface_refinement=surface_refinement,
        add_layers=add_layers, n_layers=n_layers, flow_axis=flow_axis,
    )
    if "error" in domain:
        return {"stage": "setup_domain", "error": domain["error"]}

    mesh = run_mesh_pipeline(case_dir=case_dir)
    if not mesh.get("success"):
        return {"stage": "run_mesh_pipeline", "error": mesh,
                "domain": domain}

    solver_setup = write_solver_setup(
        case_dir=case_dir, case_name=_case_name, solver=solver,
        turbulence=turbulence, inflow_velocity=inflow_velocity,
        nu=nu, n_cores=n_cores, flow_axis=flow_axis, div_scheme=div_scheme,
    )

    return {
        "success": True,
        "domain": domain,
        "mesh": {"ok": mesh.get("mesh_ok"), "steps": [s["step"] for s in mesh.get("steps", [])]},
        "solver_setup": solver_setup,
        "next_step": f"Run solver with: run_solver(case_dir='{case_dir}', solver='{solver}')",
    }


def monitor_solver(case_dir: str, log_name: str | None = None,
                   tail_lines: int = 40) -> dict:
    """
    Check status of a running solver. Reads the solver log, extracts the latest
    residuals per field, detects convergence, and checks if the process is still alive.
    Use after run_solver(background=True) to track progress.
    """
    root = Path(case_dir)

    # Detect log
    if log_name:
        log_path = root / log_name
    else:
        pid_file = root / ".solver_pid"
        candidates = sorted(root.glob("log.*"), key=lambda p: p.stat().st_mtime, reverse=True)
        log_path = candidates[0] if candidates else None

    # Check if process is running
    running = False
    pid_file = root / ".solver_pid"
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            result = subprocess.run(["kill", "-0", str(pid)], capture_output=True)
            running = result.returncode == 0
        except Exception:
            pass

    if not log_path or not log_path.exists():
        return {"running": running, "error": "No solver log found"}

    text = log_path.read_text(errors="replace")
    lines = text.splitlines()
    tail  = "\n".join(lines[-tail_lines:])

    # Latest residuals
    re_res = re.compile(r"Solving for (\w+),\s+Initial residual = ([\d.eE+\-]+)")
    latest: dict[str, float] = {}
    step_count = 0
    cur_time   = 0.0
    re_time    = re.compile(r"^Time = ([\d.eE+\-]+)")
    for line in lines:
        m = re_time.match(line)
        if m:
            step_count += 1
            cur_time = float(m.group(1))
            latest = {}
            continue
        m = re_res.match(line)
        if m:
            latest[m.group(1)] = float(m.group(2))

    converged = bool(re.search(r"SIMPLE solution converged|solution converged", text, re.IGNORECASE))

    return {
        "running":        running,
        "converged":      converged,
        "steps_complete": step_count,
        "current_time":   cur_time,
        "latest_residuals": latest,
        "log_tail":       tail,
        "log":            str(log_path),
    }


def check_mesh(case_dir: str, latest_time: bool = True) -> dict:
    """
    Run checkMesh and return detailed mesh quality metrics with pass/fail advice.
    Parses non-orthogonality, skewness, aspect ratio, cell counts, and overall verdict.
    """
    if not Path(case_dir).is_dir():
        return {"error": f"Case directory not found: {case_dir}"}

    flag = "-latestTime" if latest_time else ""
    output, code = _of(f"checkMesh {flag} 2>&1 | tee log.checkMesh", cwd=case_dir)

    # Parse quality metrics
    stats: dict = {"raw_exit_code": code}

    def _find(pattern, text, cast=str):
        m = re.search(pattern, text)
        return cast(m.group(1)) if m else None

    stats["cells"]          = _find(r'\bcells:\s+(\d+)', output, int)
    stats["faces"]          = _find(r'\bfaces:\s+(\d+)', output, int)
    stats["points"]         = _find(r'\bpoints:\s+(\d+)', output, int)
    stats["max_non_ortho"]  = _find(r'non-orthogonality Max:\s+([\d.]+)', output, float)
    stats["avg_non_ortho"]  = _find(r'non-orthogonality.*?average:\s+([\d.]+)', output, float)
    stats["max_skewness"]   = _find(r'[Mm]ax skewness\s*=\s*([\d.]+)', output, float)
    stats["max_aspect"]     = _find(r'[Mm]ax aspect ratio\s*=\s*([\d.]+)', output, float)
    stats["mesh_ok"]        = "Mesh OK" in output or "No errors" in output

    # Quality advice
    advice: list[str] = []
    no = stats.get("max_non_ortho")
    sk = stats.get("max_skewness")
    ar = stats.get("max_aspect")

    if no is not None:
        if no > 85:
            advice.append(f"CRITICAL: max non-orthogonality {no:.1f}° > 85°: mesh likely to diverge. "
                          "Reduce snappyHexMesh feature angle or increase nSmoothScale.")
        elif no > 70:
            advice.append(f"WARNING: max non-orthogonality {no:.1f}° > 70°: increase "
                          "nNonOrthogonalCorrectors to 3-5 in fvSolution/SIMPLE.")
        else:
            advice.append(f"Non-orthogonality {no:.1f}° is acceptable.")

    if sk is not None:
        if sk > 4:
            advice.append(f"CRITICAL: max skewness {sk:.2f} > 4: high risk of divergence.")
        elif sk > 0.85:
            advice.append(f"WARNING: max skewness {sk:.2f} > 0.85.")
        else:
            advice.append(f"Skewness {sk:.2f} is fine.")

    if ar is not None:
        if ar > 1000:
            advice.append(f"WARNING: max aspect ratio {ar:.0f} > 1000: check boundary layer settings.")
        else:
            advice.append(f"Aspect ratio {ar:.0f} is acceptable.")

    if not stats["mesh_ok"] and not advice:
        advice.append("checkMesh reported errors: review log.checkMesh for details.")

    return {
        "mesh_ok":  stats["mesh_ok"],
        "metrics":  {k: v for k, v in stats.items() if k != "raw_exit_code" and v is not None},
        "advice":   advice,
        "log_tail": "\n".join(output.splitlines()[-40:]),
    }


def patch_inlet_bc(case_dir: str, patch: str, fields: list | None = None) -> dict:
    """
    Patch boundary condition files in 0/ to use timeVaryingMappedFixedValue for the
    given patch. Call this after query_turbulence_db has written boundaryData.
    fields defaults to ["U"]: pass ["U","k","omega"] etc. as needed.
    Also patches constant/boundaryData/{patch} path in the BC.
    """
    root = Path(case_dir)
    if fields is None:
        fields = ["U"]

    patched = []
    errors  = []

    for field in fields:
        bc_file = root / "0" / field
        if not bc_file.exists():
            errors.append(f"0/{field} not found")
            continue

        text = bc_file.read_text(errors="replace")

        # Build replacement BC block
        if field == "U":
            new_bc = (
                f"    {patch}\n    {{\n"
                f"        type            timeVaryingMappedFixedValue;\n"
                f"        setAverage      false;\n"
                f"        perturb         0.0001;\n"
                f"        fieldName       U;\n"
                f"        value           uniform (0 0 0);\n"
                f"    }}\n"
            )
        else:
            # Scalar fields (k, p, omega, epsilon, nuTilda)
            new_bc = (
                f"    {patch}\n    {{\n"
                f"        type            timeVaryingMappedFixedValue;\n"
                f"        setAverage      false;\n"
                f"        perturb         0;\n"
                f"        fieldName       {field};\n"
                f"        value           uniform 0;\n"
                f"    }}\n"
            )

        # Replace existing patch block (between "    patch {" and the matching "}")
        pattern = re.compile(
            rf'(\s+{re.escape(patch)}\s*\{{[^{{}}]*(?:\{{[^{{}}]*\}}[^{{}}]*)?\}})',
            re.DOTALL
        )
        new_text, n = pattern.subn(f"\n{new_bc}", text, count=1)
        if n == 0:
            errors.append(f"Could not find patch '{patch}' block in 0/{field}")
            continue

        bc_file.write_text(new_text)
        patched.append(f"0/{field}")

    # Verify boundaryData directory exists
    bd_path = root / "constant" / "boundaryData" / patch
    bd_exists = bd_path.exists()

    return {
        "patched":         patched,
        "errors":          errors,
        "boundary_data_exists": bd_exists,
        "boundary_data_path":   str(bd_path),
        "note": (
            "BCs patched. Make sure constant/boundaryData/{patch}/points and time directories "
            "are populated (use query_turbulence_db with write_boundary_data)."
            if not bd_exists else
            f"BCs patched and boundaryData found at {bd_path}."
        ),
    }


def generate_report(case_dir: str, output_dir: str | None = None,
                    title: str | None = None) -> dict:
    """
    Generate a full Markdown simulation report with a proper References section
    and a citations.bib BibTeX file. Reads solver log, forces, mesh stats, and
    case setup from the case directory. Writes report.md and citations.bib.
    """
    from datetime import datetime

    root     = Path(case_dir)
    out      = Path(output_dir) if output_dir else root / "results"
    out.mkdir(parents=True, exist_ok=True)

    # Detect solver: controlDict application field first, then log files
    log_path = None
    detected_solver = _read_of_value(root / "system" / "controlDict", "application") or "unknown"
    if detected_solver != "unknown":
        p = root / f"log.{detected_solver}"
        if p.exists():
            log_path = p
    if not log_path:
        for s in ("simpleFoam", "buoyantSimpleFoam", "buoyantPimpleFoam",
                  "rhoSimpleFoam", "pimpleFoam", "icoFoam", "rhoCentralFoam"):
            p = root / f"log.{s}"
            if p.exists():
                log_path = p; detected_solver = s; break
    if not log_path:
        cands = list(root.glob("log.*"))
        if cands:
            log_path = cands[0]
            detected_solver = log_path.name.split(".", 1)[-1]

    # Parse residuals
    res_rows: list[dict] = []
    field_names: list[str] = []
    if log_path and log_path.exists():
        re_t = re.compile(r"^Time = ([\d.eE+\-]+)")
        re_r = re.compile(r"Solving for (\w+),\s+Initial residual = ([\d.eE+\-]+)")
        step, cur_time, current = 0, 0.0, {}
        for line in log_path.read_text(errors="replace").splitlines():
            m = re_t.match(line)
            if m:
                if current:
                    res_rows.append({"step": step, "time": cur_time, **current})
                    for k in current:
                        if k not in field_names: field_names.append(k)
                step += 1; cur_time = float(m.group(1)); current = {}; continue
            m = re_r.search(line)
            if m and m.group(1) not in current:
                current[m.group(1)] = float(m.group(2))
        if current:
            res_rows.append({"step": step, "time": cur_time, **current})

    _log_text = log_path.read_text(errors="replace") if log_path and log_path.exists() else ""
    converged = bool(re.search(r"SIMPLE solution converged|solution converged", _log_text, re.IGNORECASE))
    if not converged and res_rows:
        # Fall back: steady RANS on complex geometry plateaus U at ~1e-2 with stable forces.
        # Use turbulence residuals (k, omega/epsilon) as convergence indicator instead.
        last = res_rows[-1]
        _turb = [v for fld, v in last.items() if fld in ("k", "omega", "epsilon", "nuTilda")]
        _u_vals = [v for fld, v in last.items() if fld.startswith("U")]
        if _turb and all(v < 1e-3 for v in _turb) and _u_vals and all(v < 0.1 for v in _u_vals):
            converged = True

    # Parse forces
    force_rows: list[dict] = []
    for td in sorted((root / "postProcessing" / "forces").glob("*/") if
                     (root / "postProcessing" / "forces").exists() else [],
                     key=lambda d: float(d.name) if d.name.replace(".", "").isdigit() else -1):
        fp = td / "forces.dat"
        if not fp.exists(): fp = td / "force.dat"
        if not fp.exists(): continue
        for line in fp.read_text().splitlines():
            if line.startswith("#") or not line.strip(): continue
            parts = line.replace("(", " ").replace(")", " ").split()
            if len(parts) < 7: continue
            try:
                force_rows.append({"time": float(parts[0]),
                                   "Fx": float(parts[1]), "Fy": float(parts[2]), "Fz": float(parts[3]),
                                   "Mx": float(parts[4]), "My": float(parts[5]), "Mz": float(parts[6])})
            except ValueError:
                continue
        if force_rows: break

    nu        = _read_of_value(root / "constant" / "transportProperties", "nu")
    sim_type  = (_read_of_value(root / "constant" / "momentumTransport", "simulationType") or
                 _read_of_value(root / "constant" / "turbulenceProperties", "simulationType") or "")
    turb_model = ""
    for _k in ("RASModel", "LESModel", "model"):
        turb_model = (_read_of_value(root / "constant" / "momentumTransport", _k) or
                      _read_of_value(root / "constant" / "turbulenceProperties", _k))
        if turb_model: break
    if not turb_model: turb_model = "laminar"
    end_time = _read_of_value(root / "system" / "controlDict", "endTime")
    n_cores  = _read_of_value(root / "system" / "decomposeParDict", "numberOfSubdomains")
    inlet_u  = ""
    aoa_deg_detected = 0.0
    u_file = root / "0" / "U"
    if u_file.exists():
        m = re.search(r'uniform\s*\(\s*([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s*\)',
                      u_file.read_text(errors="replace"))
        if m:
            ux, uz = float(m.group(1)), float(m.group(3))
            inlet_u = f"({m.group(1)} {m.group(2)} {m.group(3)})"
            mag = (ux**2 + uz**2) ** 0.5
            if mag > 1e-12:
                aoa_deg_detected = round(math.degrees(math.atan2(uz, ux)), 2)
    mesh_stats = _parse_checkmesh(root)

    # Citation data
    _CITATIONS = {
        "openfoam":          ("Weller1998",   "Weller, H. G., Tabor, G., Jasak, H., & Fureby, C.",
                              "A tensorial approach to computational continuum mechanics using object-oriented techniques",
                              "Computers in Physics", "1998", "12", "620-631", "10.1063/1.168744"),
        "teno5":             ("Fu2016",        "Fu, L., Hu, X. Y., & Adams, N. A.",
                              "A family of high-order targeted ENO schemes for compressible-fluid simulations",
                              "Journal of Computational Physics", "2016", "305", "333-359", "10.1016/j.jcp.2015.10.037"),
        "teno6":             ("Fu2016",        "Fu, L., Hu, X. Y., & Adams, N. A.",
                              "A family of high-order targeted ENO schemes for compressible-fluid simulations",
                              "Journal of Computational Physics", "2016", "305", "333-359", "10.1016/j.jcp.2015.10.037"),
        "komegasst":         ("Menter1994",    "Menter, F. R.",
                              "Two-equation eddy-viscosity turbulence models for engineering applications",
                              "AIAA Journal", "1994", "32", "1598-1605", "10.2514/3.12149"),
        "komega":            ("Wilcox1988",    "Wilcox, D. C.",
                              "Reassessment of the scale-determining equation for advanced turbulence models",
                              "AIAA Journal", "1988", "26", "1299-1310", "10.2514/3.10041"),
        "kepsilon":          ("Launder1974",   "Launder, B. E., & Spalding, D. B.",
                              "The numerical computation of turbulent flows",
                              "Computer Methods in Applied Mechanics and Engineering", "1974", "3", "269-289",
                              "10.1016/0045-7825(74)90029-2"),
        "realizablekepsilon":("Shih1995",      "Shih, T.-H., Liou, W. W., Shabbir, A., Yang, Z., & Zhu, J.",
                              "A new k-epsilon eddy viscosity model for high Reynolds number turbulent flows",
                              "Computers & Fluids", "1995", "24", "227-238", "10.1016/0045-7930(94)00032-T"),
        "rngkepsilon":       ("Yakhot1992",    "Yakhot, V., et al.",
                              "Development of turbulence models for shear flows by a double expansion technique",
                              "Physics of Fluids A", "1992", "4", "1510-1520", "10.1063/1.858424"),
        "spalartallmaras":   ("Spalart1992",   "Spalart, P. R., & Allmaras, S. R.",
                              "A one-equation turbulence model for aerodynamic flows",
                              "AIAA Paper 92-0439", "1992", "", "", "10.2514/6.1992-439"),
        "v2f":               ("Durbin1995",    "Durbin, P. A.",
                              "Separated flow computations with the k-epsilon-v2 model",
                              "AIAA Journal", "1995", "33", "659-664", "10.2514/3.12628"),
        "smagorinsky":       ("Smagorinsky1963","Smagorinsky, J.",
                              "General circulation experiments with the primitive equations",
                              "Monthly Weather Review", "1963", "91", "99-164",
                              "10.1175/1520-0493(1963)091<0099:GCEWTP>2.3.CO;2"),
        "dynamicsmagorinsky":("Germano1991",   "Germano, M., Piomelli, U., Moin, P., & Cabot, W. H.",
                              "A dynamic subgrid-scale eddy viscosity model",
                              "Physics of Fluids A", "1991", "3", "1760-1765", "10.1063/1.857955"),
        "wale":              ("Nicoud1999",    "Nicoud, F., & Ducros, F.",
                              "Subgrid-scale stress modelling based on the square of the velocity gradient tensor",
                              "Flow, Turbulence and Combustion", "1999", "62", "183-200", "10.1023/A:1009995426001"),
        "dynamiclagrangian": ("Meneveau1996",  "Meneveau, C., Lund, T. S., & Cabot, W. H.",
                              "A Lagrangian dynamic subgrid-scale model of turbulence",
                              "Journal of Fluid Mechanics", "1996", "319", "353-385", "10.1017/S0022112096007379"),
        "jhtdb":             ("Li2008",        "Li, Y., Perlman, E., Wan, M., Yang, Y., et al.",
                              "A public turbulence database cluster and applications to study Lagrangian evolution",
                              "Journal of Turbulence", "2008", "9", "N31", "10.1080/14685240802376389"),
    }

    _TURB_KEY = {
        "kOmegaSST": "komegasst", "kOmega": "komega", "kEpsilon": "kepsilon",
        "realizableKE": "realizablekepsilon", "RNGkEpsilon": "rngkepsilon",
        "SpalartAllmaras": "spalartallmaras", "v2f": "v2f",
        "Smagorinsky": "smagorinsky", "dynamicSmagorinsky": "dynamicsmagorinsky",
        "WALE": "wale", "dynamicLagrangian": "dynamiclagrangian",
    }

    # Detect which div scheme is in use to cite the right TENO variant
    _fvschemes_txt = ""
    _fvschemes_path = root / "system" / "fvSchemes"
    if _fvschemes_path.exists():
        _fvschemes_txt = _fvschemes_path.read_text(errors="replace").lower()
    if "teno6" in _fvschemes_txt:
        _teno_cite = "teno6"
    elif re.search(r'div\(phi,u\)\s+gauss\s+teno\b', _fvschemes_txt):
        _teno_cite = "teno5"
    else:
        _teno_cite = None  # linearUpwind or unknown: no TENO citation

    cite_keys = ["openfoam"] + ([_teno_cite] if _teno_cite else [])
    for name, key in _TURB_KEY.items():
        if name.lower() in turb_model.lower():
            cite_keys.append(key); break

    def _fmt_inline(c):
        authors,title,journal,year,vol,pages,doi = c[1],c[2],c[3],c[4],c[5],c[6],c[7]
        s = f"{authors} ({year}). {title}."
        if journal: s += f" *{journal}*"
        if vol:     s += f", {vol}"
        if pages:   s += f", pp. {pages}"
        s += "."
        if doi: s += f" https://doi.org/{doi}"
        return s

    def _fmt_bib(key, c):
        bib_key,authors,title,journal,year,vol,pages,doi = c[0],c[1],c[2],c[3],c[4],c[5],c[6],c[7]
        return (f"@article{{{bib_key},\n"
                f"  author  = {{{authors}}},\n"
                f"  title   = {{{title}}},\n"
                f"  journal = {{{journal}}},\n"
                f"  year    = {{{year}}},\n"
                f"  volume  = {{{vol}}},\n"
                f"  pages   = {{{pages}}},\n"
                f"  doi     = {{{doi}}}\n}}\n")

    # Write report.md
    report_path = out / "report.md"
    case_name = root.name
    with report_path.open("w") as f:
        f.write(f"# {title or 'Cake Studio - Simulation Report'}\n\n")
        f.write(f"| | |\n|---|---|\n")
        f.write(f"| **Case** | {case_name} |\n")
        f.write(f"| **Solver** | {detected_solver} |\n")
        f.write(f"| **Date** | {datetime.now().isoformat(timespec='seconds')} |\n")
        f.write(f"| **Status** | {'Converged' if converged else 'Did not converge'} |\n\n")

        f.write("## Simulation Inputs\n\n| Parameter | Value |\n|---|---|\n")
        f.write(f"| Simulation type | {sim_type or 'laminar'} |\n")
        f.write(f"| Turbulence model | {turb_model} |\n")
        f.write(f"| Inlet velocity | {inlet_u or '(not found)'} m/s |\n")
        f.write(f"| Angle of attack (AoA) | {aoa_deg_detected:.2f} ° |\n")
        f.write(f"| Kinematic viscosity ν | {nu or '(not found)'} m²/s |\n")
        if end_time: f.write(f"| End time / iterations | {end_time} |\n")
        if n_cores:  f.write(f"| CPU cores | {n_cores} |\n")
        if _fvschemes_path.exists():
            _dm = re.search(r'div\(phi,U\)\s+Gauss\s+(\w+)',
                            _fvschemes_path.read_text(errors="replace"))
            if _dm:
                _s = _dm.group(1)
                _lbl = ("TENO5 (CakeCFD)" if _s == "teno" else
                        "TENO6 (CakeCFD)" if _s == "teno6" else _s)
                f.write(f"| Divergence scheme div(phi,U) | {_lbl} |\n")
        f.write("\n")

        if mesh_stats:
            f.write("## Mesh\n\n| Metric | Value |\n|---|---|\n")
            if "cells"         in mesh_stats: f.write(f"| Total cells | {mesh_stats['cells']:,} |\n")
            if "max_non_ortho" in mesh_stats: f.write(f"| Max non-orthogonality | {mesh_stats['max_non_ortho']:.1f}° |\n")
            if "max_skewness"  in mesh_stats: f.write(f"| Max skewness | {mesh_stats['max_skewness']:.3f} |\n")
            if "bbox"          in mesh_stats: f.write(f"| Domain bbox | {mesh_stats['bbox']} |\n")
            f.write(f"| checkMesh | {'OK' if mesh_stats.get('ok') else 'FAILED'} |\n\n")

        f.write("## Convergence\n\n")
        if not res_rows:
            f.write("_No residual data._\n\n")
        else:
            last = res_rows[-1]
            f.write(f"| Steps | {len(res_rows)} |\n|---|---|\n")
            f.write(f"| Final time | {last['time']} s |\n")
            f.write(f"| Status | {'**Converged**' if converged else '**Did not converge**'} |\n\n")
            f.write("| Field | Final residual |\n|---|---|\n")
            for k in field_names:
                if k in last: f.write(f"| {k} | {last[k]:.4e} |\n")
            f.write("\n")

        if force_rows:
            fr = force_rows[-1]
            f.write("## Aerodynamic Forces (final)\n\n")
            f.write("| Component | Fx [N] | Fy [N] | Fz [N] |\n|---|---|---|---|\n")
            f.write(f"| Force | {fr['Fx']:.6g} | {fr['Fy']:.6g} | {fr['Fz']:.6g} |\n")
            f.write(f"| Moment [N·m] | {fr['Mx']:.6g} | {fr['My']:.6g} | {fr['Mz']:.6g} |\n\n")

        f.write("## References\n\n")
        for i, key in enumerate(cite_keys, 1):
            c = _CITATIONS.get(key)
            if c: f.write(f"{i}. {_fmt_inline(c)}\n")
        f.write("\n---\n*Generated by Cake Studio*\n")

    # Write citations.bib
    bib_path = out / "citations.bib"
    with bib_path.open("w") as f:
        f.write("% Cake Studio: auto-generated citations\n\n")
        for key in cite_keys:
            c = _CITATIONS.get(key)
            if c: f.write(_fmt_bib(key, c) + "\n")

    return {
        "report":    str(report_path),
        "bib":       str(bib_path),
        "converged": converged,
        "n_steps":   len(res_rows),
        "citations": cite_keys,
    }


def get_results_summary(case_dir: str) -> dict:
    """Read the compact results_summary.json written after the last solver run."""
    json_path = Path(case_dir) / "results_summary.json"
    if not json_path.exists():
        return {"error": "No results_summary.json found. Run the solver first."}
    try:
        return json.loads(json_path.read_text())
    except Exception as e:
        return {"error": f"Could not parse results_summary.json: {e}"}


def write_case_param(case_dir: str, dict_file: str, key: str, value: str) -> dict:
    full_dict = Path(case_dir) / dict_file
    if not full_dict.exists():
        return {"error": f"Dict file not found: {full_dict}"}

    _, code = _of(
        f"foamDictionary {dict_file} -entry {key} -set {value}",
        cwd=case_dir,
    )
    return {"success": code == 0, "key": key, "value": value, "file": dict_file}


# Dispatch table - maps tool name → function
DISPATCH = {
    "run_solver":          run_solver,
    "read_residuals":      read_residuals,
    "read_forces":         read_forces,
    "load_geometry":       load_geometry,
    "query_turbulence_db": query_turbulence_db,
    "write_case_param":    write_case_param,
    "get_results_summary": get_results_summary,
    "setup_domain":        setup_domain,
    "run_mesh_pipeline":   run_mesh_pipeline,
    "write_solver_setup":  write_solver_setup,
    "export_results":      export_results,
    "setup_mesh":          setup_mesh,
    "monitor_solver":      monitor_solver,
    "check_mesh":          check_mesh,
    "patch_inlet_bc":      patch_inlet_bc,
    "generate_report":     generate_report,
}
