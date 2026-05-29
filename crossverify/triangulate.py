"""Phase 5 — cross-tool triangulation.

Compare the Python results against an independent R implementation, statistic by
statistic, within tolerance. This is the step that catches results which are
artifacts of one tool's defaults rather than properties of the data. Set
``abs: true`` in a statistic's tolerance to compare magnitudes only, for
quantities whose sign is implementation-defined (e.g. PCA loadings).
"""

from .checks import CheckResult, is_close, tol_for, fmt


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
        note = "magnitude only" if use_abs else ""
        checks.append(CheckResult(
            "5", f"triangulate:{k}", f"Python vs R: {k}", ok,
            f"python = {fmt(a)}, r = {fmt(b)}, |delta| = {fmt(delta)} "
            f"(atol={atol:g}, rtol={rtol:g}{', abs' if use_abs else ''})"))
        rows.append({"stat": k, "python": a, "r": b, "delta": delta, "match": ok, "note": note})
    return checks, rows
