"""MCP server exposing crossverify as a toolchain for an autonomous agent.

An agent can scaffold a project, write the Python + R analysis, call
``verify_analysis``, read the structured pass/fail/info result, revise, and
re-verify — without parsing console text or shelling out to the CLI itself.

Trust boundary — READ THIS
==========================
``verify_analysis`` **executes the analysis code the project points at** (it
imports the Python module and ``Rscript``-runs the R script). An agent that can
choose ``project_path`` can therefore cause arbitrary code execution. Two
guardrails are enforced here, but they are not a sandbox:

1. **Path containment (default).** A project's ``data`` / ``python.module`` /
   ``r.script`` must resolve *inside* the project folder; a project that escapes
   it (absolute path or ``..``) comes back ``verdict="invalid"`` with the
   offending path, and no analysis code runs. (Set ``allow_external_paths: true``
   in the project file to opt out — only do that for projects you trust.)
2. **Bounded subprocess.** Each ``verify_analysis`` runs in a child process with
   a **timeout** (``CROSSVERIFY_MCP_TIMEOUT`` seconds, default 300) and a
   **minimal environment** (an allowlist — the parent's tokens/secrets are not
   passed), so a runaway or hostile analysis is time-bounded and cannot harvest
   the server's environment.

Still: **run this server in a sandbox** (container/VM, no credentials in env,
least-privilege filesystem). The read-only tools (``validate_project``,
``scaffold_project``, ``inspect_dataset``) do not execute analysis code.

Run it::

    pip install "crossverify[mcp]"
    crossverify-mcp            # stdio transport
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from . import api

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        "The crossverify MCP server requires the 'mcp' extra. "
        "Install it with:  pip install 'crossverify[mcp]'"
    ) from exc

mcp = FastMCP("crossverify")

# Only these environment variables are passed to the verification subprocess, so
# a hostile analysis cannot read the server's tokens/credentials. The interpreter
# still finds its installed packages via sys.path, which does not need the env.
_ENV_ALLOW = (
    "PATH",
    "HOME",
    "TMPDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "SYSTEMROOT",
    "USERPROFILE",
)


def _timeout() -> float:
    """Per-verification wall-clock budget in seconds (``CROSSVERIFY_MCP_TIMEOUT``)."""
    try:
        return float(os.environ.get("CROSSVERIFY_MCP_TIMEOUT", "300"))
    except ValueError:
        return 300.0


def _minimal_env() -> dict:
    """Build the allowlisted environment handed to the verification subprocess."""
    env = {k: os.environ[k] for k in _ENV_ALLOW if k in os.environ}
    env.setdefault("PATH", os.defpath)
    return env


@mcp.tool()
def verify_analysis(
    project_path: str,
    phases: list[int] | None = None,
    skip_r: bool = False,
    seed: int | None = None,
) -> dict:
    """Run the six-phase verification on a project and return structured results.

    Executes the project's analysis **in a bounded subprocess** (timeout + minimal
    environment) and returns the full machine-readable result. A failed check is a
    normal outcome (``verdict="fail"``), not an error. A project that fails
    validation — including one whose paths escape the project folder — returns
    ``verdict="invalid"`` with a ``problems`` list and runs no analysis code.

    The result carries a ``scope_caveat``: agreement across Python and R is strong
    evidence a number is not a tool-specific artifact, but it is **not** proof the
    analysis is correct (a shared specification error agrees perfectly). Do not
    report a verified result as "correct".

    Args:
        project_path: Path to the project YAML file.
        phases: Phase numbers to run (1-6); omit to run all.
        skip_r: Skip Phase 5 cross-tool triangulation (Python-only).
        seed: Override the project's random seed.

    Returns:
        The verification result dict (``verdict``, ``totals``, per-check ``checks``,
        the Python-vs-R ``comparison`` deltas, ``output_paths``, ``scope_caveat``),
        or ``{"verdict": "error", "error": ...}`` if the subprocess timed out or
        produced no parseable output.
    """
    proj = Path(project_path).expanduser().resolve()
    if not proj.exists():
        return {"verdict": "error", "error": f"project file not found: {proj}"}

    out_dir = proj.parent / "crossverify_out" / proj.stem
    cmd = [
        sys.executable,
        "-m",
        "crossverify",
        "--project",
        str(proj),
        "--json",
        "--out",
        str(out_dir),
    ]
    if skip_r:
        cmd.append("--skip-r")
    if phases:
        cmd += ["--phases", ",".join(str(p) for p in phases)]
    if seed is not None:
        cmd += ["--seed", str(seed)]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_timeout(),
            env=_minimal_env(),
            cwd=str(proj.parent),
        )
    except subprocess.TimeoutExpired:
        return {
            "verdict": "error",
            "error": f"verification exceeded the {_timeout():g}s timeout and was terminated",
        }

    out = proc.stdout.strip()
    if not out:
        return {
            "verdict": "error",
            "error": "the verification subprocess produced no output",
            "stderr": proc.stderr[-2000:],
        }
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {
            "verdict": "error",
            "error": "could not parse the verification output as JSON",
            "stdout": out[-2000:],
            "stderr": proc.stderr[-2000:],
        }


@mcp.tool()
def validate_project(project_path: str) -> dict:
    """Check a project file and return any problems, without running an analysis.

    Use this to fix a project's configuration before calling ``verify_analysis``.

    Args:
        project_path: Path to the project YAML file.

    Returns:
        ``{"ok": bool, "problems": [...]}``; ``ok`` is ``True`` when the problems
        list is empty. ``{"ok": false, "error": ...}`` if the file is missing or
        malformed (no ``data`` key).
    """
    try:
        problems = api.validate(project_path)
    except (FileNotFoundError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": not problems, "problems": problems}


@mcp.tool()
def scaffold_project(target_dir: str) -> dict:
    """Scaffold a new project (project.yaml + analysis.py + analysis.R) to fill in.

    Existing files are left untouched, so this is safe to re-run.

    Args:
        target_dir: Directory to scaffold into (created if needed).

    Returns:
        ``{"target": str, "written": [...], "skipped": [...]}``.
    """
    return api.scaffold(target_dir)


@mcp.tool()
def inspect_dataset(csv_path: str) -> dict:
    """Summarize a dataset (Phase-1 intake) without running an analysis.

    Args:
        csv_path: Path to the CSV dataset.

    Returns:
        ``{"path", "rows", "columns", "checks", "artifacts"}``, or
        ``{"error": ...}`` if the file is missing.
    """
    try:
        return api.inspect_dataset(csv_path)
    except FileNotFoundError as exc:
        return {"error": str(exc)}


def main() -> None:
    """Console entry point: run the MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
