"""Phase 5 — cross-tool triangulation.

Compare the Python results against an independent R implementation, statistic by
statistic, within tolerance. This is the step that catches results which are
artifacts of one tool's defaults rather than properties of the data. Set
``abs: true`` in a statistic's tolerance to compare magnitudes only, for
quantities whose sign is implementation-defined (e.g. PCA loadings).

A mismatch fails the build by default. For a statistic that legitimately differs
across tools for a defensible reason (robust-SE variant, ddof/denominator choice,
contrast coding), declare ``severity: info`` in its per-key tolerance so the
divergence is reported as INFO rather than FAIL — the run stays green and the
disagreement is surfaced for a human to interpret, instead of pressuring the
analyst to force one tool to mimic the other. A statistic that is simply absent
in one tool is always a hard failure (the replication is incomplete), regardless
of severity.
"""

from .checks import CheckResult, is_close, tol_for, severity_for, fmt


def triangulate(py_results, r_results, tolerance):
    """Return (list of CheckResult, list of comparison rows for the table)."""
    checks = []
    rows = []
    for k in sorted(set(py_results) | set(r_results)):
        a, b = py_results.get(k), r_results.get(k)
        atol, rtol, use_abs = tol_for(tolerance, k)

        if k not in py_results or k not in r_results:
            note = "missing in Python" if k not in py_results else "missing in R"
            checks.append(CheckResult("5", f"triangulate:{k}", f"Python vs R: {k}", False, note))
            rows.append({"stat": k, "python": a, "r": b, "delta": None, "match": False, "note": note})
            continue

        ok = is_close(a, b, atol, rtol, use_abs)
        delta = abs(abs(a) - abs(b)) if use_abs else abs(a - b)
        advisory = severity_for(tolerance, k) == "info"
        # On a mismatch, an advisory statistic reports INFO (passed=None) instead
        # of FAIL, so a defensible cross-tool divergence does not break the build.
        passed = True if ok else (None if advisory else False)
        notes = []
        if use_abs:
            notes.append("magnitude only")
        if advisory and not ok:
            notes.append("advisory: severity=info, not a failure")
        note = "; ".join(notes)
        detail = (f"python = {fmt(a)}, r = {fmt(b)}, |delta| = {fmt(delta)} "
                  f"(atol={atol:g}, rtol={rtol:g}{', abs' if use_abs else ''}"
                  f"{', advisory' if advisory else ''})")
        checks.append(CheckResult("5", f"triangulate:{k}", f"Python vs R: {k}", passed, detail))
        rows.append({"stat": k, "python": a, "r": b, "delta": delta, "match": ok, "note": note})
    return checks, rows
