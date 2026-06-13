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

1. **Path containment (enforced by the server).** A project's ``data`` /
   ``python.module`` / ``r.script`` must resolve *inside* the project folder; a
   project that escapes it (absolute path or ``..``) comes back
   ``verdict="invalid"`` with the offending path, and no analysis code runs. The
   server forces this regardless of the project file, so an agent that authors the
   project cannot disable containment by setting ``allow_external_paths: true``.
   The opt-out lives with the operator, not the project: set
   ``CROSSVERIFY_MCP_ALLOW_EXTERNAL=1`` in the server's environment to honor the
   project flag again, and only for projects you trust.
2. **Bounded subprocess.** Each ``verify_analysis`` runs in its own process group
   with a **timeout** (``CROSSVERIFY_MCP_TIMEOUT`` seconds, default 300) and a
   **minimal environment** (an allowlist — the parent's tokens/secrets are not
   passed). On timeout the whole process group is killed, including the ``Rscript``
   grandchild, so a runaway or hostile analysis is genuinely time-bounded and
   cannot harvest the server's environment.

Still: **run this server in a sandbox** (container/VM, no credentials in env,
least-privilege filesystem). The read-only tools (``validate_project``,
``scaffold_project``, ``inspect_dataset``) do not execute analysis code.

Run it::

    pip install "crossverify[mcp]"
    crossverify-mcp            # stdio transport
"""

import json
import os
import signal
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


def _force_contain() -> bool:
    """Whether the server overrides the project's ``allow_external_paths`` and contains.

    The opt-out flag lives in the (untrusted) project file an agent can author, so
    by default the server ignores it and enforces path containment. An operator who
    deliberately runs trusted projects can restore the flag's effect by setting
    ``CROSSVERIFY_MCP_ALLOW_EXTERNAL=1`` (also ``true``/``yes``) on the server.
    """
    return os.environ.get("CROSSVERIFY_MCP_ALLOW_EXTERNAL", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    )


def _kill_process_tree(proc: subprocess.Popen) -> None:
    """Kill a child and its whole process group/tree, best effort.

    The verification child spawns an ``Rscript`` grandchild (Phase 5); killing only
    the direct child would orphan it. The child is started in its own session
    (POSIX) or process group (Windows) so the group can be signalled as a unit.
    """
    if os.name == "posix":
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError):
            pass
    proc.kill()


def _run_bounded(cmd: list[str], env: dict, cwd: str, timeout: float):
    """Run ``cmd`` with a wall-clock timeout, killing the whole tree on expiry.

    ``subprocess.run(timeout=...)`` signals only the direct child, so the Rscript
    grandchild would survive the timeout and keep consuming resources. Starting the
    child in a new process group lets the timeout path kill the group, making the
    advertised time bound real.

    Returns:
        ``(stdout, stderr, returncode)``.

    Raises:
        subprocess.TimeoutExpired: After killing the process tree, if the timeout
            elapsed before the child completed.
    """
    popen_kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "env": env,
        "cwd": cwd,
    }
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    elif os.name == "nt":  # pragma: no cover - exercised only on Windows
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    proc = subprocess.Popen(cmd, **popen_kwargs)
    try:
        out, err = proc.communicate(timeout=timeout)
        return out, err, proc.returncode
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        # Reap the killed group so it doesn't linger as a zombie.
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:  # pragma: no cover - kill already sent
            proc.kill()
        raise


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
    if _force_contain():
        cmd.append("--force-contain")
    if skip_r:
        cmd.append("--skip-r")
    if phases:
        cmd += ["--phases", ",".join(str(p) for p in phases)]
    if seed is not None:
        cmd += ["--seed", str(seed)]

    try:
        stdout, stderr, _ = _run_bounded(cmd, _minimal_env(), str(proj.parent), _timeout())
    except subprocess.TimeoutExpired:
        return {
            "verdict": "error",
            "error": f"verification exceeded the {_timeout():g}s timeout and was terminated",
        }

    out = stdout.strip()
    if not out:
        return {
            "verdict": "error",
            "error": "the verification subprocess produced no output",
            "stderr": (stderr or "")[-2000:],
        }
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {
            "verdict": "error",
            "error": "could not parse the verification output as JSON",
            "stdout": out[-2000:],
            "stderr": (stderr or "")[-2000:],
        }


@mcp.tool()
def validate_project(project_path: str) -> dict:
    """Check a project file and return any problems, without running an analysis.

    Use this to fix a project's configuration before calling ``verify_analysis``.

    Args:
        project_path: Path to the project YAML file.

    Path containment is reported the same way ``verify_analysis`` enforces it, so a
    project that validates here will not be rejected for an out-of-tree path later.

    Returns:
        ``{"ok": bool, "problems": [...]}``; ``ok`` is ``True`` when the problems
        list is empty. ``{"ok": false, "error": ...}`` if the file is missing or
        malformed (no ``data`` key).
    """
    try:
        problems = api.validate(project_path, force_contain=_force_contain())
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
