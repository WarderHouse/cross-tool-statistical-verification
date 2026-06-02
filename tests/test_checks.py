"""Unit tests for the check primitives. Run with `python -m pytest` or directly:
`python tests/test_checks.py`."""

import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crossverify import cli, consistency, reproduce, triangulate
from crossverify.checks import is_close, severity_for, tol_for
from crossverify.config import Project


def test_is_close_basic():
    assert is_close(1.0, 1.0 + 1e-9)
    assert not is_close(1.0, 1.1)
    assert is_close(-0.7, 0.7, use_abs=True)  # sign-flip tolerated when abs
    assert not is_close(-0.7, 0.7)  # but not by default
    assert not is_close(1.0, float("nan"))


def test_nan_and_inf_policy():
    nan, inf = float("nan"), float("inf")
    assert not is_close(nan, nan)  # two NaN are NOT agreement
    assert not is_close(1.0, nan)
    assert is_close(inf, inf)  # +inf == +inf
    assert not is_close(inf, -inf)
    assert not is_close(inf, 1.0)
    # a NaN must not pass reproducibility as two runs "agreeing"
    assert reproduce.reproducibility({"x": nan}, {"x": nan})[0].passed is False
    # nor read as a cross-tool match
    _, rows = triangulate.triangulate(
        {"x": nan}, {"x": nan}, {"default_atol": 1e-8, "default_rtol": 1e-6}
    )
    assert rows[0]["match"] is False


def test_is_close_symmetric():
    # relative term anchored to max(|a|, |b|): swapping the arguments can't flip the verdict
    for a, b in [(1.0, 1.0 + 9e-7), (100.0, 100.0 + 1e-4), (1.0, 2.0)]:
        assert is_close(a, b, atol=0, rtol=1e-6) == is_close(b, a, atol=0, rtol=1e-6)


def test_tol_for_overrides():
    tol = {
        "default_atol": 1e-8,
        "default_rtol": 1e-6,
        "per_key": {"x": {"atol": 1e-3, "abs": True}},
    }
    assert tol_for(tol, "y") == (1e-8, 1e-6, False)
    assert tol_for(tol, "x") == (1e-3, 1e-6, True)


def _project(**kw):
    p = Project(analysis_name="t", data_path=Path("x"), base_dir=Path("."))
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def test_consistency_ranges_and_signs():
    proj = _project(
        checks={
            "r2": {"kind": "r_squared"},
            "p": {"kind": "p_value"},
            "load": {"kind": "loading"},
            "b": {"kind": "coefficient", "expected_sign": "negative", "severity": "fail"},
            "rs": {"kind": "residual_sum"},
            "n": {"kind": "count", "equals": 3},
        }
    )
    results = {"r2": 0.5, "p": 0.04, "load": -0.9, "b": -2.1, "rs": 1e-12, "n": 3}
    out = {c.name: c.passed for c in consistency.consistency_checks(results, proj, {})}
    assert all(out.values()), out

    bad = {"r2": 1.4, "p": -0.01, "load": 1.2, "b": 3.0, "rs": 0.5, "n": 4}
    out2 = {c.name: c.passed for c in consistency.consistency_checks(bad, proj, {})}
    assert not any(out2.values()), out2


def test_consistency_missing_statistic_fails():
    proj = _project(checks={"r2": {"kind": "r_squared"}})
    out = consistency.consistency_checks({}, proj, {})
    assert out[0].passed is False


def test_residual_sum_scaled():
    # |Σ resid| tolerance should scale to the response magnitude when a column is given
    proj = _project(checks={"rs": {"kind": "residual_sum", "column": "y"}})
    scales = {"y": 1.0e7}  # Σ|y| in the millions
    assert consistency.consistency_checks({"rs": 5.0e-3}, proj, {}, scales)[0].passed is True
    assert consistency.consistency_checks({"rs": 50.0}, proj, {}, scales)[0].passed is False
    # without a column it stays an absolute near-zero check
    proj2 = _project(checks={"rs": {"kind": "residual_sum"}})
    assert consistency.consistency_checks({"rs": 1e-3}, proj2, {}, {})[0].passed is False


def test_loading_standardized():
    proj = _project(checks={"L": {"kind": "loading"}})  # standardized (default)
    assert consistency.consistency_checks({"L": 1.4}, proj, {})[0].passed is False
    proj2 = _project(checks={"L": {"kind": "loading", "standardized": False}})
    assert consistency.consistency_checks({"L": 1.4}, proj2, {})[0].passed is None  # not bounded


def test_sign_severity():
    proj = _project(checks={"b": {"kind": "coefficient", "expected_sign": "negative"}})
    assert consistency.consistency_checks({"b": 3.0}, proj, {})[0].passed is None  # warn -> INFO
    assert consistency.consistency_checks({"b": -3.0}, proj, {})[0].passed is True
    proj2 = _project(
        checks={"b": {"kind": "coefficient", "expected_sign": "negative", "severity": "fail"}}
    )
    assert consistency.consistency_checks({"b": 3.0}, proj2, {})[0].passed is False


def test_centroid_uses_given_ranges():
    proj = _project(checks={"c": {"kind": "centroid", "column": "z"}})
    ranges = {"z": (-1.5, 1.5)}  # e.g. standardized/analyzed space
    assert consistency.consistency_checks({"c": -0.8}, proj, ranges)[0].passed is True
    assert consistency.consistency_checks({"c": 9.0}, proj, ranges)[0].passed is False


def test_group_check_sum_to_n():
    proj = _project(group_checks=[{"kind": "sum_to_n", "keys": ["a", "b", "c"]}])
    ok = consistency.group_checks({"a": 10, "b": 12, "c": 10}, proj, n_rows=32)
    assert ok[0].passed is True
    bad = consistency.group_checks({"a": 10, "b": 12, "c": 5}, proj, n_rows=32)
    assert bad[0].passed is False


def test_spot_check_recompute():
    proj = _project(
        spot_checks=[{"stat": "m", "op": "mean", "column": "x"}],
        tolerance={"default_atol": 1e-8, "default_rtol": 1e-6},
    )
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
    assert consistency.spot_checks({"m": 2.0}, proj, df)[0].passed is True
    assert consistency.spot_checks({"m": 9.9}, proj, df)[0].passed is False


def test_spot_check_std_ddof():
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0]})
    reported = float(np.std(df["x"]))  # numpy: ddof=0 (population)
    tol = {"default_atol": 1e-8, "default_rtol": 1e-6}
    proj0 = _project(
        spot_checks=[{"stat": "s", "op": "std", "column": "x", "ddof": 0}], tolerance=tol
    )
    assert consistency.spot_checks({"s": reported}, proj0, df)[0].passed is True
    # the default (pandas ddof=1) would NOT match a numpy ddof=0 report
    proj1 = _project(spot_checks=[{"stat": "s", "op": "std", "column": "x"}], tolerance=tol)
    assert consistency.spot_checks({"s": reported}, proj1, df)[0].passed is False


def test_reproducibility_tolerance():
    same = reproduce.reproducibility({"a": 1.0, "b": 2.0}, {"a": 1.0, "b": 2.0})
    assert all(c.passed for c in same)
    # last-ULP drift on a correct deterministic value is tolerated
    assert reproduce.reproducibility({"a": 1.0}, {"a": 1.0 + 1e-15})[0].passed is True
    # a real difference is still flagged
    assert reproduce.reproducibility({"a": 1.0}, {"a": 1.0 + 1e-6})[0].passed is False


def test_triangulate_tolerance_and_missing():
    tol = {"default_atol": 1e-6, "default_rtol": 1e-6, "per_key": {"load": {"abs": True}}}
    checks, rows = triangulate.triangulate(
        {"a": 1.0, "load": -0.8, "only_py": 5.0}, {"a": 1.0 + 1e-9, "load": 0.8}, tol
    )
    by = {c.name.split(":")[1]: c.passed for c in checks}
    assert by["a"] is True
    assert by["load"] is True  # magnitude match under abs
    assert by["only_py"] is False  # present in Python, missing in R


def test_triangulate_severity_info():
    # A statistic declared severity: info reports a mismatch as INFO, not FAIL,
    # so a defensible cross-tool divergence does not break the build.
    tol = {"default_atol": 1e-9, "default_rtol": 1e-9, "per_key": {"se": {"severity": "info"}}}
    assert severity_for(tol, "se") == "info"
    assert severity_for(tol, "x") == "fail"  # default
    checks, _ = triangulate.triangulate({"se": 1.0, "x": 1.0}, {"se": 1.2, "x": 2.0}, tol)
    by = {c.name.split(":")[1]: c.passed for c in checks}
    assert by["se"] is None  # advisory mismatch -> INFO
    assert by["x"] is False  # ordinary mismatch -> FAIL
    # a matching advisory statistic still PASSes
    assert triangulate.triangulate({"se": 1.0}, {"se": 1.0}, tol)[0][0].passed is True
    # severity does not rescue a statistic simply absent in one tool
    assert triangulate.triangulate({"se": 1.0}, {}, tol)[0][0].passed is False


# ---- end-to-end cli.main: prepare()/run() data-space contract (findings B/C) ----

_PREPARE_ADAPTER = """\
import os
_COUNT = os.environ["CV_PREP_COUNT"]

def prepare(df, seed=None):
    with open(_COUNT, "a") as fh:
        fh.write("1")            # one mark per prepare() call
    out = df.copy()
    out["z"] = out["x"] - out["x"].mean()    # column "z" exists only after prepare()
    return out

def run(df, seed=None):
    # df must be the PREPARED frame: a raw-df hand-off would KeyError on "z".
    return {"c": float(df["z"].iloc[0]), "n": float(len(df))}
"""


def _prepare_project(tmp):
    tmp = Path(tmp)
    (tmp / "data.csv").write_text("x\n1\n2\n3\n")
    (tmp / "analysis.py").write_text(_PREPARE_ADAPTER)
    (tmp / "project.yaml").write_text(
        "analysis_name: t\n"
        "data: data.csv\n"
        "python: {module: analysis.py}\n"
        "checks:\n"
        "  c: {kind: centroid, column: z}\n"
        "  n: {kind: count, equals: 3}\n"
    )
    return tmp / "project.yaml"


def test_main_prepare_called_once_feeds_run():
    tmp = tempfile.mkdtemp()
    proj = _prepare_project(tmp)
    count = Path(tmp) / "count.txt"
    os.environ["CV_PREP_COUNT"] = str(count)
    try:
        # Phases 1-4 (no R, so skip 5). run() needs the prepared "z" column;
        # reaching rc == 0 proves run() received the prepared frame, not raw df.
        rc = cli.main(
            ["--project", str(proj), "--out", str(Path(tmp) / "out"), "--phases", "1,2,3,4"]
        )
        assert rc == 0
        # prepare() ran exactly once across phases 2/3/4 (run() itself runs twice in 4).
        assert count.read_text() == "1"
    finally:
        os.environ.pop("CV_PREP_COUNT", None)


def test_main_phase1_skips_prepare():
    tmp = tempfile.mkdtemp()
    proj = _prepare_project(tmp)
    count = Path(tmp) / "count.txt"
    os.environ["CV_PREP_COUNT"] = str(count)
    try:
        rc = cli.main(["--project", str(proj), "--out", str(Path(tmp) / "out"), "--phases", "1"])
        assert rc == 0
        assert not count.exists()  # an intake-only run never calls prepare()
    finally:
        os.environ.pop("CV_PREP_COUNT", None)


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} tests passed")


if __name__ == "__main__":
    _run_all()
