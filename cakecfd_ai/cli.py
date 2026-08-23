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
CLI entry point:  cakecfd [--case CASE_DIR] [--model MODEL]

Opens an interactive REPL where you type natural language commands
and Claude drives Cake CFD tools in response.

Direct tool mode (no API key needed):
    cakecfd --tool TOOLNAME --case DIR [--args '{"key": "value"}']
    cakecfd --list-tools
"""

import argparse
import json
import os
import sys

from rich.console import Console
from rich.prompt import Prompt


def main():
    parser = argparse.ArgumentParser(
        prog="cakecfd",
        description="Claude-powered Cake CFD assistant",
    )
    parser.add_argument("--case", metavar="DIR", help="OpenFOAM case directory")
    parser.add_argument(
        "--model",
        default="claude-sonnet-5",
        help="Claude model (default: claude-sonnet-5)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Anthropic API key (default: $ANTHROPIC_API_KEY)",
    )
    parser.add_argument(
        "--tool", metavar="NAME",
        help="Call a tool directly (no API key required)",
    )
    parser.add_argument(
        "--args", metavar="JSON", default="{}",
        help="JSON dict of arguments for --tool (default: {})",
    )
    parser.add_argument(
        "--list-tools", action="store_true",
        help="List all available tools and exit",
    )
    args = parser.parse_args()

    # Direct tool mode (no API key)
    if args.list_tools or args.tool:
        from .tool_impl import DISPATCH
        if args.list_tools:
            for name in sorted(DISPATCH):
                print(name)
            return

        fn = DISPATCH.get(args.tool)
        if fn is None:
            print(f"Unknown tool '{args.tool}'. Run --list-tools to see available tools.",
                  file=sys.stderr)
            sys.exit(1)

        kwargs = json.loads(args.args)
        if args.case and "case_dir" not in kwargs:
            kwargs["case_dir"] = args.case

        result = fn(**kwargs)
        print(json.dumps(result, indent=2, default=str))
        return

    # Interactive REPL mode
    from .agent import CakeAgent

    console = Console()
    console.print("[bold green]Cake CFD AI[/bold green] : powered by Claude 5")
    console.print(f"Model : {args.model}")
    console.print(f"Case  : {args.case or '(none: specify per message)'}")
    console.print("Type [bold]exit[/bold] or Ctrl-C to quit.\n")

    agent = CakeAgent(
        case_dir=args.case,
        api_key=args.api_key,
        model=args.model,
    )

    while True:
        try:
            user_input = Prompt.ask("[bold blue]You[/bold blue]")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Bye.[/dim]")
            sys.exit(0)

        if user_input.strip().lower() in {"exit", "quit", "q"}:
            console.print("[dim]Bye.[/dim]")
            sys.exit(0)

        if not user_input.strip():
            continue

        agent.chat(user_input)


if __name__ == "__main__":
    main()
