"""Command-line entrypoint for the ``crossverify`` verification harness.

A thin wrapper over :mod:`crossverify.api`: it parses arguments, calls the API,
and renders the result as a one-screen summary plus an exit code. All the
orchestration lives in the API so the CLI and the MCP server behave identically.

Examples:
    ```
    python -m crossverify --project examples/project.yaml
    python -m crossverify --project examples/project.yaml --skip-r
    python -m crossverify --project examples/project.yaml --phases 1,3,5
    python -m crossverify --init my_study/
    ```
"""

import argparse
import sys
from pathlib import Path

from . import __version__, api


def main(argv=None):
    """Parse arguments, run the verification via the API, and print a summary.

    Either scaffolds a new project (``--init``) or runs the selected phases on the
    named project and prints a one-screen per-phase summary. The verification
    itself is delegated to :func:`crossverify.api.verify`.

    Args:
        argv: Argument vector to parse; when ``None``, ``argparse`` reads ``sys.argv``.

    Returns:
        Process exit code: ``0`` on success, ``1`` if any check failed, ``2`` if the
        project failed validation. The ``--init`` path returns ``0``.

    Raises:
        SystemExit: Raised by ``argparse`` for ``--version``, ``--help``, or a usage
            error such as a missing ``--project``.
        FileNotFoundError: If the project file does not exist (via the API).
        ValueError: If the project file is missing the required ``data`` key (via the API).
    """
    ap = argparse.ArgumentParser(
        prog="crossverify",
        description="Six-phase verification harness for statistical analysis, "
        "with Python-vs-R cross-tool triangulation.",
    )
    ap.add_argument("--project", help="Path to the project YAML file.")
    ap.add_argument(
        "--out", default=None, help="Output directory (default: crossverify_out/<project>)."
    )
    ap.add_argument(
        "--phases",
        default="1,2,3,4,5,6",
        help="Comma-separated phases to run (default: all). E.g. 1,3,5",
    )
    ap.add_argument("--skip-r", action="store_true", help="Skip Phase 5 cross-tool triangulation.")
    ap.add_argument("--seed", type=int, default=None, help="Override the project's random seed.")
    ap.add_argument("--init", metavar="DIR", help="Scaffold a new project in DIR and exit.")
    ap.add_argument("--version", action="version", version=f"crossverify {__version__}")
    args = ap.parse_args(argv)

    if args.init:
        _print_scaffold(api.scaffold(args.init))
        return 0
    if not args.project:
        ap.error("--project is required (or use --init DIR)")

    phases = {int(x) for x in args.phases.split(",") if x.strip()}
    result = api.verify(
        args.project, phases=phases, skip_r=args.skip_r, seed=args.seed, out=args.out
    )

    if result["verdict"] == "invalid":
        print("Project has problems:", file=sys.stderr)
        for p in result["problems"]:
            print(f"  - {p}", file=sys.stderr)
        return 2

    _print_summary(result)
    return 0 if result["verdict"] == "pass" else 1


def _print_summary(result):
    """Print a one-screen, per-phase pass/fail/info summary and the output location.

    Args:
        result: A :func:`crossverify.api.verify` result dict (``analysis_name``,
            ``checks``, ``comparison``, ``totals``, ``verdict``, ``output_paths``).

    Returns:
        None. Output is written to stdout.
    """
    titles = {
        "1": "intake",
        "2": "transforms",
        "3": "consistency",
        "4": "reproducibility",
        "5": "triangulation",
    }
    print(f"\ncrossverify {__version__} — {result['analysis_name']}")
    for p in ("1", "2", "3", "4", "5"):
        rows = [c for c in result["checks"] if c["phase"] == p]
        if not rows:
            continue
        pa = sum(1 for c in rows if c["status"] == "PASS")
        fa = sum(1 for c in rows if c["status"] == "FAIL")
        inf = sum(1 for c in rows if c["status"] == "INFO")
        bits = []
        if pa:
            bits.append(f"{pa} pass")
        if fa:
            bits.append(f"{fa} FAIL")
        if inf:
            bits.append(f"{inf} info")
        print(f"  Phase {p} {titles[p]:<16} {', '.join(bits)}")
    comparison = result["comparison"]
    if comparison:
        matched = sum(1 for r in comparison if r["match"])
        print(f"  Cross-tool: {matched}/{len(comparison)} statistics matched within tolerance.")
    totals = result["totals"]
    verdict = "PASS" if result["verdict"] == "pass" else "FAIL"
    print(
        f"\nResult: {verdict} ({totals['passed']} passed, {totals['failed']} failed, "
        f"{totals['info']} informational)"
    )
    print(
        f"Wrote: {result['output_paths']['dir']}/  "
        f"(verification_log.md, comparison_table.md, methodology_statement.md, "
        f"verification_results.json)"
    )


def _print_scaffold(result):
    """Print the result of scaffolding a new project (``--init``).

    Args:
        result: A :func:`crossverify.api.scaffold` result dict (``target``,
            ``written``, ``skipped``).

    Returns:
        None. Output is written to stdout.
    """
    for p in result["skipped"]:
        print(f"  skip (exists): {p}")
    print(f"Scaffolded a project in {result['target']}/")
    for w in result["written"]:
        print(f"  wrote {w}")
    print("\nNext: point 'data:' at your dataset, fill in the analysis, then run:")
    print(f"  python -m crossverify --project {Path(result['target']) / 'project.yaml'}")
