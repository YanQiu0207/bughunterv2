"""Configuration loading for bughunterv2."""

import os
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
_DEFAULT_MAX_RETRY = 3
_DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_LLM_MODEL = "gpt-4o"
_DEFAULT_DIAGNOSIS_OUTPUT_LANGUAGE = "zh-CN"
_DEFAULT_DIAGNOSIS_PROMPT_APPEND = ""
_DEFAULT_TARGET_PROJECT_DIR = ""
_DEFAULT_SVN_URL = ""
_DEFAULT_SVN_CACHE_DIR = "workspace/cache/svn-clean"
_DEFAULT_BUILD_COMMAND = ""
_DEFAULT_TEST_COMMAND = ""


@dataclass
class Config:
    """Runtime configuration for a diagnosis run."""

    framework_packages: list[str] = field(
        default_factory=lambda: list(_DEFAULT_FRAMEWORK_PACKAGES)
    )
    max_steps: int = _DEFAULT_MAX_STEPS
    max_retry: int = _DEFAULT_MAX_RETRY
    extra_source_roots: list[str] = field(default_factory=list)
    llm_base_url: str = _DEFAULT_LLM_BASE_URL
    llm_model: str = _DEFAULT_LLM_MODEL
    llm_api_key: str = ""
    diagnosis_output_language: str = _DEFAULT_DIAGNOSIS_OUTPUT_LANGUAGE
    diagnosis_prompt_append: str = _DEFAULT_DIAGNOSIS_PROMPT_APPEND
    target_project_dir: str = _DEFAULT_TARGET_PROJECT_DIR
    svn_url: str = _DEFAULT_SVN_URL
    svn_cache_dir: str = _DEFAULT_SVN_CACHE_DIR
    build_command: str = _DEFAULT_BUILD_COMMAND
    test_command: str = _DEFAULT_TEST_COMMAND

    def __post_init__(self) -> None:
        if self.max_steps <= 0:
            raise ValueError(
                f"max_steps must be a positive integer, got {self.max_steps}"
            )
        if self.max_retry < 0:
            raise ValueError(
                f"max_retry must be a non-negative integer, got {self.max_retry}"
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

    framework_packages = raw.get(
        "framework_packages", list(_DEFAULT_FRAMEWORK_PACKAGES)
    )
    if not isinstance(framework_packages, list):
        raise ValueError(
            f"'framework_packages' in {path!r} must be a list, "
            f"got {type(framework_packages).__name__}"
        )

    llm_api_key = raw.get("llm_api_key") or os.environ.get("LLM_API_KEY", "")

    return Config(
        framework_packages=framework_packages,
        max_steps=int(raw.get("max_steps", _DEFAULT_MAX_STEPS)),
        max_retry=int(raw.get("max_retry", _DEFAULT_MAX_RETRY)),
        extra_source_roots=list(raw.get("extra_source_roots", [])),
        llm_base_url=str(raw.get("llm_base_url", _DEFAULT_LLM_BASE_URL)),
        llm_model=str(raw.get("llm_model", _DEFAULT_LLM_MODEL)),
        llm_api_key=llm_api_key,
        diagnosis_output_language=str(
            raw.get(
                "diagnosis_output_language",
                _DEFAULT_DIAGNOSIS_OUTPUT_LANGUAGE,
            )
        ),
        diagnosis_prompt_append=str(
            raw.get(
                "diagnosis_prompt_append",
                _DEFAULT_DIAGNOSIS_PROMPT_APPEND,
            )
        ),
        target_project_dir=str(
            raw.get("target_project_dir", _DEFAULT_TARGET_PROJECT_DIR)
        ),
        svn_url=str(raw.get("svn_url", _DEFAULT_SVN_URL)),
        svn_cache_dir=str(raw.get("svn_cache_dir", _DEFAULT_SVN_CACHE_DIR)),
        build_command=str(raw.get("build_command", _DEFAULT_BUILD_COMMAND)),
        test_command=str(raw.get("test_command", _DEFAULT_TEST_COMMAND)),
    )
