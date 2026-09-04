# cakecfd-ai

## About cakecfd-ai

cakecfd-ai is a Claude integration for CakeCFD, an OpenFOAM based computational
fluid dynamics platform. It exposes meshing, solver control, monitoring and post
processing as tools that Claude can call, so a simulation can be set up, run and
interpreted from natural language instructions.

Tools may also be called directly from the command line without an API key,
which allows an agent that already has terminal access to drive CakeCFD without
routing through the Anthropic API.

## Copyright

cakecfd-ai is free software: you can redistribute it and/or modify it under the
terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version. See the file `LICENSE` in this directory, or
<https://www.gnu.org/licenses/>, for the terms under which you can copy the
files.

## Runtime environments

| Environment | Supported | Notes |
|---|---|---|
| Claude Code | Recommended | No tool timeout. Solver runs can take 10 to 60 minutes. Full terminal access. |
| Claude chat (claude.ai) | Limited | Two minute tool timeout. Short runs (under 100 iterations, coarse mesh) may complete. Long runs are cut off mid solve. |
| API or custom agent loop | Yes | Timeout controlled by your HTTP client. Set `timeout=None` or at least 3600 s. |

Minimum specifications for solver runs:

| Component | Minimum | Recommended |
|---|---|---|
| CPU | 4 cores | 8 or more cores |
| RAM | 8 GB | 16 GB or more |
| Disk | 5 GB free | 20 GB or more (mesh and results) |
| OpenFOAM | 2312 | 2412 |

> If you are Claude reading this inside a chat session, warn the user of two
> things before starting any solver or mesh run:
>
> 1. Timeout. `run_solver` and `run_mesh_pipeline` will likely exceed the two
>    minute tool timeout in claude.ai chat. Suggest switching to Claude Code
>    (the `claude` CLI), which has no timeout.
> 2. Token cost. A single RANS run uses roughly 110k to 200k tokens. LES or long
>    runs can reach 300k to 500k or more. At Opus pricing that is $1.50 to
>    $7.50 or more per run.
>
> Tools that complete in under a second and are safe to run in chat:
> `setup_domain`, `write_solver_setup`, `write_case_param`, `check_mesh`,
> `load_geometry`.

## Requirements

| Requirement | Notes |
|---|---|
| Python 3.10 or later | |
| Anthropic API key | Only for the REPL and agent modes. Not required for direct tool calls. |
| OpenFOAM 2412 | On WSL2 Ubuntu 24.04, for the `run_solver` tool |
| CakeCFD binary | Optional. Geometry tools use the CakeCFD C++ library. |

Install OpenFOAM 2412 from [openfoam.com](https://www.openfoam.com/download).
If that domain is not reachable from your environment, a GitHub-hosted mirror
of the same release is available at
[CakeCFD/cake-openFOAM-lib](https://github.com/CakeCFD/cake-openFOAM-lib). Either way,
point `OF_BASHRC` at the resulting `etc/bashrc` if it is not at the default
apt install path:

```bash
export OF_BASHRC=/path/to/openfoam2412/etc/bashrc
```

## Installation

```bash
pip install cakecfd_ai
```

From source, which is recommended while CakeCFD is in development:

```bash
git clone https://github.com/CakeCFD/cakecfd-ai
cd cakecfd-ai
pip install -e ".[dev]"
```

## Usage

An Anthropic API key is optional. It is required only for the REPL and the
Python agent, where Claude decides which tools to call. Every tool can also be
invoked directly from the command line with no key and no network access, as
shown under Direct tool mode below.

Python API:

```python
from cakecfd_ai import CakeAgent

agent = CakeAgent(case_dir="/path/to/your/case")

# Returns the final text and streams to the terminal.
agent.chat("Run simpleFoam for 300 iterations, then report Cd.")
```

Interactive REPL:

```bash
cakecfd --case /path/to/your/case
```

```
CakeCFD AI, powered by Claude
Model : claude-opus-4-5
Case  : /path/to/your/case

You> Run the solver and tell me if it converged.
>> Tool: run_solver({"case_dir": "...", "solver": "simpleFoam"})
...
The solver converged after 347 iterations. Final Ux residual 3.2e-5,
below the 1e-4 threshold. Drag coefficient Cd is about 0.41, consistent
with the expected value for a sphere at Re of about 667k.
```

Direct tool mode, which requires no API key:

```bash
cakecfd --list-tools

cakecfd --tool get_results_summary --case /path/to/your/case
cakecfd --tool check_mesh --case /path/to/your/case
cakecfd --tool read_residuals --case /path/to/your/case --args '{"log_name":"log.simpleFoam"}'
cakecfd --tool write_case_param --case /path/to/your/case --args '{"dict_file":"system/controlDict","key":"endTime","value":"500"}'
```

Multi-turn sessions preserve history:

```python
agent = CakeAgent(case_dir="runs/airfoil")

agent.chat("Run simpleFoam.")
agent.chat("The residuals are still high. Reduce relaxation factors to 0.4 and retry.")
agent.chat("What is the lift-to-drag ratio?")
```

## Available tools

| Tool | Function |
|---|---|
| `run_solver` | Runs a CakeFOAM solver, streams the log, returns convergence status |
| `read_residuals` | Parses `log.*` and returns residual history per field |
| `read_forces` | Reads `postProcessing/forces` and returns Fx, Fy, Fz |
| `load_geometry` | Inspects a CAD file (STEP, BREP, STL) and returns bounding box and volume |
| `query_turbulence_db` | Queries a turbulence database server for DNS inflow data |
| `write_case_param` | Edits a key in any OpenFOAM dictionary through `foamDictionary` |
| `setup_domain` | Computes domain extents from STL and writes blockMeshDict, snappyHexMeshDict and surfaceFeatureExtractDict |
| `run_mesh_pipeline` | Runs surfaceFeatureExtract, blockMesh, snappyHexMesh and checkMesh in sequence |
| `write_solver_setup` | Writes fvSchemes, fvSolution, controlDict and all 0/ boundary condition files |
| `export_results` | Exports residuals.csv, forces.csv, report.md and results_summary.json |
| `get_results_summary` | Reads results_summary.json for a compact results overview |
| `check_mesh` | Runs checkMesh and returns non-orthogonality, skewness and aspect ratio |
| `monitor_solver` | Polls a running solver log and returns convergence status |
| `patch_inlet_bc` | Patches the inlet condition to timeVaryingMappedFixedValue |
| `generate_report` | Generates report.md and citations.bib for the case |

## Architecture

```
cakecfd_ai/
    agent.py       CakeAgent, the agentic loop with tool use
    tools.py       Anthropic tool schemas (input_schema JSON)
    tool_impl.py   Python implementations invoked when Claude selects a tool
    cli.py         cakecfd REPL entry point
```

Claude reads the tool schemas, selects a tool, the Python side executes it, and
the result is returned to Claude. This repeats until Claude returns `end_turn`.

## Token usage

CFD runs are token heavy. Budget accordingly before starting a session.

A single RANS run on claude-opus-4-5:

| Step | Approximate tokens |
|---|---|
| Tool schemas and system prompt, repeated each turn | 6k x 10 turns = 60k |
| `setup_mesh` and `check_mesh` output | 7k |
| `monitor_solver` polling, 20 polls at 1.5k | 30k |
| Solver log tail passed to `generate_report` | 10k to 50k |
| Report and citations output | 5k |
| Total per run | 110k to 200k tokens |

LES runs, long convergence or frequent monitoring can reach 300k to 500k tokens
or more. At Opus pricing of about $15 per Mtok input, one full run costs about
$1.50 to $7.50.

A pre-meshed simpleFoam run, with the report pushed directly to the user rather
than read back into context:

| Step | Approximate tokens |
|---|---|
| Tool schemas and system prompt | 6k x 4 turns = 24k |
| `write_solver_setup` and `run_solver` log tail | 12k |
| `generate_report` | 4k |
| Total | 35k to 40k tokens, about $0.50 on Opus |

Push `report.md` to the user after `generate_report` rather than reading it back
into context, to keep token usage down.

For fast iteration during debugging, claude-haiku-4-5 is roughly 25 times
cheaper:

```python
agent = CakeAgent(model="claude-haiku-4-5-20251001")
```

## Claude Code

The package is designed to run inside Claude Code, which is the only interface
with no tool timeout. Solver runs take minutes to hours, and chat based Claude
times out after two minutes.

Within a Claude Code session Claude has full terminal access, can call every
tool autonomously, and waits as long as the solver needs. The full pipeline of
`setup_domain`, `run_mesh_pipeline`, `run_solver` and `export_results` runs end
to end without manual intervention.
