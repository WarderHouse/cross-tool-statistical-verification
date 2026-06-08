"""Tests for the programmatic API (crossverify.api).

These exercise the API directly (the layer the CLI and the MCP server both wrap),
without R, so Phase 5 auto-skips on a runner without Rscript.
"""

import tempfile
from pathlib import Path

from crossverify import api

_ANALYSIS = """\
def run(df, seed=None):
    return {"n": float(len(df)), "mx": float(df["x"].max())}
"""


def _project(tmp, *, data="x\\n1\\n2\\n3\\n", checks="  n: {kind: count, equals: 3}\\n"):
    tmp = Path(tmp)
    (tmp / "data.csv").write_text(data.replace("\\n", "\n"))
    (tmp / "analysis.py").write_text(_ANALYSIS)
    (tmp / "project.yaml").write_text(
        "analysis_name: t\n"
        "data: data.csv\n"
        "python: {module: analysis.py}\n"
        "checks:\n" + checks.replace("\\n", "\n")
    )
    return tmp / "project.yaml"


def test_verify_pass_structured_result():
    tmp = tempfile.mkdtemp()
    proj = _project(tmp)
    result = api.verify(proj, phases={1, 3, 4}, out=str(Path(tmp) / "out"))
    assert result["verdict"] == "pass"
    assert result["totals"]["failed"] == 0
    assert result["totals"]["passed"] >= 1
    # Structured, agent-friendly shape with the honest-scope caveat carried along.
    for key in ("checks", "comparison", "output_paths", "scope_caveat", "tool_version"):
        assert key in result
    assert "implementation-independent" in result["scope_caveat"]
    # Every check is a serialized record (no CheckResult objects leak through).
    assert all(
        set(c) == {"phase", "name", "description", "status", "detail"} for c in result["checks"]
    )
    # The four artifacts were written where the result says they are.
    assert Path(result["output_paths"]["results_json"]).exists()
    assert Path(result["output_paths"]["verification_log"]).exists()


def test_verify_fail_is_a_result_not_an_exception():
    tmp = tempfile.mkdtemp()
    # Declare the count as 99 when there are 3 rows -> a failed check, not a crash.
    proj = _project(tmp, checks="  n: {kind: count, equals: 99}\\n")
    result = api.verify(proj, phases={3}, out=str(Path(tmp) / "out"))
    assert result["verdict"] == "fail"
    assert result["totals"]["failed"] >= 1


def test_verify_skip_r_marks_phase5_skipped():
    tmp = tempfile.mkdtemp()
    proj = _project(tmp)
    result = api.verify(proj, skip_r=True, out=str(Path(tmp) / "out"))
    assert result["verdict"] == "pass"
    skipped = [c for c in result["checks"] if c["phase"] == "5" and c["status"] == "INFO"]
    assert skipped and "skip" in skipped[0]["detail"].lower()


def test_verify_invalid_project_returns_problems():
    tmp = tempfile.mkdtemp()
    proj = _project(tmp)
    # Point data at a file that does not exist -> validation problem, no user code runs.
    (Path(tmp) / "project.yaml").write_text(
        "analysis_name: t\ndata: missing.csv\npython: {module: analysis.py}\n"
    )
    result = api.verify(proj)
    assert result["verdict"] == "invalid"
    assert any("missing.csv" in p for p in result["problems"])


def test_validate_clean_and_broken():
    tmp = tempfile.mkdtemp()
    proj = _project(tmp)
    assert api.validate(proj) == []
    (Path(tmp) / "data.csv").unlink()
    assert any("data file not found" in p for p in api.validate(proj))


def test_scaffold_writes_then_skips():
    tmp = tempfile.mkdtemp()
    first = api.scaffold(tmp)
    assert {Path(p).name for p in first["written"]} == {"project.yaml", "analysis.py", "analysis.R"}
    assert first["skipped"] == []
    second = api.scaffold(tmp)
    assert second["written"] == []
    assert len(second["skipped"]) == 3


def test_inspect_dataset_summary():
    tmp = tempfile.mkdtemp()
    (Path(tmp) / "data.csv").write_text("x,y\n1,4\n2,5\n3,6\n")
    info = api.inspect_dataset(Path(tmp) / "data.csv")
    assert info["rows"] == 3
    assert info["columns"] == ["x", "y"]
    assert info["checks"]  # Phase-1 intake produced records


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == "__main__":
    _run_all()
