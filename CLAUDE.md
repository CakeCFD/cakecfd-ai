# CLAUDE.md

Instructions for Claude when working in this repository. Read this before
running solver tools, editing tool schemas, or answering questions about setup.
See [README.md](README.md) for the full tool list, token budgets and usage
examples. This file only adds what a coding agent needs and the README
doesn't already cover.

## What this repo is

cakecfd-ai wraps CakeCFD (a separate C++/Qt/OpenFOAM project in its own
repository) as Claude tool calls: agent.py (agentic loop), tools.py (schemas),
tool_impl.py (implementations), cli.py (REPL). It calls out to OpenFOAM
binaries on disk (blockMesh, snappyHexMesh, simpleFoam, etc.) via
subprocess. It does not vendor or build OpenFOAM itself.

## OpenFOAM and other binaries

run_solver, run_mesh_pipeline and check_mesh need OpenFOAM 2412 from
openfoam.com on PATH with its environment sourced. 2312 is the stated floor
and 2412 is what is tested. The OpenFOAM Foundation distribution
(openfoam.org, github.com/OpenFOAM) is a different project with an
incompatible version scheme, so never suggest it as a substitute.

Installing software is the user's decision. Do not download, extract, source
or install OpenFOAM, MPI, libtenoScheme.so or any other binary yourself, and
do not look for alternative download sources when a site is unreachable. If a
tool fails because something is missing, stop, say what is missing, and point
the user to the Requirements section of README.md.

What the common failures look like in a solver log:

- etc/bashrc not found: OpenFOAM is not installed, or OF_BASHRC (see
  tool_impl.py) points to the wrong place.
- libmpi.so.40 missing: the build uses WM_MPLIB=SYSTEMOPENMPI and even serial
  runs load Pstream, so OpenMPI must be installed.
- Unknown div scheme teno or teno6: libtenoScheme.so is not in
  FOAM_USER_LIBBIN. write_solver_setup succeeds regardless, so this only
  shows up in the solver log.

## Things that are easy to get wrong here

- Never wrap os.environ["ANTHROPIC_API_KEY"] in try/except or a friendly
  error message in agent.py. A missing key there should raise a raw
  KeyError that nothing catches or explains. (The key being optional overall is
  already covered in the README; this is specifically about that one line of
  code.)

- **File encoding**: always pass encoding="utf-8" to open() and
  Path.write_text() in tool_impl.py. Windows defaults to cp1252, which
  silently corrupts non-ASCII output.
- **report_generator.py citation keys must stay deduplicated**, using
  list(dict.fromkeys(keys)), which keeps their order. set() reorders them and
  breaks reproducible citation ordering.
- **cli.py needs its main guard**, the block at the bottom that calls
  main() when the module runs as a script. Don't remove it during refactors;
  it's the actual entry point for the cakecfd console
  script.
- Tool schemas in tools.py and their implementations in tool_impl.py must
  stay in lockstep. A schema change without a matching tool_impl.py update
  imports cleanly and then fails silently at call time.
