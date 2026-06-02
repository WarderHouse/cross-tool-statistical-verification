"""Execute the Python adapter and the R replication, collecting key statistics."""

import importlib.util
import inspect
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pandas as pd


def load_data(path):
    return pd.read_csv(path)


def load_adapter(module_path):
    """Import a Python analysis module from a file path.

    The module must define ``run(df, seed=None) -> dict`` and may define
    ``prepare(df, seed=None) -> DataFrame``. When ``prepare`` is declared, cli
    runs it once and hands its output to ``run`` (and to the Phase-3 consistency
    ranges), so the statistics and the checks share one data space; without it,
    ``run`` receives the raw data as loaded.
    """
    module_path = Path(module_path)
    spec = importlib.util.spec_from_file_location(
        f"crossverify_adapter_{module_path.stem}", str(module_path)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def call_with_optional_seed(fn, df, seed):
    """Call fn(df, seed=seed) if it accepts a seed parameter, else fn(df)."""
    if "seed" in inspect.signature(fn).parameters:
        return fn(df, seed=seed)
    return fn(df)


def _to_num(v):
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    return float(v)


def _coerce(mapping):
    coerced = {}
    for k, v in mapping.items():
        try:
            coerced[str(k)] = _to_num(v)
        except (TypeError, ValueError):
            raise ValueError(
                f"statistic '{k}' is not numeric (got {v!r}); "
                "the harness verifies numbers, so emit scalars only."
            ) from None
    return coerced


def run_python(adapter, df, seed):
    if not hasattr(adapter, "run"):
        raise AttributeError("the Python adapter must define run(df, seed=None) -> dict")
    result = call_with_optional_seed(adapter.run, df.copy(), seed)
    if not isinstance(result, dict):
        raise TypeError("run() must return a dict of {statistic_name: number}")
    return _coerce(result)


# Variables the R child legitimately needs; everything else in the parent
# environment (tokens, cloud credentials, etc.) is withheld from the
# user-supplied R script. R_* / LC_* families are matched by prefix below.
_R_ENV_ALLOW = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TZ",
    "TMPDIR",
    "LD_LIBRARY_PATH",
    "DYLD_LIBRARY_PATH",
)


def _r_child_env(helper_path):
    """Build a minimal environment for the Rscript child.

    Copies only an allowlist from the parent environment so secrets the parent
    holds are not exposed to the user-supplied R script, then points
    CROSSVERIFY_R at the helper library.
    """
    env = {k: v for k, v in os.environ.items() if k in _R_ENV_ALLOW or k.startswith(("R_", "LC_"))}
    env["CROSSVERIFY_R"] = str(helper_path)
    return env


def r_available():
    return shutil.which("Rscript") is not None


def r_version():
    try:
        out = subprocess.run(["Rscript", "--version"], capture_output=True, text=True)
        text = (out.stdout or out.stderr).strip()
        return text.splitlines()[0] if text else "unknown"
    except Exception:
        return "unknown"


def run_r(r_script, data_path, seed, helper_path):
    """Run the R replication and return (results dict, stdout).

    The harness passes three positional arguments to the R script — data path,
    output path, seed — and sets CROSSVERIFY_R to the helper library so the
    script can ``source(Sys.getenv("CROSSVERIFY_R"))``.
    """
    fd, out_path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        env = _r_child_env(helper_path)
        cmd = [
            "Rscript",
            str(r_script),
            str(data_path),
            out_path,
            "" if seed is None else str(seed),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            raise RuntimeError(
                f"R script exited {proc.returncode}.\n--- R stdout ---\n{proc.stdout}\n"
                f"--- R stderr ---\n{proc.stderr}"
            )
        raw = json.loads(Path(out_path).read_text())
        return _coerce(raw), proc.stdout
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass
