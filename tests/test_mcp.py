"""Tests for the MCP server (crossverify.mcp_server).

Skipped wholesale unless the optional 'mcp' extra is installed (it requires
Python >= 3.10), so the default test matrix that doesn't install it just skips.
"""

import asyncio
from pathlib import Path

import pytest

# Skip everything here if the 'mcp' extra is not installed.
mcp_server = pytest.importorskip("crossverify.mcp_server")

_ROOT = Path(__file__).resolve().parent.parent
_EXAMPLE = str(_ROOT / "examples" / "project.yaml")
_MTCARS = str(_ROOT / "examples" / "data" / "mtcars.csv")
_TOOLS = {"verify_analysis", "validate_project", "scaffold_project", "inspect_dataset"}


def test_tools_register_with_schemas():
    tools = asyncio.run(mcp_server.mcp.list_tools())
    assert _TOOLS <= {t.name for t in tools}
    # The input schema generated from the type annotations (the integration point).
    va = next(t for t in tools if t.name == "verify_analysis")
    assert set(va.inputSchema["properties"]) >= {"project_path", "phases", "skip_r", "seed"}


def test_verify_analysis_runs_subprocess_and_carries_caveat():
    # skip_r keeps it Python-only (no R needed on the runner). This exercises the
    # full bounded-subprocess path: spawn `crossverify --json`, parse, return.
    result = mcp_server.verify_analysis(_EXAMPLE, skip_r=True)
    assert result["verdict"] == "pass"
    assert result["totals"]["failed"] == 0
    # The honest-scope caveat must reach the agent so it cannot over-claim.
    assert "implementation-independent" in result["scope_caveat"]


def test_verify_analysis_missing_project_is_error_not_crash():
    result = mcp_server.verify_analysis(str(_ROOT / "nope" / "missing.yaml"))
    assert result["verdict"] == "error"
    assert "not found" in result["error"]


def test_call_tool_protocol_roundtrip():
    # Exercise the MCP protocol layer (not just the bare function): list -> call.
    out = asyncio.run(mcp_server.mcp.call_tool("validate_project", {"project_path": _EXAMPLE}))
    assert out is not None  # returns content blocks / structured result without error


def test_read_only_tools(tmp_path):
    assert mcp_server.validate_project(_EXAMPLE)["ok"] is True
    info = mcp_server.inspect_dataset(_MTCARS)
    assert info["rows"] == 32 and "mpg" in info["columns"]
    scaffolded = mcp_server.scaffold_project(str(tmp_path / "proj"))
    assert len(scaffolded["written"]) == 3
