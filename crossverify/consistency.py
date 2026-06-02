"""Phase 3 — internal consistency checks, group checks, and spot-checks.

Internal consistency checks confirm that each reported statistic is the kind of
number it claims to be (an R-squared in [0, 1], a p-value in [0, 1], a
standardized loading in [-1, 1], an OLS-with-intercept residual sum near zero, a
coefficient of an expected sign, and so on). Spot-checks recompute a reported
value directly from the raw data so the analysis cannot quietly disagree with
its source.

Scope notes (see docs/PROTOCOL.md):
  - ``residual_sum`` ~ 0 is a property of OLS *with an intercept*. It does NOT
    hold for regression through the origin, GLM/logistic, WLS/GLS, or penalized
    fits. Declare a ``column`` so the tolerance scales to the response magnitude
    (a fixed absolute tolerance produces false failures on large-scale data).
  - ``loading`` in [-1, 1] holds only for standardized (correlation-scaled)
    loadings; pass ``standardized: false`` for covariance-based/unstandardized
    loadings, which legitimately exceed 1.
  - ``variance_explained`` expects a proportion in [0, 1], not a percentage
    (0-100) or an eigenvalue.
  - an unexpected coefficient sign is reported as INFO by default — it is often
    the substantive finding, not a computation error. Set ``severity: fail`` to
    make a sign mismatch a hard failure.
"""

from .checks import CheckResult, is_close, tol_for, fmt

# kinds whose value must fall inside a fixed interval
_RANGE_KINDS = {
    "r_squared": (0.0, 1.0),
    "p_value": (0.0, 1.0),
    "proportion": (0.0, 1.0),
    "variance_explained": (0.0, 1.0),
    "correlation": (-1.0, 1.0),
}


def consistency_checks(results, project, data_ranges, data_scales=None, near_zero_atol=1e-6):
    out = []
    for name, spec in project.checks.items():
        out.append(_one(name, results.get(name), spec, name in results,
                        data_ranges or {}, data_scales or {}, near_zero_atol))
    return out


def _one(name, value, spec, present, data_ranges, data_scales, near_zero_atol):
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

    if kind == "loading":
        # [-1, 1] is a property of standardized (correlation-scaled) loadings only.
        if spec.get("standardized", True):
            return CheckResult("3", rid, f"{name} (standardized loading) in [-1, 1]",
                               -1.0 <= v <= 1.0, f"value = {fmt(v)}")
        return CheckResult("3", rid, f"{name} (unstandardized loading; not range-bounded)",
                           None, f"value = {fmt(v)}")

    if kind == "count":
        is_int = float(v).is_integer() and v >= 0
        if "equals" in spec:
            ok = is_int and int(v) == spec["equals"]
            return CheckResult("3", rid, f"{name} == {spec['equals']}", ok, f"value = {fmt(v)}")
        return CheckResult("3", rid, f"{name} is a non-negative integer", is_int, f"value = {fmt(v)}")

    if kind == "coefficient":
        return _coefficient(name, rid, v, spec)

    if kind == "residual_sum":
        return _residual_sum(name, rid, v, spec, data_scales, near_zero_atol)

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
        return CheckResult(
            "3", rid,
            f"{name} within observed range of '{col}' [{fmt(lo)}, {fmt(hi)}] (analyzed data)",
            lo <= v <= hi, f"value = {fmt(v)}")

    return CheckResult("3", rid, f"{name} (no consistency rule for kind '{kind}')", None, f"value = {fmt(v)}")


def _coefficient(name, rid, v, spec):
    sign = (spec.get("expected_sign") or "any").lower()
    if sign == "any":
        return CheckResult("3", rid, f"{name} (coefficient, sign not constrained)", None, f"value = {fmt(v)}")
    matches = {"positive": v > 0, "negative": v < 0, "nonzero": v != 0}.get(sign)
    op = {"positive": "> 0", "negative": "< 0", "nonzero": "!= 0"}.get(sign)
    if matches is None:
        return CheckResult("3", rid, f"{name} (unknown expected_sign '{sign}')", None, f"value = {fmt(v)}")
    if matches:
        return CheckResult("3", rid, f"{name} {op} (expected sign)", True, f"value = {fmt(v)}")
    # A coefficient with the opposite sign is frequently the substantive finding,
    # not a computation error, so this is informational by default.
    if (spec.get("severity") or "warn").lower() == "fail":
        return CheckResult("3", rid, f"{name} {op} (expected sign)", False, f"value = {fmt(v)}")
    return CheckResult("3", rid, f"{name} sign differs from expected ({sign})", None,
                       f"value = {fmt(v)} — review whether this is the finding, not an error")


def _residual_sum(name, rid, v, spec, data_scales, near_zero_atol):
    # |Sigma resid| ~ 0 is a theorem for OLS *with an intercept* only. The
    # tolerance scales to the response magnitude (Sigma|y|) when a `column` (or
    # explicit `scale`) is given, so a correct large-scale fit is not failed by
    # ordinary floating-point accumulation.
    col = spec.get("column")
    scale = None
    if col and col in (data_scales or {}):
        scale = data_scales[col]
    elif "scale" in spec:
        scale = abs(float(spec["scale"]))
    atol = spec.get("atol", near_zero_atol)
    rtol = spec.get("rtol", 1e-9 if scale is not None else 0.0)
    tol = atol + rtol * (scale or 0.0)
    scaled = f" (scaled to |{col}|)" if scale is not None and col else ""
    return CheckResult("3", rid,
                       f"{name} ~ 0 (|x| <= {tol:g}{scaled}; OLS-with-intercept property)",
                       abs(v) <= tol, f"value = {fmt(v)}")


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
        ddof = sc.get("ddof", 1)   # pandas/R default; set 0 to match numpy.std
        rid = f"spot:{stat}"
        try:
            sub = df
            cond = ""
            if where:
                sub = df[df[where["column"]] == where["equals"]]
                cond = f" where {where['column']}={where['equals']}"
            if op == "std":
                recomputed = float(sub[col].std(ddof=ddof))
                label = f"std(ddof={ddof}, {col}{cond})"
            elif op in _AGGS:
                recomputed = float(_AGGS[op](sub[col]))
                label = f"{op}({col}{cond})"
            else:
                out.append(CheckResult("3", rid, f"spot-check {stat}", None,
                                       f"unsupported op '{op}'"))
                continue
            reported = results.get(stat)
            atol, rtol, _ = tol_for(project.tolerance, stat)
            ok = reported is not None and is_close(reported, recomputed, atol, rtol)
            out.append(CheckResult("3", rid, f"Independent spot-check of {stat}", ok,
                                   f"recomputed {label} = {fmt(recomputed)}; "
                                   f"analysis reported {fmt(reported)}"))
        except Exception as e:
            out.append(CheckResult("3", rid, f"spot-check {stat}", False, f"error: {e}"))
    return out
