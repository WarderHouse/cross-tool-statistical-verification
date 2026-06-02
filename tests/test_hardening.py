"""Unit tests for the security-hardening changes (issue #1, F1/F2/F5).

Run directly or under pytest:
    python tests/test_hardening.py
    python -m pytest tests/test_hardening.py
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crossverify.config import Project, _within_base
from crossverify.report import _render
from crossverify.runner import _r_child_env


def _project(base, **kw):
    p = Project(analysis_name="t", data_path=Path(base) / "data.csv", base_dir=Path(base))
    for k, v in kw.items():
        setattr(p, k, v)
    return p


# ---- F1: path containment ------------------------------------------------- #


def test_within_base_relative_ok():
    base = Path(tempfile.mkdtemp())
    assert _within_base(base / "sub" / "x.csv", base) is True
    assert _within_base(base / ".." / "x.csv", base) is False  # escapes base
    assert _within_base("/etc/passwd", base) is False  # absolute outside


def test_external_path_rejected():
    base = tempfile.mkdtemp()
    outside = Path(tempfile.mkdtemp()) / "evil.py"
    proj = _project(base, python_module=outside, r_script=Path("/etc/hosts"))
    problems = proj.validate()
    flagged = [p for p in problems if "outside the project folder" in p]
    assert any("python.module" in p for p in flagged), problems
    assert any("r.script" in p for p in flagged), problems


def test_allow_external_paths_optout():
    base = tempfile.mkdtemp()
    outside = Path(tempfile.mkdtemp()) / "evil.py"
    proj = _project(base, python_module=outside, allow_external_paths=True)
    assert not any("outside the project folder" in p for p in proj.validate())


def test_load_parses_allow_external_paths():
    d = Path(tempfile.mkdtemp())
    (d / "p.yaml").write_text(
        "data: data.csv\npython: {module: a.py}\nallow_external_paths: true\n"
    )
    assert Project.load(d / "p.yaml").allow_external_paths is True
    (d / "q.yaml").write_text("data: data.csv\npython: {module: a.py}\n")
    assert Project.load(d / "q.yaml").allow_external_paths is False


# ---- F5: minimal R child environment -------------------------------------- #


def test_r_child_env_drops_secrets():
    saved = {k: os.environ.get(k) for k in ("AWS_SECRET_ACCESS_KEY", "R_LIBS", "PATH")}
    try:
        os.environ["AWS_SECRET_ACCESS_KEY"] = "shhh"
        os.environ["R_LIBS"] = "/opt/Rlibs"
        os.environ.setdefault("PATH", "/usr/bin")
        env = _r_child_env("/tmp/helper.R")
        assert "AWS_SECRET_ACCESS_KEY" not in env  # secret withheld
        assert "PATH" in env  # needed, kept
        assert env.get("R_LIBS") == "/opt/Rlibs"  # R_* family kept
        assert env["CROSSVERIFY_R"] == "/tmp/helper.R"
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ---- F2: safe template rendering ------------------------------------------ #


def test_render_tolerates_bad_template():
    # Unknown placeholder is left intact instead of raising.
    assert _render("Hi $name, $missing", {"name": "X"}) == "Hi X, $missing"
    # A stray brace (would break str.format) is harmless here.
    assert _render("a { b $name", {"name": "Y"}) == "a { b Y"
    # Fully-populated template substitutes correctly.
    assert _render("$a-$b", {"a": "1", "b": "2"}) == "1-2"


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == "__main__":
    _run_all()
