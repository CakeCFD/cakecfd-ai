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
Tool definitions exposed to Claude.

Each entry follows the Anthropic tool-use schema:
  { name, description, input_schema }

Implementations live in tool_impl.py.
"""

TOOLS = [
    {
        "name": "run_solver",
        "description": (
            "Run an CakeCFD solver (e.g. simpleFoam) on a case directory. "
            "Returns stdout/stderr and the final exit code."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "solver": {
                    "type": "string",
                    "description": "Solver executable name, e.g. 'simpleFoam'",
                    "default": "simpleFoam",
                },
                "case_dir": {
                    "type": "string",
                    "description": "Absolute path to the CakeCFD case directory",
                },
                "max_iterations": {
                    "type": "integer",
                    "description": "Override endTime in controlDict (0 = use existing)",
                    "default": 0,
                },
                "background": {
                    "type": "boolean",
                    "description": "Start solver in background and return immediately. Use monitor_solver to track progress.",
                    "default": False,
                },
            },
            "required": ["case_dir"],
        },
    },
    {
        "name": "read_residuals",
        "description": (
            "Parse the solver log and return the residual history for each "
            "field (U, p, k, omega ...). Useful for convergence assessment."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "case_dir": {
                    "type": "string",
                    "description": "Path to the CakeCFD case directory",
                },
                "log_name": {
                    "type": "string",
                    "description": "Name of the solver log file (default: log.simpleFoam)",
                    "default": "log.simpleFoam",
                },
            },
            "required": ["case_dir"],
        },
    },
    {
        "name": "read_forces",
        "description": (
            "Read the forces postProcessing output and return lift, drag, "
            "and moment coefficients for the latest time step."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "case_dir": {
                    "type": "string",
                    "description": "Path to the CakeCFD case directory",
                },
            },
            "required": ["case_dir"],
        },
    },
    {
        "name": "load_geometry",
        "description": (
            "Import a CAD file (STEP/BREP/STL) into Cake and return mesh "
            "statistics (bounding box, surface area, volume)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the geometry file",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "query_turbulence_db",
        "description": (
            "Query a turbulence database server (JHTDB via SOAP, or any custom REST/XML server) "
            "for velocity, pressure, vorticity, velocity gradient, pressure gradient, "
            "temperature, or magnetic field data at a batch of [x,y,z] points and one or more "
            "simulation times. Supports JHTDB spatial/temporal interpolation settings, "
            "time-range sweeps (sequential queries), turbulence statistics (k, I, epsilon, omega), "
            "OpenFOAM timeVaryingMappedFixedValue boundary data export, and custom server "
            "response formats (JSON or XML). The endpoint must always be supplied: "
            "never assume or default to any URL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "endpoint": {
                    "type": "string",
                    "description": (
                        "Full base URL of the turbulence database API, "
                        "e.g. 'http://turbulence.phy.jhu.edu/service/turbulence.asmx' "
                        "or 'http://myserver.local/api'. "
                        "Must be provided explicitly: do not guess or default."
                    ),
                },
                "dataset": {
                    "type": "string",
                    "description": (
                        "Dataset name on that server, e.g. 'isotropic1024coarse', "
                        "'channel5200', 'sabl2048low', 'sabl2048high', etc."
                    ),
                },
                "field": {
                    "type": "string",
                    "enum": [
                        "velocity", "pressure", "vorticity",
                        "magnetic", "temperature",
                        "velocity_gradient", "pressure_gradient",
                    ],
                    "description": "Physical field to retrieve",
                },
                "time": {
                    "type": "number",
                    "description": "Simulation time for single-snapshot queries (ignored if time_range is set)",
                    "default": 0.0,
                },
                "points": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 3,
                        "maxItems": 3,
                    },
                    "description": "List of [x, y, z] query points (all sent in a single batch request)",
                },
                "auth_token": {
                    "type": "string",
                    "description": "Auth token (omit to use TURBDB_TOKEN env var)",
                },
                "server_type": {
                    "type": "string",
                    "enum": ["jhtdb_soap", "rest_json", "rest_xml"],
                    "default": "jhtdb_soap",
                    "description": (
                        "Protocol to use. 'jhtdb_soap' (default) sends a SOAP POST "
                        "with all points in one XML batch: correct for JHTDB and "
                        "JHTDB-compatible servers. 'rest_json' POSTs a JSON body and "
                        "parses the response with response_format. 'rest_xml' GETs XML "
                        "and parses with response_format."
                    ),
                },
                "spatial_interp": {
                    "type": "string",
                    "enum": ["Lag4", "Lag6", "Lag8", "None"],
                    "default": "Lag4",
                    "description": "JHTDB spatial interpolation order (Lag4/Lag6/Lag8 or None for no interpolation)",
                },
                "temporal_interp": {
                    "type": "string",
                    "enum": ["None", "PCHIP"],
                    "default": "None",
                    "description": "JHTDB temporal interpolation (None or PCHIP)",
                },
                "time_range": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": (
                        "If set, overrides 'time' and fires sequential queries for each "
                        "time in the list. Results are returned as a list in the same order. "
                        "Use for time sweeps and inlet boundary data generation."
                    ),
                },
                "response_format": {
                    "type": "object",
                    "description": (
                        "Custom server response parsing spec. Required for rest_json and rest_xml "
                        "when the server is not JHTDB-compatible. Not needed for jhtdb_soap."
                    ),
                    "properties": {
                        "json_path": {
                            "type": "string",
                            "description": "Dot-separated path into JSON response to the list of point results, e.g. 'data.points'",
                        },
                        "component_keys": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Key names for each component per point in the JSON entry, e.g. ['vx','vy','vz']",
                        },
                        "xml_tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "XML element tag names to collect as component values, e.g. ['x','y','z']",
                        },
                    },
                },
                "compute_turb_stats": {
                    "type": "boolean",
                    "default": False,
                    "description": (
                        "If true and field='velocity', compute turbulence statistics "
                        "from the returned velocity samples: k (TKE), I (intensity), "
                        "epsilon (dissipation), omega (specific dissipation). "
                        "Use the result to populate RANS inlet boundary conditions."
                    ),
                },
                "write_boundary_data": {
                    "type": "object",
                    "description": (
                        "If set, write OpenFOAM timeVaryingMappedFixedValue boundary data "
                        "to constant/boundaryData/{patch}/ after the query finishes. "
                        "Requires case_dir and patch. Combined with time_range, this "
                        "generates one time directory per snapshot."
                    ),
                    "properties": {
                        "case_dir": {
                            "type": "string",
                            "description": "Absolute path to the OpenFOAM case directory",
                        },
                        "patch": {
                            "type": "string",
                            "description": "Patch name, e.g. 'inlet'",
                        },
                    },
                    "required": ["case_dir", "patch"],
                },
            },
            "required": ["endpoint", "dataset", "field", "points"],
        },
    },
    {
        "name": "write_case_param",
        "description": (
            "Modify a scalar parameter inside an CakeCFD dictionary file "
            "(e.g. change inflowVelocity, endTime, maxCo). "
            "Uses foamDictionary for safe in-place edits."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "case_dir": {
                    "type": "string",
                    "description": "Path to the CakeCFD case directory",
                },
                "dict_file": {
                    "type": "string",
                    "description": "Relative path inside case dir, e.g. 'system/controlDict'",
                },
                "key": {
                    "type": "string",
                    "description": "Dictionary key to set",
                },
                "value": {
                    "type": "string",
                    "description": "New value as a string",
                },
            },
            "required": ["case_dir", "dict_file", "key", "value"],
        },
    },
    {
        "name": "get_results_summary",
        "description": (
            "Read the compact results_summary.json generated after the last solver run. "
            "Returns Re, residuals, forces, time steps, and citation keys in one low-token call. "
            "Use this instead of re-parsing logs or calling read_residuals + read_forces separately."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "case_dir": {
                    "type": "string",
                    "description": "Path to the CakeCFD case directory",
                },
            },
            "required": ["case_dir"],
        },
    },
    {
        "name": "setup_domain",
        "description": (
            "Read an STL from constant/triSurface, compute its bounding box, "
            "then write system/blockMeshDict, system/snappyHexMeshDict, and "
            "system/surfaceFeatureExtractDict with sensible external-aero defaults. "
            "Returns domain extents, cell counts, and the next steps to run "
            "(surfaceFeatureExtract → blockMesh → snappyHexMesh)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "case_dir":          {"type": "string",  "description": "Path to the CakeCFD case directory"},
                "stl_name":          {"type": "string",  "description": "STL filename (e.g. 'sphere.stl') inside constant/triSurface"},
                "upstream_mult":     {"type": "number",  "description": "Domain upstream extent as multiple of char. length (default 5)"},
                "downstream_mult":   {"type": "number",  "description": "Domain downstream extent as multiple of char. length (default 15)"},
                "side_mult":         {"type": "number",  "description": "Domain side/top extent as multiple of char. length (default 5)"},
                "cell_size":         {"type": "number",  "description": "Base blockMesh cell size in metres (default Lc/4)"},
                "surface_refinement":{"type": "string",  "enum": ["coarse","medium","fine"], "description": "snappyHexMesh surface refinement preset (default medium)"},
                "add_layers":        {"type": "boolean", "description": "Add boundary layers (default true)"},
                "n_layers":          {"type": "integer", "description": "Number of boundary layers (default 5)"},
                "flow_axis":         {"type": "string",  "enum": ["+X","-X","+Y","-Y","+Z","-Z"],
                                      "description": "Axis the flow enters from: sets inlet/outlet patch faces and locationInMesh (default +X)"},
            },
            "required": ["case_dir", "stl_name"],
        },
    },
    {
        "name": "run_mesh_pipeline",
        "description": (
            "Run the full meshing sequence on an already-prepared case directory: "
            "surfaceFeatureExtract → blockMesh → snappyHexMesh -overwrite → checkMesh. "
            "Aborts on the first failing step. Returns per-step exit codes and the "
            "checkMesh output tail. Call setup_domain first to write the mesh dicts, "
            "then call this to actually build the mesh."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "case_dir": {
                    "type": "string",
                    "description": "Absolute path to the CakeCFD case directory",
                },
            },
            "required": ["case_dir"],
        },
    },
    {
        "name": "write_solver_setup",
        "description": (
            "Write all OpenFOAM solver dictionaries needed to run a steady-state "
            "external-aero simulation: fvSchemes (linearUpwind), fvSolution, controlDict "
            "(with forces postProcessing), decomposeParDict, and all 0/ boundary condition "
            "files (U, p, k, omega/epsilon/nuTilda, nut) plus constant/ physical properties. "
            "Call this after setup_domain and run_mesh_pipeline to complete the case setup "
            "before running the solver. Mirrors the Cake Mesh 'Generate Case' button output."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "case_dir": {
                    "type": "string",
                    "description": "Absolute path to the CakeCFD case directory",
                },
                "case_name": {
                    "type": "string",
                    "description": "Case / geometry name: used as the wall patch name in BCs",
                },
                "solver": {
                    "type": "string",
                    "enum": ["simpleFoam"],
                    "description": "OpenFOAM solver. Only simpleFoam is supported.",
                    "default": "simpleFoam",
                },
                "turbulence": {
                    "type": "string",
                    "enum": ["kOmegaSST", "kEpsilon", "SpalartAllmaras", "laminar"],
                    "description": "Turbulence model (default: kOmegaSST)",
                    "default": "kOmegaSST",
                },
                "inflow_velocity": {
                    "type": "number",
                    "description": "Freestream velocity in m/s (default: 10.0)",
                    "default": 10.0,
                },
                "nu": {
                    "type": "number",
                    "description": "Kinematic viscosity in m²/s (default: 1.5e-5 for air)",
                    "default": 1.5e-5,
                },
                "n_cores": {
                    "type": "integer",
                    "description": "Number of CPU cores for decomposeParDict (default: 4)",
                    "default": 4,
                },
                "flow_axis": {
                    "type": "string",
                    "enum": ["+X","-X","+Y","-Y","+Z","-Z"],
                    "description": "Flow axis: sets inlet velocity vector direction (default +X)",
                    "default": "+X",
                },
                "div_scheme": {
                    "type": "string",
                    "enum": ["linearUpwind", "teno", "teno6"],
                    "description": (
                        "Divergence scheme for div(phi,U). "
                        "'linearUpwind': default, no extra libs. "
                        "'teno': CakeCFD TENO5 adaptive-stencil scheme (requires libtenoScheme.so). "
                        "'teno6': CakeCFD TENO6 adaptive-stencil scheme (requires libtenoScheme.so). "
                        "Use teno/teno6 only if libtenoScheme.so is deployed in FOAM_USER_LIBBIN."
                    ),
                    "default": "linearUpwind",
                },
            },
            "required": ["case_dir", "case_name"],
        },
    },
    {
        "name": "setup_mesh",
        "description": (
            "Full mesh + solver setup pipeline in a single call: reads the STL, computes the "
            "aerodynamic domain, writes blockMeshDict/snappyHexMeshDict/surfaceFeatureExtractDict, "
            "runs surfaceFeatureExtract → blockMesh → snappyHexMesh → checkMesh, then writes all "
            "solver dictionaries (fvSchemes, fvSolution, controlDict, BCs, turbulenceProperties). "
            "Use this instead of calling setup_domain + run_mesh_pipeline + write_solver_setup "
            "separately when you want the whole pipeline in one shot."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "case_dir":           {"type": "string",  "description": "Absolute path to the OpenFOAM case directory"},
                "stl_name":           {"type": "string",  "description": "STL filename inside constant/triSurface/"},
                "upstream_mult":      {"type": "number",  "description": "Upstream domain extent multiplier (default 5)"},
                "downstream_mult":    {"type": "number",  "description": "Downstream domain extent multiplier (default 15)"},
                "side_mult":          {"type": "number",  "description": "Side/top domain extent multiplier (default 5)"},
                "cell_size":          {"type": "number",  "description": "Base blockMesh cell size in metres"},
                "surface_refinement": {"type": "string",  "enum": ["coarse","medium","fine"], "description": "snappyHexMesh refinement preset (default medium)"},
                "add_layers":         {"type": "boolean", "description": "Add boundary layers (default true)"},
                "n_layers":           {"type": "integer", "description": "Number of boundary layers (default 5)"},
                "flow_axis":          {"type": "string",  "enum": ["+X","-X","+Y","-Y","+Z","-Z"], "description": "Inflow axis (default +X)"},
                "case_name":          {"type": "string",  "description": "Case/wall-patch name (defaults to STL stem)"},
                "solver":             {"type": "string",  "enum": ["simpleFoam"], "description": "Solver. Only simpleFoam is supported."},
                "turbulence":         {"type": "string",  "enum": ["kOmegaSST","kEpsilon","SpalartAllmaras","laminar"], "description": "Turbulence model (default kOmegaSST)"},
                "inflow_velocity":    {"type": "number",  "description": "Freestream velocity m/s (default 10.0)"},
                "nu":                 {"type": "number",  "description": "Kinematic viscosity m²/s (default 1.5e-5)"},
                "n_cores":            {"type": "integer", "description": "MPI cores (default 4)"},
                "div_scheme":         {"type": "string",  "enum": ["linearUpwind","teno","teno6"],
                                       "description": "Divergence scheme for div(phi,U) (default linearUpwind)"},
            },
            "required": ["case_dir", "stl_name"],
        },
    },
    {
        "name": "monitor_solver",
        "description": (
            "Check the status of a running solver. Returns whether the process is still alive, "
            "latest per-field residuals, step count, current simulation time, and a tail of the "
            "solver log. Call this repeatedly after run_solver(background=True) to track convergence."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "case_dir":   {"type": "string",  "description": "Path to the OpenFOAM case directory"},
                "log_name":   {"type": "string",  "description": "Log filename (default: auto-detected newest log.*)"},
                "tail_lines": {"type": "integer", "description": "Lines of log tail to return (default 40)"},
            },
            "required": ["case_dir"],
        },
    },
    {
        "name": "check_mesh",
        "description": (
            "Run checkMesh on an existing mesh and return detailed quality metrics: "
            "cell count, max non-orthogonality, max skewness, max aspect ratio, overall pass/fail, "
            "and actionable advice on how to fix any issues found."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "case_dir":    {"type": "string",  "description": "Path to the OpenFOAM case directory"},
                "latest_time": {"type": "boolean", "description": "Use -latestTime flag (default true)"},
            },
            "required": ["case_dir"],
        },
    },
    {
        "name": "patch_inlet_bc",
        "description": (
            "Patch boundary condition files in 0/ to use timeVaryingMappedFixedValue for a "
            "given patch. Call this after query_turbulence_db has written boundaryData to "
            "constant/boundaryData/{patch}/. Supports U and scalar fields (k, omega, epsilon, etc.)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "case_dir": {"type": "string", "description": "Path to the OpenFOAM case directory"},
                "patch":    {"type": "string", "description": "Patch name to patch, e.g. 'inlet'"},
                "fields":   {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Field files to patch in 0/ (default: ['U']). E.g. ['U','k','omega']",
                },
            },
            "required": ["case_dir", "patch"],
        },
    },
    {
        "name": "generate_report",
        "description": (
            "Generate a full Markdown simulation report (report.md) and BibTeX citations file "
            "(citations.bib) from a finished OpenFOAM case. Includes simulation inputs, mesh stats, "
            "convergence table, forces, and a numbered References section with correct academic "
            "citations for OpenFOAM, TENO5, the turbulence model, and any turbulence database used."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "case_dir":   {"type": "string", "description": "Path to the OpenFOAM case directory"},
                "output_dir": {"type": "string", "description": "Directory to write report.md and citations.bib (default: <case_dir>/results)"},
                "title":      {"type": "string", "description": "Custom report title (optional)"},
            },
            "required": ["case_dir"],
        },
    },
    {
        "name": "export_results",
        "description": (
            "Export post-processing artefacts from a finished solver run to a directory: "
            "residuals.csv (per-step initial residuals for every field), "
            "forces.csv (time-series Fx/Fy/Fz/Mx/My/Mz), "
            "report.md (markdown convergence + forces summary), and "
            "results_summary.json (compact JSON for machine-readable consumption). "
            "All four outputs are optional; all are enabled by default. "
            "Use after run_solver to give the user persistent downloadable results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "case_dir": {
                    "type": "string",
                    "description": "Absolute path to the OpenFOAM case directory",
                },
                "output_dir": {
                    "type": "string",
                    "description": "Directory to write export files into (created if absent)",
                },
                "residuals": {
                    "type": "boolean",
                    "description": "Write residuals.csv (default: true)",
                    "default": True,
                },
                "forces": {
                    "type": "boolean",
                    "description": "Write forces.csv (default: true)",
                    "default": True,
                },
                "report": {
                    "type": "boolean",
                    "description": "Write report.md (default: true)",
                    "default": True,
                },
                "summary": {
                    "type": "boolean",
                    "description": "Write results_summary.json (default: true)",
                    "default": True,
                },
            },
            "required": ["case_dir", "output_dir"],
        },
    },
]
