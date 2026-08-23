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
CakeAgent: the main agentic loop.

Usage:
    from cakecfd_ai import CakeAgent

    agent = CakeAgent(
        case_dir="/path/to/your/openfoam/case",
        api_key="sk-ant-...",   # or set ANTHROPIC_API_KEY
    )
    agent.chat("Run the solver for 200 iterations, then tell me the drag force.")
"""

import json
import os
from typing import Iterator

from .tools import TOOLS
from .tool_impl import DISPATCH

SYSTEM_PROMPT = """You are an expert CFD engineer integrated into CakeCFD: an
CakeFOAM-based CFD software. You have access to tools that let you:
- Run CakeFOAM solvers and inspect their convergence
- Read force/residual results
- Modify case parameters (velocity, mesh refinement, etc.)
- Query external turbulence databases (JHTDB)
- Load and inspect geometry files

Always explain what you are doing before calling a tool. After getting results,
interpret them in the context of fluid dynamics: reference Reynolds number, Cd/Cl,
convergence criteria, numerical stability as appropriate.

## Report pipeline

After every solver run, two files are auto-generated in the case directory:
- **report.md**: human-readable markdown with inputs, convergence table, forces, and cited references.
  Always tell the user: "Your full report is at `report.md` in your case directory."
- **results_summary.json**: compact machine-readable JSON for your internal use.

When you need post-run data (residuals, forces, Re, mesh info), call `get_results_summary` first :
it returns everything in one low-token call. Only fall back to `read_residuals` or `read_forces`
if the JSON is missing or stale. Never summarise the raw log in full: that wastes tokens.

When the user asks you to run a simulation, do so, then give a brief summary:
1. Convergence status
2. Key aerodynamic coefficients (from get_results_summary)
3. Any warnings or numerical issues
4. Point to report.md for the full details

Be concise but technically precise."""


class CakeAgent:
    def __init__(
        self,
        case_dir: str | None = None,
        api_key: str | None = None,
        model: str = "claude-sonnet-5",
        max_tokens: int = 4096,
    ):
        try:
            import anthropic as _anthropic
        except ImportError:
            raise ImportError(
                "The 'anthropic' package is required to use CakeAgent. "
                "Install it with: pip install anthropic"
            ) from None

        self.case_dir = case_dir
        self.model = model
        self.max_tokens = max_tokens
        self.client = _anthropic.Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self._history: list[dict] = []


    def _call_tool(self, name: str, inputs: dict) -> str:
        """Dispatch a tool call and return a JSON string result."""
        fn = DISPATCH.get(name)
        if fn is None:
            return json.dumps({"error": f"Unknown tool: {name}"})

        # Inject case_dir if the tool accepts it and it wasn't specified
        if "case_dir" in fn.__code__.co_varnames and "case_dir" not in inputs:
            if self.case_dir:
                inputs = {"case_dir": self.case_dir, **inputs}

        try:
            result = fn(**inputs)
        except Exception as e:
            result = {"error": str(e)}

        return json.dumps(result, indent=2)


    def chat(self, user_message: str, *, stream: bool = True) -> str:
        """
        Send a message, run the agentic tool loop, and return the final text.
        Prints streamed output to stdout if stream=True.
        """
        from rich.console import Console
        from rich.markdown import Markdown

        console = Console()
        self._history.append({"role": "user", "content": user_message})

        final_text = ""

        while True:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=self._history,
            )

            # Collect assistant content
            assistant_content = []
            text_parts: list[str] = []
            tool_calls: list[dict] = []

            for block in response.content:
                assistant_content.append(block)
                if block.type == "text":
                    text_parts.append(block.text)
                elif block.type == "tool_use":
                    tool_calls.append(block)

            if text_parts:
                combined = "\n".join(text_parts)
                final_text = combined
                if stream:
                    console.print(Markdown(combined))

            self._history.append({"role": "assistant", "content": assistant_content})

            if response.stop_reason == "end_turn" or not tool_calls:
                break

            # Execute tools and feed results back
            tool_results = []
            for tc in tool_calls:
                if stream:
                    console.print(f"[bold cyan]>> Tool:[/bold cyan] {tc.name}({json.dumps(tc.input, indent=2)})")

                result_str = self._call_tool(tc.name, tc.input)

                if stream:
                    console.print(f"[dim]{result_str[:500]}[/dim]")

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": result_str,
                })

            self._history.append({"role": "user", "content": tool_results})

        return final_text

    def reset(self):
        """Clear conversation history."""
        self._history.clear()
