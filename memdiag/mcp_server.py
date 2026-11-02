"""MCP server: lets an agent (for example Claude Code) run memory diagnostics.

Run with:  python -m memdiag.mcp_server
Requires:  pip install "mcp>=2"
"""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from . import run_files
from .report import text_report

server = MCPServer("memdiag", instructions=(
    "Memory diagnostics for AI agents. Point it at a JSONL file of the agent's "
    "conversation logs to separate memory failures from retrieval failures and "
    "compare candidate memory strategies."))


@server.tool(description="Diagnose an agent's conversation logs. Returns failure counts by "
                         "memory vs retrieval, each finding with evidence, and a strategy comparison.")
def diagnose_traces(traces_path: str, docs_path: str | None = None) -> dict:
    res = run_files(traces_path, docs_path)
    return {"summary": {k: v for k, v in res["summary"].items()}, "stats": res["stats"],
            "findings": res["findings"], "strategies": res["strategies"]}


@server.tool(description="Diagnose logs and return a short plain-text report for a human.")
def diagnose_report(traces_path: str, docs_path: str | None = None) -> str:
    return text_report(run_files(traces_path, docs_path), color=False)


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()
