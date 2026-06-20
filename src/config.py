"""Configuration loading for bughunterv2."""

from dataclasses import dataclass, field
from typing import Any

import yaml


_DEFAULT_FRAMEWORK_PACKAGES = [
    "java.",
    "javax.",
    "sun.",
    "com.sun.",
    "org.springframework.",
    "org.apache.",
    "org.slf4j.",
]
_DEFAULT_MAX_STEPS = 10


@dataclass
class Config:
    """Runtime configuration for a diagnosis run."""

    framework_packages: list[str] = field(
        default_factory=lambda: list(_DEFAULT_FRAMEWORK_PACKAGES)
    )
    max_steps: int = _DEFAULT_MAX_STEPS
    extra_source_roots: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.max_steps <= 0:
            raise ValueError(
                f"max_steps must be a positive integer, got {self.max_steps}"
            )


def load_config(path: str) -> Config:
    """Load config from a YAML file, falling back to defaults for missing fields.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        Config populated from the file merged with defaults.

    Raises:
        ValueError: If the YAML structure is invalid.
    """
    with open(path, encoding="utf-8") as f:
        raw: Any = yaml.safe_load(f)

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"Config file {path!r} must be a YAML mapping, got {type(raw).__name__}"
        )

    framework_packages = raw.get("framework_packages", list(_DEFAULT_FRAMEWORK_PACKAGES))
    if not isinstance(framework_packages, list):
        raise ValueError(
            f"'framework_packages' in {path!r} must be a list, "
            f"got {type(framework_packages).__name__}"
        )

    return Config(
        framework_packages=framework_packages,
        max_steps=int(raw.get("max_steps", _DEFAULT_MAX_STEPS)),
        extra_source_roots=list(raw.get("extra_source_roots", [])),
    )
