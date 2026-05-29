"""Phase 3 — internal consistency checks, group checks, and spot-checks.

Internal consistency checks confirm that each reported statistic is the kind of
number it claims to be (an R-squared in [0, 1], a p-value in [0, 1], a loading
in [-1, 1], a residual sum near zero, a coefficient of the expected sign, and so
on). Spot-checks recompute a reported value directly from the raw data so the
analysis cannot quietly disagree with the source.
"""

from .checks import CheckResult, is_close, tol_for, fmt

# kinds whose value must fall inside a fixed interval
_RANGE_KINDS = {
    "r_squared": (0.0, 1.0),
    "p_value": (0.0, 1.0),
    "proportion": (0.0, 1.0),
    "variance_explained": (0.0, 1.0),
    "loading": (-1.0, 1.0),
    "correlation": (-1.0, 1.0),
}


def consistency_checks(results, project, data_ranges, near_zero_atol=1e-6):
    out = []
    for name, spec in project.checks.items():
        out.append(_one(name, results.get(name), spec, name in results,
                        data_ranges, near_zero_atol))
    return out


def _one(name, value, spec, present, data_ranges, near_zero_atol):
    kind = (spec or {}).get("kind", "")
    rid = f"consistency:{name}"

    if not present:
        return CheckResult("3", rid, f"{name} emitted by analysis", False,
                           "statistic was declared in checks but not emitted by run()")
    try:
        v = float(value)
    except (TypeError, ValueError):
        return CheckResult("3", rid, f"{name} is numeric", False, f"got {value!r}")

    if kind in _RANGE_KINDS:
        lo, hi = _RANGE_KINDS[kind]
        return CheckResult("3", rid, f"{name} ({kind}) in [{lo}, {hi}]",
                           lo <= v <= hi, f"value = {fmt(v)}")

    if kind == "count":
        is_int = float(v).is_integer() and v >= 0
        if "equals" in spec:
            ok = is_int and int(v) == spec["equals"]
            return CheckResult("3", rid, f"{name} == {spec['equals']}", ok, f"value = {fmt(v)}")
        return CheckResult("3", rid, f"{name} is a non-negative integer", is_int, f"value = {fmt(v)}")

    if kind == "coefficient":
        sign = (spec.get("expected_sign") or "any").lower()
        if sign == "positive":
            return CheckResult("3", rid, f"{name} > 0", v > 0, f"value = {fmt(v)}")
        if sign == "negative":
            return CheckResult("3", rid, f"{name} < 0", v < 0, f"value = {fmt(v)}")
        if sign == "nonzero":
            return CheckResult("3", rid, f"{name} != 0", v != 0, f"value = {fmt(v)}")
        return CheckResult("3", rid, f"{name} (coefficient, sign not constrained)", None, f"value = {fmt(v)}")

    if kind == "residual_sum":
        atol = spec.get("atol", near_zero_atol)
        return CheckResult("3", rid, f"{name} ~ 0 (|x| <= {atol})", abs(v) <= atol, f"value = {fmt(v)}")

    if kind == "converged":
        return CheckResult("3", rid, f"{name} indicates convergence", v == 1.0,
                           "converged" if v == 1.0 else "did NOT converge")

    if kind == "centroid":
        col = spec.get("column")
        rng = (data_ranges or {}).get(col)
        if not rng:
            return CheckResult("3", rid, f"{name} within range of '{col}'", None,
                               f"no numeric range available for column '{col}'")
        lo, hi = rng
        return CheckResult("3", rid, f"{name} within observed range of '{col}' [{fmt(lo)}, {fmt(hi)}]",
                           lo <= v <= hi, f"value = {fmt(v)}")

    return CheckResult("3", rid, f"{name} (no consistency rule for kind '{kind}')", None, f"value = {fmt(v)}")


def group_checks(results, project, n_rows):
    out = []
    for spec in project.group_checks:
        kind = spec.get("kind", "")
        keys = spec.get("keys", [])
        missing = [k for k in keys if k not in results]
        if missing:
            out.append(CheckResult("3", f"group:{kind}", f"group check '{kind}'", False,
                                   f"missing statistics: {', '.join(missing)}"))
            continue
        total = sum(float(results[k]) for k in keys)
        tol = spec.get("tolerance", 1e-6)
        if kind == "sum_to_n":
            n = spec.get("n", n_rows)
            out.append(CheckResult("3", "group:sum_to_n", f"{' + '.join(keys)} == N ({n})",
                                   abs(total - n) <= tol, f"sum = {fmt(total)}"))
        elif kind == "sum_to_one":
            out.append(CheckResult("3", "group:sum_to_one", f"{' + '.join(keys)} == 1",
                                   abs(total - 1.0) <= tol, f"sum = {fmt(total)}"))
        elif kind == "sum_le_one":
            out.append(CheckResult("3", "group:sum_le_one", f"{' + '.join(keys)} <= 1",
                                   total <= 1.0 + tol, f"sum = {fmt(total)}"))
        else:
            out.append(CheckResult("3", f"group:{kind}", f"unsupported group check '{kind}'", None, "skipped"))
    return out


_AGGS = {
    "mean": lambda s: s.mean(),
    "sum": lambda s: s.sum(),
    "count": lambda s: s.count(),
    "median": lambda s: s.median(),
    "std": lambda s: s.std(),
    "min": lambda s: s.min(),
    "max": lambda s: s.max(),
}


def spot_checks(results, project, df):
    out = []
    for sc in project.spot_checks:
        stat = sc.get("stat")
        op = sc.get("op")
        col = sc.get("column")
        where = sc.get("where")
        rid = f"spot:{stat}"
        try:
            sub = df
            label = f"{op}({col})"
            if where:
                sub = df[df[where["column"]] == where["equals"]]
                label = f"{op}({col} where {where['column']}={where['equals']})"
            if op not in _AGGS:
                out.append(CheckResult("3", rid, f"spot-check {stat}", None,
                                       f"unsupported op '{op}'"))
                continue
            recomputed = float(_AGGS[op](sub[col]))
            reported = results.get(stat)
            atol, rtol, _ = tol_for(project.tolerance, stat)
            ok = reported is not None and is_close(reported, recomputed, atol, rtol)
            out.append(CheckResult("3", rid, f"Independent spot-check of {stat}", ok,
                                   f"recomputed {label} = {fmt(recomputed)}; "
                                   f"analysis reported {fmt(reported)}"))
        except Exception as e:
            out.append(CheckResult("3", rid, f"spot-check {stat}", False, f"error: {e}"))
    return out
