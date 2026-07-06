"""Generate a standalone JSON-Schema registry for all AE402 MCP tools.

Run: python scripts/gen_mcp_tools_schema.py
Writes: docs/mcp_tools_schema.json (name, description, inputSchema for each tool)
so integrators/judges can browse the full tool surface without running the
MCP server itself. Requires `pip install mcp`.
"""
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from sdk.mcp_server import TOOLS  # noqa: E402

registry = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "AgentEscrow402 MCP Tool Registry",
    "description": (
        "JSON-Schema definitions for all tools exposed by the AE402 MCP server "
        "(sdk/mcp_server.py). Generated from the live TOOLS list, not hand-maintained."
    ),
    "tool_count": len(TOOLS),
    "tools": [
        {
            "name": t.name,
            "description": t.description,
            "inputSchema": t.inputSchema,
        }
        for t in TOOLS
    ],
}

out_path = os.path.join(REPO_ROOT, "docs", "mcp_tools_schema.json")
with open(out_path, "w") as f:
    json.dump(registry, f, indent=2)
    f.write("\n")

print(f"Wrote {len(TOOLS)} tool schemas to {out_path}")
