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
Auto-generates two output files after every solver run:

  report.md           : human-readable markdown (inputs, results, references)
  results_summary.json: compact JSON for Claude's internal use (low token cost)

Claude should point users to report.md rather than summarising everything inline.
"""

import json
import re
from datetime import date
from pathlib import Path


# Density-based (compressible) solvers use thermophysicalProperties + gamma/p/T
# instead of transportProperties + nu, so their config table needs different
# fields. rhoCentralFoam is additionally explicit/diagonal: it does not run a
# linear solver per field, so it never prints "Solving for X, Final residual =
# ..." lines and has no residual-based convergence criterion at all — the only
# way to judge it is whether it ran to the requested end time.
COMPRESSIBLE_SOLVERS = {
    "rhoSimpleFoam", "rhoPimpleFoam", "rhoCentralFoam",
    "buoyantSimpleFoam", "buoyantPimpleFoam",
}
DIAGONAL_SOLVERS = {"rhoCentralFoam"}


# known citations with DOIs

CITATIONS = {
    "teno5": {
        "authors": "Fu, L., Hu, X.Y., Adams, N.A.",
        "year": 2016,
        "title": "A family of high-order targeted ENO schemes for compressible-fluid simulations",
        "journal": "Journal of Computational Physics",
        "volume": "305", "pages": "333-359",
        "doi": "10.1016/j.jcp.2015.10.037",
    },
    "teno6": {
        "authors": "Fu, L., Hu, X.Y., Adams, N.A.",
        "year": 2016,
        "title": "A family of high-order targeted ENO schemes for compressible-fluid simulations",
        "journal": "Journal of Computational Physics",
        "volume": "305", "pages": "333-359",
        "doi": "10.1016/j.jcp.2015.10.037",
    },
    "komegasst": {
        "authors": "Menter, F.R.",
        "year": 1994,
        "title": "Two-equation eddy-viscosity turbulence models for engineering applications",
        "journal": "AIAA Journal",
        "volume": "32", "pages": "1598-1605",
        "doi": "10.2514/3.12149",
    },
    "kepsilon": {
        "authors": "Launder, B.E., Spalding, D.B.",
        "year": 1974,
        "title": "The numerical computation of turbulent flows",
        "journal": "Computer Methods in Applied Mechanics and Engineering",
        "volume": "3", "pages": "269-289",
        "doi": "10.1016/0045-7825(74)90029-2",
    },
    "jhtdb": {
        "authors": "Li, Y. et al.",
        "year": 2008,
        "title": "A public turbulence database cluster and applications to study Lagrangian evolution",
        "journal": "Journal of Turbulence",
        "volume": "9", "pages": "N31",
        "doi": "10.1080/14685240802376389",
    },
    "openfoam": {
        "authors": "Weller, H.G., Tabor, G., Jasak, H., Fureby, C.",
        "year": 1998,
        "title": "A tensorial approach to computational continuum mechanics using object-oriented techniques",
        "journal": "Computers in Physics",
        "volume": "12", "pages": "620-631",
        "doi": "10.1063/1.168744",
    },
}


# readers

def _read_dict_value(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    text = path.read_text(errors="replace")
    m = re.search(rf"{re.escape(key)}\s+([^\s;]+)\s*;", text)
    return m.group(1) if m else ""


def _read_uniform_scalar(path: Path) -> str:
    """Read a scalar field file's internalField, e.g. 0/p or 0/T."""
    if not path.exists():
        return ""
    text = path.read_text(errors="replace")
    m = re.search(r"internalField\s+uniform\s+([\d.eE+\-]+)\s*;", text)
    return m.group(1) if m else ""


def _read_inlet_velocity(case: Path) -> list[float]:
    u_file = case / "0" / "U"
    if not u_file.exists():
        return [0, 0, 0]
    text = u_file.read_text(errors="replace")
    m = re.search(r"uniform\s*\(\s*([\d.eE+\-]+)\s+([\d.eE+\-]+)\s+([\d.eE+\-]+)\s*\)", text)
    if m:
        return [float(m.group(i)) for i in (1, 2, 3)]
    return [0, 0, 0]


def _read_residuals(case: Path, solver: str) -> dict:
    log = case / f"log.{solver}"
    if not log.exists():
        candidates = list(case.glob("log.*"))
        if not candidates:
            return {}
        log = candidates[0]

    text = log.read_text(errors="replace")
    pattern = re.compile(
        r"Solving for (\w+),\s+Initial residual = ([\d.eE+\-]+),\s+"
        r"Final residual = ([\d.eE+\-]+),\s+No Iterations (\d+)"
    )
    history: dict[str, list[float]] = {}
    for m in pattern.finditer(text):
        history.setdefault(m.group(1), []).append(float(m.group(2)))

    return {f: {"iterations": len(v), "final": v[-1], "min": min(v)}
            for f, v in history.items()}


def _read_forces(case: Path) -> dict:
    pp = case / "postProcessing" / "forces"
    if not pp.exists():
        return {}
    time_dirs = sorted(
        [d for d in pp.iterdir() if d.is_dir()],
        key=lambda d: float(d.name) if d.name.replace(".", "").isdigit() else -1
    )
    if not time_dirs:
        return {}
    for fname in ("forces.dat", "force.dat"):
        ff = time_dirs[-1] / fname
        if ff.exists():
            lines = [l for l in ff.read_text().splitlines() if not l.startswith("#")]
            if lines:
                parts = lines[-1].replace("(", " ").replace(")", " ").split()
                try:
                    return {"Fx": float(parts[1]), "Fy": float(parts[2]), "Fz": float(parts[3])}
                except Exception:
                    pass
    return {}


def _read_div_scheme(case: Path) -> tuple[str, str | None]:
    """
    Read the div(phi,U) convection scheme from fvSchemes.
    Returns (display_label, citation_key). citation_key is None for schemes
    with no dedicated citation (e.g. linearUpwind).
    """
    schemes = case / "system" / "fvSchemes"
    if not schemes.exists():
        return "unknown", None
    m = re.search(r"div\(phi,U\)\s+Gauss\s+(\w+)", schemes.read_text(errors="replace"))
    if not m:
        return "unknown", None
    s = m.group(1)
    if s == "teno":
        return "TENO5 (CakeCFD)", "teno5"
    if s == "teno6":
        return "TENO6 (CakeCFD)", "teno6"
    return s, None


def _detect_citations(case: Path) -> list[str]:
    keys = ["openfoam"]
    turb = (case / "constant" / "momentumTransport")
    turb2 = (case / "constant" / "turbulenceProperties")

    _, scheme_cite = _read_div_scheme(case)
    if scheme_cite:
        keys.append(scheme_cite)
    for tf in (turb, turb2):
        if tf.exists():
            txt = tf.read_text(errors="replace")
            if "kOmegaSST" in txt:
                keys.append("komegasst")
            elif "kEpsilon" in txt:
                keys.append("kepsilon")

    if (case / "citations.bib").exists():
        bib = (case / "citations.bib").read_text(errors="replace")
        if "jhtdb" in bib.lower() or "Li2008" in bib:
            keys.append("jhtdb")

    # A case often carries both momentumTransport and turbulenceProperties, and
    # the loop above appends once per file, so the turbulence key can be added
    # twice. Deduplicate while preserving first-seen order.
    return list(dict.fromkeys(keys))


# main entry point

def generate(case_dir: str, solver: str = "simpleFoam",
             converged: bool = False, exit_code: int = 0,
             completed: bool | None = None) -> dict:
    """
    Generate report.md and results_summary.json in the case directory.
    Returns the summary dict (same content as the JSON).

    completed: whether the solver actually ran to its end condition, as
    distinct from `converged` (met a residual criterion) and from exit_code
    (some solvers crash during post-run cleanup after finishing correctly).
    Defaults to exit_code == 0 for callers that don't track it separately.
    """
    case = Path(case_dir)
    case_name = case.name
    compressible = solver in COMPRESSIBLE_SOLVERS
    diagonal = solver in DIAGONAL_SOLVERS
    if completed is None:
        completed = exit_code == 0

    mesh_cells = None
    check_log = case / "log.checkMesh"
    if check_log.exists():
        m = re.search(r"cells:\s+(\d+)", check_log.read_text(errors="replace"))
        if m:
            mesh_cells = int(m.group(1))

    # gather inputs
    scheme_label, _ = _read_div_scheme(case)
    if compressible:
        config = {
            "compressible": True,
            "gamma":     _read_dict_value(case / "constant" / "thermophysicalProperties", "gamma") or "unknown",
            "p_initial": _read_uniform_scalar(case / "0" / "p") or "unknown",
            "T_initial": _read_uniform_scalar(case / "0" / "T") or "unknown",
            "max_Co":    _read_dict_value(case / "system" / "controlDict", "maxCo") or "unknown",
            "end_time":  _read_dict_value(case / "system" / "controlDict", "endTime") or "unknown",
            "scheme":    scheme_label,
            "mesh_cells": mesh_cells,
        }
    else:
        nu_str   = _read_dict_value(case / "constant" / "transportProperties", "nu") or \
                   _read_dict_value(case / "constant" / "physicalProperties", "nu") or "unknown"
        turb_model = _read_dict_value(case / "constant" / "momentumTransport", "model") or \
                     _read_dict_value(case / "constant" / "turbulenceProperties", "model") or "unknown"
        U = _read_inlet_velocity(case)
        U_mag = (U[0]**2 + U[1]**2 + U[2]**2) ** 0.5

        try:
            nu_val = float(nu_str)
            re_val = round(U_mag / nu_val, 0) if nu_val > 0 else None
        except Exception:
            re_val = None

        config = {
            "compressible": False,
            "nu":              nu_str,
            "U_inlet":         U,
            "U_mag":           round(U_mag, 4),
            "Re":              re_val,
            "turbulence":      turb_model,
            "scheme":          scheme_label,
            "mesh_cells":      mesh_cells,
        }

    # gather outputs
    residuals = {} if diagonal else _read_residuals(case, solver)
    forces    = _read_forces(case)
    citations = _detect_citations(case)

    # time steps
    time_steps = sorted(
        [d.name for d in case.iterdir()
         if d.is_dir() and d.name.replace(".", "").isdigit() and float(d.name) > 0],
        key=float
    )

    # build summary dict (Claude reads this)
    summary = {
        "case":         case_name,
        "date":         date.today().isoformat(),
        "solver":       solver,
        "converged":    converged,
        "completed":    completed,
        "diagonal":     diagonal,
        "exit_code":    exit_code,
        "config":       config,
        "residuals":    residuals,
        "forces":       forces,
        "time_steps":   time_steps,
        "citations":    citations,
        "report_path":  str(case / "report.md"),
    }

    # write JSON (internal, Claude reads this)
    json_path = case / "results_summary.json"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    # write report.md (human-readable)
    _write_report(case, summary)

    return summary


def _write_report(case: Path, s: dict):
    cfg = s["config"]
    lines = []

    if s["diagonal"]:
        status = "Completed" if s["completed"] else "Did not complete"
    else:
        status = "Converged" if s["converged"] else "Did not converge"

    lines += [
        f"# CakeFOAM Simulation Report",
        f"",
        f"**Case:** `{s['case']}`  ",
        f"**Date:** {s['date']}  ",
        f"**Solver:** {s['solver']}  ",
        f"**Status:** {status}",
        f"",
    ]

    # Config table
    cells_str = f"{cfg['mesh_cells']:,}" if cfg['mesh_cells'] else 'N/A'
    lines += ["## Configuration", "", "| Parameter | Value |", "|-----------|-------|"]
    if cfg["compressible"]:
        lines += [
            f"| Ratio of specific heats (γ) | {cfg['gamma']} |",
            f"| Initial pressure | {cfg['p_initial']} Pa |",
            f"| Initial temperature | {cfg['T_initial']} K |",
            f"| Max Courant number | {cfg['max_Co']} |",
            f"| End time | {cfg['end_time']} s |",
            f"| Convection scheme div(phi,U) | {cfg['scheme']} |",
            f"| Mesh cells | {cells_str} |",
        ]
    else:
        re_str = f"{int(cfg['Re']):,}" if cfg['Re'] else 'N/A'
        u = cfg['U_inlet']
        lines += [
            f"| Inlet velocity | ({u[0]}, {u[1]}, {u[2]}) m/s |",
            f"| |U| | {cfg['U_mag']} m/s |",
            f"| Kinematic viscosity (ν) | {cfg['nu']} m²/s |",
            f"| Reynolds number | {re_str} |",
            f"| Turbulence model | {cfg['turbulence']} |",
            f"| Convection scheme div(phi,U) | {cfg['scheme']} |",
            f"| Mesh cells | {cells_str} |",
        ]
    lines.append("")

    # Residuals table
    if s["diagonal"]:
        lines += [
            "## Convergence",
            "",
            f"`{s['solver']}` is an explicit, density-based solver — it has no "
            "linear-solver residuals and therefore no residual convergence "
            "criterion. Progress is judged by whether it reached the "
            "requested end time (see Status above and Time Steps below).",
            "",
        ]
    elif s["residuals"]:
        lines += [
            "## Convergence",
            "",
            "| Field | Final Residual | Converged |",
            "|-------|---------------|-----------|",
        ]
        for field, info in s["residuals"].items():
            conv = "Yes" if info["final"] < 1e-3 else "No"
            lines.append(f"| {field} | {info['final']:.2e} | {conv} |")
        lines.append("")

    # Results
    if s["forces"]:
        lines += [
            "## Forces",
            "",
            "| Component | Value (N) |",
            "|-----------|-----------|",
        ]
        for comp, val in s["forces"].items():
            lines.append(f"| {comp} | {val:.6g} |")
        lines.append("")

    # Time steps
    if s["time_steps"]:
        lines += [
            "## Result Time Steps",
            "",
            ", ".join(f"`{t}`" for t in s["time_steps"]),
            "",
        ]

    # References
    if s["citations"]:
        lines += ["## References", ""]
        for i, key in enumerate(s["citations"], 1):
            c = CITATIONS.get(key)
            if c:
                lines.append(
                    f"{i}. {c['authors']} ({c['year']}). "
                    f"*{c['title']}*. "
                    f"{c['journal']}, **{c['volume']}**, {c['pages']}. "
                    f"DOI: [{c['doi']}](https://doi.org/{c['doi']})"
                )
        lines.append("")

    lines += [
        "---",
        "*Generated by CakeFOAM / cakecfd_ai*",
    ]

    (case / "report.md").write_text("\n".join(lines), encoding="utf-8")
