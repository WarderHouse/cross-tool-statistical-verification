"""Phase 2 — transformation sanity checks.

The harness cannot know what cleaning your analysis performs, so this phase is
opt-in. If your Python adapter exposes a ``prepare(df, seed=None) -> DataFrame``
function, the harness runs it, records a before/after shape snapshot, and applies
any ``transform_checks`` declared in the project file. If there is no prepare()
step, the phase records that the analysis consumes the raw data as loaded.
"""

from .checks import CheckResult, fmt
from .runner import call_with_optional_seed


def run_phase(adapter, df, project, prepared=None):
    """Run Phase 2 transformation sanity checks and return the prepared frame.

    If the adapter exposes a callable ``prepare``, records a before/after shape snapshot
    and evaluates each declared ``transform_check``; otherwise records that the analysis
    consumes the raw dataset as loaded. ``prepared`` may be supplied by the caller
    (``cli.main`` computes it once and reuses it here) to avoid invoking ``prepare()`` a
    second time; if it is ``None`` and the adapter declares ``prepare()``, this function
    calls it.

    Args:
        adapter: Analysis adapter module, optionally exposing ``prepare(df, seed=None)``.
        df: The raw input ``DataFrame`` as loaded.
        project: The :class:`~crossverify.config.Project` supplying ``seed`` and
            ``transform_checks``.
        prepared: Optionally, the already-computed prepared ``DataFrame`` to reuse.

    Returns:
        A ``(results, frame)`` tuple where ``results`` is a list of
        :class:`~crossverify.checks.CheckResult` and ``frame`` is the prepared
        ``DataFrame`` (or the original ``df`` when no ``prepare()`` step exists).
    """
    results = []
    prepare = getattr(adapter, "prepare", None)

    if not callable(prepare):
        results.append(
            CheckResult(
                "2",
                "transform:none",
                "Transformation step",
                None,
                "No prepare() declared; the analysis consumes the raw dataset as loaded.",
            )
        )
        return results, df

    if prepared is None:
        prepared = call_with_optional_seed(prepare, df.copy(), project.seed)
    results.append(
        CheckResult(
            "2",
            "transform:shape",
            "Shape after prepare()",
            None,
            f"{df.shape[0]}x{df.shape[1]} -> {prepared.shape[0]}x{prepared.shape[1]}",
        )
    )

    for spec in project.transform_checks:
        results.append(_evaluate(spec, prepared))
    return results, prepared


def _evaluate(spec, df):
    """Evaluate a single transform-check ``spec`` against ``df``.

    Dispatches on ``spec["kind"]`` (``range``, ``no_duplicate_rows``, ``row_count``);
    unknown kinds yield an INFO skip and a malformed spec yields a FAIL rather than
    silently passing.

    Args:
        spec: A single transform-check specification mapping (must contain ``kind``).
        df: The prepared ``DataFrame`` to evaluate the check against.

    Returns:
        A :class:`~crossverify.checks.CheckResult` capturing the check outcome.
    """
    kind = spec.get("kind", "")
    try:
        if kind == "range":
            col = spec["column"]
            lo, hi = spec.get("min"), spec.get("max")
            s = df[col]
            below = int((s < lo).sum()) if lo is not None else 0
            above = int((s > hi).sum()) if hi is not None else 0
            ok = below == 0 and above == 0
            return CheckResult(
                "2",
                f"transform:range:{col}",
                f"{col} within [{lo}, {hi}]",
                ok,
                f"observed [{fmt(s.min())}, {fmt(s.max())}]; {below} below, {above} above",
            )
        if kind == "no_duplicate_rows":
            dups = int(df.duplicated().sum())
            return CheckResult(
                "2",
                "transform:no_dup",
                "No duplicate rows after prepare()",
                dups == 0,
                f"{dups} duplicate rows",
            )
        if kind == "row_count":
            n = len(df)
            if "equals" in spec:
                ok = n == spec["equals"]
                return CheckResult(
                    "2", "transform:rows", f"Row count == {spec['equals']}", ok, f"observed {n}"
                )
            if "at_least" in spec:
                ok = n >= spec["at_least"]
                return CheckResult(
                    "2", "transform:rows", f"Row count >= {spec['at_least']}", ok, f"observed {n}"
                )
        return CheckResult(
            "2",
            f"transform:{kind or 'unknown'}",
            f"Unsupported transform check '{kind}'",
            None,
            "skipped (unknown kind)",
        )
    except Exception as e:  # a malformed spec should fail loudly, not silently pass
        return CheckResult(
            "2", f"transform:{kind or 'error'}", f"Transform check '{kind}'", False, f"error: {e}"
        )
