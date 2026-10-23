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

import argparse
import inspect
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

        try:
            kwargs = json.loads(args.args)
        except json.JSONDecodeError as exc:
            print(json.dumps({"error": f"--args is not valid JSON: {exc}"}, indent=2))
            sys.exit(1)
        if not isinstance(kwargs, dict):
            print(json.dumps({"error": "--args must be a JSON object"}, indent=2))
            sys.exit(1)

        sig = inspect.signature(fn)
        if args.case and "case_dir" in sig.parameters and "case_dir" not in kwargs:
            kwargs["case_dir"] = args.case

        try:
            sig.bind(**kwargs)
        except TypeError as exc:
            print(json.dumps({"error": f"Bad arguments for {args.tool}: {exc}"}, indent=2))
            sys.exit(1)

        result = fn(**kwargs)
        print(json.dumps(result, indent=2, default=str))
        return

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
    # Imported after CakeAgent so a missing package hits its clearer ImportError.
    import anthropic

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

        try:
            agent.chat(user_input)
        except anthropic.APIError as e:
            console.print(f"[bold red]API error:[/bold red] {e}")


if __name__ == "__main__":
    main()
