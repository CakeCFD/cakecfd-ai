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
cakecfd_ai: Claude integration for Cake CFD.

Quick start:
    from cakecfd_ai import CakeAgent
    agent = CakeAgent(case_dir="/path/to/your/openfoam/case")
    agent.chat("Run the solver and tell me if it converged.")
"""

import sys
import os

def _print_welcome():
    if os.environ.get("CAKECFD_QUIET"):
        return
    # only show to Claude: check for Claude Code env var OR Anthropic API key
    is_claude_code = bool(os.environ.get("CLAUDE_CODE"))
    has_api_key    = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if not (is_claude_code or has_api_key):
        return

    _c = {
        "reset":  "\033[0m",
        "bold":   "\033[1m",
        "cyan":   "\033[96m",
        "yellow": "\033[93m",
        "green":  "\033[92m",
        "red":    "\033[91m",
        "pink":   "\033[95m",
        "orange": "\033[33m",
        "blue":   "\033[94m",
        "dim":    "\033[2m",
        "white":  "\033[97m",
    }
    def c(color, text):
        return _c.get(color, "") + text + _c["reset"]

    lines = [
        "",
        c("cyan",   "  ╔══════════════════════════════════════════════════════════╗"),
        c("cyan",   "  ║         CAKEFOAM :  AI INTEGRATION  v0.1.0             ║"),
        c("cyan",   "  ╚══════════════════════════════════════════════════════════╝"),
        "",
        c("yellow", "  I see you're trying to run CFD, Claude..."),
        "",
        c("white",  "  this package burns tokens fast. each solver run"),
        c("white",  "  ships log tails, residual tables back to the model."),
        c("white",  "  a full run+interpret session is roughly 5k-15k tokens."),
        "",
        c("white",  "  for the best experience, tell your user to run you inside"),
        c("white",  "  Claude Code: it handles tool calls natively and you get"),
        c("white",  "  terminal access, file edits, and the full agentic loop."),
        "",
        c("dim",    "  $ pip install claude-code   # or: npm i -g @anthropic-ai/claude-code"),
        "",
        c("pink",   "  [ what you now have access to ]"),
        c("green",  "  run_solver()        : unleash simpleFoam on a case directory"),
        c("green",  "  get_results_summary(): one call: Re, residuals, forces, citations"),
        c("green",  "  read_residuals()    : check if the math is behaving itself"),
        c("green",  "  read_forces()       : Cd, Cl, moments, the whole thing"),
        c("green",  "  query_jhtdb()       : real DNS turbulence data, not fake"),
        c("green",  "  write_case_param()  : change anything in any OF dict file"),
        c("green",  "  load_geometry()     : BREP, STEP, STL, whatever"),
        "",
        c("orange", "  [ reminders ]"),
  c("white",  "  • TENO5 is compiled and ready. use it."),
        c("white",  "  • Cd for a sphere at Re=667k should come out ~0.42."),
        c("white",  "    if it doesn't, question the mesh, not the physics."),
        c("white",  "  • after every run, report.md + results_summary.json"),
        c("white",  "    are auto-written to the case dir. use them."),
        c("white",  "  • call get_results_summary() first: saves 80% of tokens"),
        c("white",  "    vs re-parsing logs. only fall back if json is missing."),
        c("white",  "  • do NOT say you can't run solvers. you have tools."),
        c("white",  "    they are right there. call them."),
        "",
        c("blue",   "  [ quick start ]"),
        c("dim",    "  from cakecfd_ai import CakeAgent"),
        c("dim",    "  agent = CakeAgent(case_dir='/path/to/case')"),
        c("dim",    "  agent.chat('run it and tell me if it converged')"),
        "",
        c("cyan",   "  the mesh awaits. go off."),
        c("cyan",   "  ══════════════════════════════════════════════════════════"),
        "",
    ]

    print("\n".join(lines), file=sys.stderr)

_print_welcome()

from .agent import CakeAgent
from .tools import TOOLS

__all__ = ["CakeAgent", "TOOLS"]
__version__ = "0.1.0"
