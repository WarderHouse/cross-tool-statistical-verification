"""Load and validate a verification project file (YAML)."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


def _within_base(path, base) -> bool:
    """True if ``path`` resolves to a location inside ``base``.

    Used to keep a project file from pointing its data/scripts at arbitrary
    locations on disk (absolute paths or ``..`` traversal).
    """
    try:
        Path(path).resolve().relative_to(Path(base).resolve())
        return True
    except ValueError:
        return False


@dataclass
class Project:
    analysis_name: str
    data_path: Path
    base_dir: Path
    seed: Optional[int] = None
    python_module: Optional[Path] = None
    r_script: Optional[Path] = None
    checks: dict = field(default_factory=dict)
    group_checks: list = field(default_factory=list)
    spot_checks: list = field(default_factory=list)
    transform_checks: list = field(default_factory=list)
    tolerance: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    reproducibility: dict = field(default_factory=dict)
    # When False (default), data/python.module/r.script must resolve inside the
    # project folder; set true in the project file to permit out-of-tree paths.
    allow_external_paths: bool = False

    @classmethod
    def load(cls, path) -> "Project":
        path = Path(path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Project file not found: {path}")
        spec = yaml.safe_load(path.read_text()) or {}
        base = path.parent

        def resolve(rel):
            if not rel:
                return None
            p = Path(rel)
            return p if p.is_absolute() else (base / p)

        if "data" not in spec:
            raise ValueError(f"{path.name}: missing required 'data' key (path to the dataset).")

        py = spec.get("python") or {}
        r = spec.get("r") or {}
        tol = spec.get("tolerance") or {}
        tol.setdefault("default_atol", 1e-8)
        tol.setdefault("default_rtol", 1e-6)

        return cls(
            analysis_name=spec.get("analysis_name", path.stem),
            data_path=resolve(spec["data"]),
            base_dir=base,
            seed=spec.get("seed"),
            python_module=resolve(py.get("module")),
            r_script=resolve(r.get("script")),
            checks=spec.get("checks") or {},
            group_checks=spec.get("group_checks") or [],
            spot_checks=spec.get("spot_checks") or [],
            transform_checks=spec.get("transform_checks") or [],
            tolerance=tol,
            metadata=spec.get("metadata") or {},
            reproducibility=spec.get("reproducibility") or {},
            allow_external_paths=bool(spec.get("allow_external_paths", False)),
        )

    def validate(self) -> list:
        """Return a list of human-readable problems (empty list == OK)."""
        problems = []
        if not self.data_path or not self.data_path.exists():
            problems.append(f"data file not found: {self.data_path}")
        if not self.python_module:
            problems.append("no python.module declared (the analysis to verify)")
        elif not self.python_module.exists():
            problems.append(f"python module not found: {self.python_module}")
        if self.r_script and not self.r_script.exists():
            problems.append(f"r script declared but not found: {self.r_script}")
        if not self.allow_external_paths:
            for label, p in (("data", self.data_path),
                             ("python.module", self.python_module),
                             ("r.script", self.r_script)):
                if p and not _within_base(p, self.base_dir):
                    problems.append(
                        f"{label} resolves outside the project folder: "
                        f"{Path(p).resolve()} (set 'allow_external_paths: true' in "
                        f"the project file to permit this)")
        return problems
