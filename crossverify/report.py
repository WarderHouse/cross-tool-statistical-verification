"""Phase 6 — compile the verification log, comparison table, and methodology statement."""

import json
import string
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from . import __version__
from .checks import fmt

PHASE_TITLES = OrderedDict([
    ("1", "Phase 1 — Data Intake and Inspection"),
    ("2", "Phase 2 — Transformation Sanity Checks"),
    ("3", "Phase 3 — Analysis: Internal Consistency and Spot-Checks"),
    ("4", "Phase 4 — Reproducibility"),
    ("5", "Phase 5 — Cross-Tool Triangulation (Python vs R)"),
])


def _counts(results):
    passed = sum(1 for r in results if r.passed is True)
    failed = sum(1 for r in results if r.passed is False)
    info = sum(1 for r in results if r.passed is None)
    return passed, failed, info


def comparison_table_md(rows):
    if not rows:
        return "_No cross-tool comparison was performed._\n"
    lines = ["| Statistic | Python | R | \\|Δ\\| | Match |",
             "|---|---|---|---|---|"]
    for r in rows:
        match = "yes" if r["match"] else "**NO**"
        note = f" ({r['note']})" if r.get("note") else ""
        lines.append(f"| {r['stat']} | {fmt(r['python'])} | {fmt(r['r'])} | "
                     f"{fmt(r['delta'])} | {match}{note} |")
    return "\n".join(lines) + "\n"


def _methodology(project, env, comparison_rows, template_path):
    n_compared = len(comparison_rows)
    n_matched = sum(1 for r in comparison_rows if r["match"])
    tol = project.tolerance
    tol_desc = f"absolute {tol.get('default_atol'):g}, relative {tol.get('default_rtol'):g}"
    libs = ", ".join(project.metadata.get("python_libs", [])) or "the libraries listed in the analysis script"
    seed = "the analysis is deterministic" if project.seed is None \
        else f"under a fixed random seed of {project.seed}"
    fields = {
        "date": env["date"],
        "analysis_name": project.analysis_name,
        "python_version": env["python_version"],
        "r_version": env["r_version"],
        "python_libs": libs,
        "seed": seed,
        "n_compared": n_compared,
        "n_matched": n_matched,
        "tolerance_desc": tol_desc,
        "tool_version": __version__,
    }
    return _render(Path(template_path).read_text(), fields)


def _render(template_text, fields):
    """Fill ``$name`` placeholders from ``fields``.

    Uses ``string.Template.safe_substitute`` so a user-edited template with an
    unknown or malformed placeholder leaves the token intact instead of raising
    or exposing attribute access (unlike ``str.format``).
    """
    return string.Template(template_text).safe_substitute(fields)


def compile_report(project, out_dir, all_results, intake_artifacts, comparison_rows,
                   env, template_path):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    by_phase = OrderedDict((p, []) for p in PHASE_TITLES)
    for r in all_results:
        by_phase.setdefault(r.phase, []).append(r)

    total_passed, total_failed, total_info = _counts(all_results)

    # ---- verification_log.md ----
    L = []
    L.append(f"# Verification Log: {project.analysis_name}\n")
    L.append(f"- Date: {env['date']}")
    L.append(f"- crossverify version: {__version__}")
    L.append(f"- Python: {env['python_version']}")
    L.append(f"- R: {env['r_version']}")
    L.append(f"- Dataset: `{project.data_path.name}`")
    L.append(f"- Random seed: {project.seed if project.seed is not None else 'none (deterministic)'}")
    L.append("")
    L.append(f"**Summary: {total_passed} passed, {total_failed} failed, {total_info} informational.**\n")

    L.append("| Phase | Passed | Failed | Info |")
    L.append("|---|---|---|---|")
    for p, title in PHASE_TITLES.items():
        pa, fa, inf = _counts(by_phase.get(p, []))
        L.append(f"| {title} | {pa} | {fa} | {inf} |")
    L.append("")

    for p, title in PHASE_TITLES.items():
        rows = by_phase.get(p, [])
        if not rows:
            continue
        L.append(f"## {title}\n")
        for r in rows:
            L.append(f"- **{r.status}** — {r.description}" + (f": {r.detail}" if r.detail else ""))
        L.append("")
        if p == "1":
            L.append("### First 10 rows\n```\n" + intake_artifacts.get("head", "") + "\n```\n")
            L.append("### Numeric descriptives\n```\n" + intake_artifacts.get("describe", "") + "\n```\n")
            L.append("### Categorical frequencies\n```\n" + intake_artifacts.get("categorical", "") + "\n```\n")
        if p == "5":
            L.append("### Comparison table\n")
            L.append(comparison_table_md(comparison_rows))

    L.append("## Items requiring human judgment\n")
    L.append("The harness checks that numbers are internally consistent and reproducible "
             "across tools. It cannot judge substance. Before treating these results as "
             "final, the analyst should still confirm:\n")
    L.append("- that coefficient signs and magnitudes are theoretically plausible;")
    L.append("- that the intake summary above matches your raw source file;")
    L.append("- that the chosen model and specification answer the research question.\n")

    (out_dir / "verification_log.md").write_text("\n".join(L))

    # ---- comparison_table.md ----
    (out_dir / "comparison_table.md").write_text(
        f"# Cross-tool comparison: {project.analysis_name}\n\n" + comparison_table_md(comparison_rows))

    # ---- methodology_statement.md ----
    (out_dir / "methodology_statement.md").write_text(
        _methodology(project, env, comparison_rows, template_path))

    # ---- verification_results.json (machine-readable) ----
    summary = {
        "analysis_name": project.analysis_name,
        "date": env["date"],
        "tool_version": __version__,
        "python_version": env["python_version"],
        "r_version": env["r_version"],
        "seed": project.seed,
        "totals": {"passed": total_passed, "failed": total_failed, "info": total_info},
        "checks": [
            {"phase": r.phase, "name": r.name, "description": r.description,
             "status": r.status, "detail": r.detail}
            for r in all_results
        ],
        "comparison": comparison_rows,
    }
    (out_dir / "verification_results.json").write_text(json.dumps(summary, indent=2))

    return {"passed": total_passed, "failed": total_failed, "info": total_info,
            "out_dir": str(out_dir)}


def env_info(r_version_str):
    import platform
    return {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "python_version": platform.python_version(),
        "r_version": r_version_str,
    }
