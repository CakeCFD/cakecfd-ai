# CLAUDE.md

Instructions for Claude when working in this repository. Read this before
running solver tools, editing tool schemas, or answering questions about setup.
See [README.md](README.md) for the full tool list, token budgets and usage
examples. This file only adds what a coding agent needs and the README
doesn't already cover.

## What this repo is

cakecfd-ai wraps CakeCFD (a separate C++/Qt/OpenFOAM project, not part of this
repo) as Claude tool calls: `agent.py` (agentic loop), `tools.py` (schemas),
`tool_impl.py` (implementations), `cli.py` (REPL). It calls out to OpenFOAM
binaries on disk (`blockMesh`, `snappyHexMesh`, `simpleFoam`, etc.) via
subprocess. It does not vendor or build OpenFOAM itself.

## Installing OpenFOAM

`run_solver`, `run_mesh_pipeline` and `check_mesh` need OpenFOAM on `PATH`
with its environment sourced. This repo targets **OpenFOAM 2412 from
openfoam.com** (2312 is the stated floor, 2412 is what's actually tested
against, same distribution family, not OpenFOAM Foundation's `openfoam-org`).

```bash
curl -s https://dl.openfoam.com/add-debian-repo.sh | sudo bash
sudo apt-get update
sudo apt-get install -y openfoam2412-default
source /usr/lib/openfoam/openfoam2412/etc/bashrc
```

Do not fetch OpenFOAM source or tarballs from GitHub. The apt repo above is
the supported path, matching the sibling `CFD_development` (CakeCFD GUI) repo.

## Things that are easy to get wrong here

- Never wrap `os.environ["ANTHROPIC_API_KEY"]` in try/except or a friendly
  error message in `agent.py`. A missing key there should raise a raw
  `KeyError`, not be caught or explained. (The key being optional overall is
  already covered in the README; this is specifically about that one line of
  code.)

- **File encoding**: always pass `encoding="utf-8"` to `open()` and
  `Path.write_text()` in `tool_impl.py`. Windows defaults to cp1252, which
  corrupts non-ASCII output silently rather than raising.
- **`report_generator.py` citation keys must stay deduplicated**, using
  `list(dict.fromkeys(keys))` (order-preserving), not `set()` (reorders,
  breaks reproducible citation ordering).
- **`cli.py` needs `if __name__ == "__main__": main()`**. Don't remove it
  during refactors; it's the actual entry point for the `cakecfd` console
  script.
- Tool schemas in `tools.py` and their implementations in `tool_impl.py` must
  stay in lockstep. A schema change without a matching `tool_impl.py` update
  fails silently at call time, not at import time.
