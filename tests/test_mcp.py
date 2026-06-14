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


# --- Trust boundary: the load-bearing guardrails of verify_analysis -----------

_PLAIN_RUN = "def run(df, seed=None):\n    return {'n_obs': float(len(df))}\n"


def _make_project(tmp_path, *, run_body, data="data.csv", allow_external=False):
    """Write a minimal, R-free project and return its project.yaml path (str)."""
    proj = tmp_path / "proj"
    proj.mkdir(exist_ok=True)
    (proj / "data.csv").write_text("x\n1\n2\n3\n")
    (proj / "analysis.py").write_text(run_body)
    lines = ["analysis_name: t", f"data: {data}", "python:", "  module: analysis.py", "checks: {}"]
    if allow_external:
        lines.append("allow_external_paths: true")
    (proj / "project.yaml").write_text("\n".join(lines) + "\n")
    return str(proj / "project.yaml")


def test_minimal_env_excludes_secrets(monkeypatch):
    # The verification subprocess must not inherit the server's secrets...
    monkeypatch.setenv("CROSSVERIFY_SECRET_TOKEN", "do-not-leak")
    env = mcp_server._minimal_env()
    assert "CROSSVERIFY_SECRET_TOKEN" not in env
    assert "PATH" in env  # ...but still resolve its interpreter/executables.


def test_force_contain_is_on_by_default(monkeypatch):
    monkeypatch.delenv("CROSSVERIFY_MCP_ALLOW_EXTERNAL", raising=False)
    assert mcp_server._force_contain() is True  # the project flag cannot opt out
    monkeypatch.setenv("CROSSVERIFY_MCP_ALLOW_EXTERNAL", "1")
    assert mcp_server._force_contain() is False  # only the operator can


def test_path_escape_is_invalid_and_runs_no_code(tmp_path):
    # data points outside the project folder; even with allow_external_paths: true
    # in the file, the server forces containment, so no analysis code runs.
    (tmp_path / "outside.csv").write_text("x\n1\n2\n")
    proj = _make_project(tmp_path, run_body=_PLAIN_RUN, data="../outside.csv", allow_external=True)
    result = mcp_server.verify_analysis(proj, skip_r=True)
    assert result["verdict"] == "invalid"
    assert any("resolves outside" in p for p in result["problems"])
    assert not (tmp_path / "proj" / "crossverify_out").exists()


def test_operator_env_restores_project_opt_out(tmp_path, monkeypatch):
    # With CROSSVERIFY_MCP_ALLOW_EXTERNAL set, the out-of-tree project is honored.
    (tmp_path / "outside.csv").write_text("x\n1\n2\n")
    proj = _make_project(tmp_path, run_body=_PLAIN_RUN, data="../outside.csv", allow_external=True)
    monkeypatch.setenv("CROSSVERIFY_MCP_ALLOW_EXTERNAL", "1")
    assert mcp_server.validate_project(proj)["ok"] is True


def test_stdout_print_does_not_corrupt_json(tmp_path):
    # A stray print() in run() must not poison the JSON seam the server parses.
    noisy = (
        "def run(df, seed=None):\n"
        "    print('chatter on stdout')\n"
        "    return {'n_obs': float(len(df))}\n"
    )
    proj = _make_project(tmp_path, run_body=noisy)
    result = mcp_server.verify_analysis(proj, skip_r=True)
    assert result["verdict"] == "pass"
    assert "scope_caveat" in result


def test_timeout_terminates_runaway(tmp_path, monkeypatch):
    # A slow analysis is bounded by CROSSVERIFY_MCP_TIMEOUT and comes back an error.
    slow = (
        "import time\n\n\n"
        "def run(df, seed=None):\n"
        "    time.sleep(30)\n"
        "    return {'n_obs': float(len(df))}\n"
    )
    proj = _make_project(tmp_path, run_body=slow)
    monkeypatch.setenv("CROSSVERIFY_MCP_TIMEOUT", "1")
    result = mcp_server.verify_analysis(proj, skip_r=True)
    assert result["verdict"] == "error"
    assert "timeout" in result["error"]
