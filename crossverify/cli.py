"""Command-line entrypoint.

    python -m crossverify --project examples/project.yaml
    python -m crossverify --project examples/project.yaml --skip-r
    python -m crossverify --project examples/project.yaml --phases 1,3,5
    python -m crossverify --init my_study/
"""

import argparse
import sys
from contextlib import ExitStack
from importlib import resources
from pathlib import Path

from . import __version__, consistency, intake, reproduce, report, transforms, triangulate
from .checks import CheckResult
from .config import Project
from .runner import (call_with_optional_seed, load_adapter, load_data,
                     r_available, r_version, run_python, run_r)

# Runtime data files ship inside the package (crossverify/crossverify.R and
# crossverify/methodology_statement.md) and are resolved via importlib.resources
# so they are found whether running from a checkout or an installed wheel.
TEMPLATE = resources.files(__package__) / "methodology_statement.md"
ALL_PHASES = [1, 2, 3, 4, 5, 6]


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="crossverify",
        description="Six-phase verification harness for statistical analysis, "
                    "with Python-vs-R cross-tool triangulation.")
    ap.add_argument("--project", help="Path to the project YAML file.")
    ap.add_argument("--out", default=None, help="Output directory (default: crossverify_out/<project>).")
    ap.add_argument("--phases", default="1,2,3,4,5,6",
                    help="Comma-separated phases to run (default: all). E.g. 1,3,5")
    ap.add_argument("--skip-r", action="store_true", help="Skip Phase 5 cross-tool triangulation.")
    ap.add_argument("--seed", type=int, default=None, help="Override the project's random seed.")
    ap.add_argument("--init", metavar="DIR", help="Scaffold a new project in DIR and exit.")
    ap.add_argument("--version", action="version", version=f"crossverify {__version__}")
    args = ap.parse_args(argv)

    if args.init:
        return _init(args.init)
    if not args.project:
        ap.error("--project is required (or use --init DIR)")

    phases = {int(x) for x in args.phases.split(",") if x.strip()}

    project = Project.load(args.project)
    if args.seed is not None:
        project.seed = args.seed
    problems = project.validate()
    if problems:
        print("Project has problems:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2

    df = load_data(project.data_path)
    adapter = load_adapter(project.python_module)

    all_results = []
    intake_artifacts = {}
    comparison_rows = []

    # If the analysis declares a prepare() step, it is the single source of truth
    # for the "analyzed" frame: the Phase-2 snapshot, the Phase-3 consistency
    # ranges/scales, and the frame handed to run() all derive from it, so they
    # cannot drift into different spaces. prepare() is called at most once, and
    # only when a phase actually needs it (never for an intake-only run).
    prepare = getattr(adapter, "prepare", None)
    prepared = None
    if callable(prepare) and (phases & {2, 3, 4, 5}):
        prepared = call_with_optional_seed(prepare, df.copy(), project.seed)
    analyzed = prepared if prepared is not None else df

    if 1 in phases:
        res, intake_artifacts = intake.inspect(df)
        all_results += res

    if 2 in phases:
        res, _ = transforms.run_phase(adapter, df, project, prepared=prepared)
        all_results += res

    # Phases 3-5 all need the Python analysis result, computed on the analyzed
    # frame so the statistics and the consistency ranges share one space.
    py_results = None
    if phases & {3, 4, 5}:
        py_results = run_python(adapter, analyzed, project.seed)

    if 3 in phases:
        ranges = intake.numeric_ranges(analyzed)
        data_scales = {c: float(analyzed[c].abs().sum())
                       for c in analyzed.select_dtypes("number").columns}
        all_results += consistency.consistency_checks(py_results, project, ranges, data_scales)
        all_results += consistency.group_checks(py_results, project, len(df))
        # Spot-checks recompute against the raw, as-loaded data on purpose: an
        # independent sanity check against the original source, not the prepared frame.
        all_results += consistency.spot_checks(py_results, project, df)

    if 4 in phases:
        py_results_2 = run_python(adapter, analyzed, project.seed)
        all_results += reproduce.reproducibility(py_results, py_results_2, project.reproducibility)

    rver = "not run"
    if 5 in phases:
        if args.skip_r:
            all_results.append(CheckResult("5", "triangulate:skipped",
                                           "Cross-tool triangulation", None, "skipped: --skip-r"))
        elif not project.r_script:
            all_results.append(CheckResult("5", "triangulate:skipped",
                                           "Cross-tool triangulation", None,
                                           "skipped: no r.script declared in the project"))
        elif not r_available():
            all_results.append(CheckResult("5", "triangulate:skipped",
                                           "Cross-tool triangulation", None,
                                           "skipped: Rscript not found on PATH"))
        else:
            # The R helper must be a concrete file on disk for the subprocess.
            # importlib.resources.as_file materializes it (extracting from a zip
            # if needed); the ExitStack keeps it alive for the run_r call.
            with ExitStack() as stack:
                helper_r = stack.enter_context(
                    resources.as_file(resources.files(__package__) / "crossverify.R"))
                r_results, _ = run_r(project.r_script, project.data_path, project.seed, helper_r)
            rver = r_version()
            checks, comparison_rows = triangulate.triangulate(py_results, r_results, project.tolerance)
            all_results += checks

    out_dir = Path(args.out) if args.out else Path("crossverify_out") / Path(args.project).stem
    env = report.env_info(rver)
    summary = report.compile_report(project, out_dir, all_results, intake_artifacts,
                                    comparison_rows, env, TEMPLATE)

    _print_summary(project, all_results, comparison_rows, summary, phases)
    return 0 if summary["failed"] == 0 else 1


def _print_summary(project, all_results, comparison_rows, summary, phases):
    titles = {"1": "intake", "2": "transforms", "3": "consistency",
              "4": "reproducibility", "5": "triangulation"}
    print(f"\ncrossverify {__version__} — {project.analysis_name}")
    for p in ("1", "2", "3", "4", "5"):
        rows = [r for r in all_results if r.phase == p]
        if not rows:
            continue
        pa = sum(1 for r in rows if r.passed is True)
        fa = sum(1 for r in rows if r.passed is False)
        inf = sum(1 for r in rows if r.passed is None)
        bits = []
        if pa:
            bits.append(f"{pa} pass")
        if fa:
            bits.append(f"{fa} FAIL")
        if inf:
            bits.append(f"{inf} info")
        print(f"  Phase {p} {titles[p]:<16} {', '.join(bits)}")
    if comparison_rows:
        matched = sum(1 for r in comparison_rows if r["match"])
        print(f"  Cross-tool: {matched}/{len(comparison_rows)} statistics matched within tolerance.")
    verdict = "PASS" if summary["failed"] == 0 else "FAIL"
    print(f"\nResult: {verdict} ({summary['passed']} passed, {summary['failed']} failed, "
          f"{summary['info']} informational)")
    print(f"Wrote: {summary['out_dir']}/  "
          f"(verification_log.md, comparison_table.md, methodology_statement.md, "
          f"verification_results.json)")


def _init(target):
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    files = {
        "project.yaml": _INIT_PROJECT,
        "analysis.py": _INIT_PY,
        "analysis.R": _INIT_R,
    }
    written = []
    for name, content in files.items():
        path = target / name
        if path.exists():
            print(f"  skip (exists): {path}")
            continue
        path.write_text(content)
        written.append(str(path))
    print(f"Scaffolded a project in {target}/")
    for w in written:
        print(f"  wrote {w}")
    print("\nNext: point 'data:' at your dataset, fill in the analysis, then run:")
    print(f"  python -m crossverify --project {target / 'project.yaml'}")
    return 0


_INIT_PROJECT = """\
analysis_name: "Describe your analysis here"
seed: null            # set an integer if the analysis uses randomness

data: data/your_dataset.csv
python:
  module: analysis.py   # must define run(df, seed=None) -> dict of {name: number}
r:
  script: analysis.R    # the independent replication; emit the same names

# allow_external_paths: false   # set true to permit data/scripts outside this folder

# Phase 3 — internal consistency checks, keyed by emitted statistic name.
# kinds: r_squared, p_value, proportion, variance_explained, loading, correlation,
#        count (+ equals), coefficient (+ expected_sign), residual_sum, converged, centroid (+ column)
checks: {}

# Phase 3 — recompute a reported value directly from the raw data.
# ops: mean, sum, count, median, std, min, max  (optional: where: {column, equals})
spot_checks: []

# Phase 5 — comparison tolerances (per_key overrides the defaults; abs: true compares magnitudes)
tolerance:
  default_atol: 1.0e-8
  default_rtol: 1.0e-6

metadata:
  python_libs: []
"""

_INIT_PY = '''\
"""Python analysis adapter. Must define run(df, seed=None) -> dict of {name: number}."""


def run(df, seed=None):
    # Compute the statistics you want verified and return them as a flat dict.
    return {
        "n_obs": float(len(df)),
    }
'''

_INIT_R = '''\
# Independent R replication. Emit the SAME statistic names as analysis.py.
source(Sys.getenv("CROSSVERIFY_R"))
args <- cv_args()
d <- read.csv(args$data, stringsAsFactors = FALSE)

cv_emit(list(
  n_obs = nrow(d)
), args$out)
'''
