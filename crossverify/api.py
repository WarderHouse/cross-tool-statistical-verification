"""Programmatic API for the crossverify verification harness.

These functions are the single source of truth for running a verification: the
command-line interface (:mod:`crossverify.cli`) and the MCP server
(:mod:`crossverify.mcp_server`) are thin wrappers over them. Unlike the CLI, they
return structured data instead of printing and exiting, so a caller — a human
script or an autonomous agent — can branch on the result without parsing console
text.

The honest-scope caveat (:data:`SCOPE_CAVEAT`) is carried in every :func:`verify`
result so an automated caller cannot quietly over-claim a verified analysis.
"""

from __future__ import annotations

from contextlib import ExitStack
from importlib import resources
from pathlib import Path

from . import consistency, intake, report, reproduce, transforms, triangulate
from .checks import CheckResult
from .config import Project
from .runner import (
    call_with_optional_seed,
    load_adapter,
    load_data,
    r_available,
    r_version,
    run_python,
    run_r,
)

ALL_PHASES = [1, 2, 3, 4, 5, 6]

# Runtime data file shipped inside the package; resolved via importlib.resources
# so it is found whether running from a checkout or an installed wheel.
TEMPLATE = resources.files(__package__) / "methodology_statement.md"

SCOPE_CAVEAT = (
    "crossverify establishes that a result is implementation-independent — "
    "internally consistent, reproducible, and in agreement across an independent "
    "Python and R implementation. It does NOT establish that the result is correct: "
    "you write both implementations, so a shared specification error agrees perfectly. "
    "Agreement is strong evidence against tool-specific artifacts, not proof the "
    "analysis is right."
)

# Scaffolding templates for a new project (used by scaffold()).
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

_INIT_R = """\
# Independent R replication. Emit the SAME statistic names as analysis.py.
source(Sys.getenv("CROSSVERIFY_R"))
args <- cv_args()
d <- read.csv(args$data, stringsAsFactors = FALSE)

cv_emit(list(
  n_obs = nrow(d)
), args$out)
"""

_RESULT_FILES = {
    "verification_log": "verification_log.md",
    "comparison_table": "comparison_table.md",
    "methodology_statement": "methodology_statement.md",
    "results_json": "verification_results.json",
}


def _check_dict(result: CheckResult) -> dict:
    """Serialize a :class:`~crossverify.checks.CheckResult` to a plain dict."""
    return {
        "phase": result.phase,
        "name": result.name,
        "description": result.description,
        "status": result.status,
        "detail": result.detail,
    }


def _output_paths(out_dir: Path) -> dict:
    """Map the four written artifacts to their absolute paths under ``out_dir``."""
    paths = {"dir": str(out_dir)}
    for key, name in _RESULT_FILES.items():
        paths[key] = str(out_dir / name)
    return paths


def validate(project_path, *, force_contain: bool = False) -> list[str]:
    """Load a project file and return its validation problems.

    Args:
        project_path: Path to the YAML project file.
        force_contain: When ``True``, enforce path containment even if the project
            file sets ``allow_external_paths: true`` (see :meth:`Project.validate`).

    Returns:
        A list of human-readable problem strings; an empty list means the project
        is valid and ready to :func:`verify`.

    Raises:
        FileNotFoundError: If the project file does not exist.
        ValueError: If the project file omits the required ``data`` key.
    """
    return Project.load(project_path).validate(force_contain=force_contain)


def inspect_dataset(csv_path) -> dict:
    """Summarize a dataset (Phase-1 intake) without running an analysis.

    Loads the CSV and reports shape, columns, and the Phase-1 intake checks and
    artifacts, so a caller can confirm the data matches the raw source before
    pointing an analysis at it.

    Args:
        csv_path: Path to the CSV dataset.

    Returns:
        A dict with ``path``, ``rows``, ``columns``, ``checks`` (serialized
        Phase-1 ``CheckResult`` records), and ``artifacts`` (the ``head`` /
        ``describe`` / ``categorical`` text blocks).
    """
    path = Path(csv_path)
    df = load_data(path)
    results, artifacts = intake.inspect(df)
    return {
        "path": str(path),
        "rows": int(df.shape[0]),
        "columns": list(df.columns),
        "checks": [_check_dict(r) for r in results],
        "artifacts": artifacts,
    }


def scaffold(target_dir) -> dict:
    """Scaffold a new project directory with starter config and analysis stubs.

    Writes ``project.yaml``, ``analysis.py``, and ``analysis.R`` into ``target_dir``
    (created if needed). Existing files are left untouched, so re-running is
    non-destructive.

    Args:
        target_dir: Directory to scaffold into.

    Returns:
        A dict with ``target`` (the directory), ``written`` (paths created), and
        ``skipped`` (paths left in place because they already existed).
    """
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    files = {
        "project.yaml": _INIT_PROJECT,
        "analysis.py": _INIT_PY,
        "analysis.R": _INIT_R,
    }
    written, skipped = [], []
    for name, content in files.items():
        path = target / name
        if path.exists():
            skipped.append(str(path))
            continue
        path.write_text(content)
        written.append(str(path))
    return {"target": str(target), "written": written, "skipped": skipped}


def verify(
    project_path,
    *,
    phases=None,
    skip_r: bool = False,
    seed=None,
    out=None,
    force_contain: bool = False,
) -> dict:
    """Run the six-phase verification pipeline and return structured results.

    Loads and validates the project, then runs the requested phases (1 intake,
    2 transforms, 3 consistency, 4 reproducibility, 5 cross-tool triangulation),
    and compiles the report artifacts. If the analysis adapter declares a
    ``prepare()`` step, it is the single source of truth for the analyzed frame
    (Phase-2 snapshot, Phase-3 ranges, and the frame handed to ``run()`` all derive
    from it) and is called at most once, only when a phase actually needs it.

    A failed check is a normal outcome (``verdict == "fail"``), not an exception;
    only a structurally broken project raises. A project that fails validation
    returns ``verdict == "invalid"`` with a ``problems`` list rather than running
    any user code.

    Args:
        project_path: Path to the YAML project file.
        phases: Iterable of phase numbers to run; ``None`` runs all of
            :data:`ALL_PHASES`.
        skip_r: If ``True``, skip Phase 5 cross-tool triangulation.
        seed: Optional override for the project's random seed.
        out: Output directory for the artifacts; defaults to
            ``crossverify_out/<project-stem>/``.
        force_contain: When ``True``, enforce path containment even if the project
            file sets ``allow_external_paths: true``. The MCP server passes this so a
            project's own opt-out cannot disable containment for executed code.

    Returns:
        A dict carrying the overall ``verdict`` (``"pass"`` / ``"fail"`` /
        ``"invalid"``) and :data:`SCOPE_CAVEAT`. For a run that executed, it also
        includes ``totals``, per-check ``checks``, the Python-vs-R ``comparison``
        rows, environment fields, and ``output_paths``. For an invalid project it
        includes ``problems`` instead.

    Raises:
        FileNotFoundError: If the project file does not exist.
        ValueError: If the project file omits the required ``data`` key.
    """
    phase_set = set(ALL_PHASES if phases is None else phases)

    project = Project.load(project_path)
    if seed is not None:
        project.seed = seed

    problems = project.validate(force_contain=force_contain)
    if problems:
        return {"verdict": "invalid", "problems": problems, "scope_caveat": SCOPE_CAVEAT}

    df = load_data(project.data_path)
    adapter = load_adapter(project.python_module)

    all_results: list[CheckResult] = []
    intake_artifacts: dict = {}
    comparison_rows: list = []

    # If the analysis declares prepare(), it is the single source of truth for the
    # analyzed frame; call it at most once, and only when a phase needs it.
    prepare = getattr(adapter, "prepare", None)
    prepared = None
    if callable(prepare) and (phase_set & {2, 3, 4, 5}):
        prepared = call_with_optional_seed(prepare, df.copy(), project.seed)
    analyzed = prepared if prepared is not None else df

    if 1 in phase_set:
        res, intake_artifacts = intake.inspect(df)
        all_results += res

    if 2 in phase_set:
        res, _ = transforms.run_phase(adapter, df, project, prepared=prepared)
        all_results += res

    # Phases 3-5 need the Python analysis result, computed on the analyzed frame so
    # the statistics and the consistency ranges share one space.
    py_results = None
    if phase_set & {3, 4, 5}:
        py_results = run_python(adapter, analyzed, project.seed)

    if 3 in phase_set:
        ranges = intake.numeric_ranges(analyzed)
        data_scales = {
            c: float(analyzed[c].abs().sum()) for c in analyzed.select_dtypes("number").columns
        }
        all_results += consistency.consistency_checks(py_results, project, ranges, data_scales)
        all_results += consistency.group_checks(py_results, project, len(df))
        # Spot-checks recompute against the raw, as-loaded data on purpose: an
        # independent sanity check against the original source, not the prepared frame.
        all_results += consistency.spot_checks(py_results, project, df)

    if 4 in phase_set:
        py_results_2 = run_python(adapter, analyzed, project.seed)
        all_results += reproduce.reproducibility(py_results, py_results_2, project.reproducibility)

    rver = "not run"
    if 5 in phase_set:
        if skip_r:
            detail = "skipped: --skip-r"
        elif not project.r_script:
            detail = "skipped: no r.script declared in the project"
        elif not r_available():
            detail = "skipped: Rscript not found on PATH"
        else:
            detail = None
            # The R helper must be a concrete file on disk for the subprocess;
            # as_file materializes it (extracting from a zip if needed) and the
            # ExitStack keeps it alive for the run_r call.
            with ExitStack() as stack:
                helper_r = stack.enter_context(
                    resources.as_file(resources.files(__package__) / "crossverify.R")
                )
                r_results, _ = run_r(project.r_script, project.data_path, project.seed, helper_r)
            rver = r_version()
            checks, comparison_rows = triangulate.triangulate(
                py_results, r_results, project.tolerance
            )
            all_results += checks
        if detail is not None:
            all_results.append(
                CheckResult("5", "triangulate:skipped", "Cross-tool triangulation", None, detail)
            )

    out_dir = Path(out) if out else Path("crossverify_out") / Path(project_path).stem
    env = report.env_info(rver)
    summary = report.compile_report(
        project, out_dir, all_results, intake_artifacts, comparison_rows, env, TEMPLATE
    )
    out_dir = summary.pop("out_dir")
    verdict = "pass" if summary["totals"]["failed"] == 0 else "fail"
    return {
        "verdict": verdict,
        **summary,
        "output_paths": _output_paths(Path(out_dir)),
        "scope_caveat": SCOPE_CAVEAT,
    }
