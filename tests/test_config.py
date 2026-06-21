"""Tests for runtime configuration loading."""

from pathlib import Path

from fix import _resolve_config_relative_path
from src.config import load_config


def test_load_config_uses_default_svn_cache_options(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}", encoding="utf-8")

    config = load_config(str(config_path))

    assert config.svn_url == ""
    assert config.svn_cache_dir == "workspace/cache/svn-clean"


def test_load_config_reads_svn_cache_options(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'svn_url: "https://svn.example.com/project/trunk"',
                'svn_cache_dir: "E:/cache/project-clean"',
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(str(config_path))

    assert config.svn_url == "https://svn.example.com/project/trunk"
    assert config.svn_cache_dir == "E:/cache/project-clean"


def test_resolve_svn_cache_dir_relative_to_config_file(tmp_path: Path) -> None:
    config_dir = tmp_path / "repo"
    config_dir.mkdir()
    config_path = config_dir / "config.yaml"
    config_path.write_text("{}", encoding="utf-8")

    resolved = _resolve_config_relative_path(
        "workspace/cache/svn-clean",
        str(config_path),
    )

    assert resolved == str(config_dir / "workspace" / "cache" / "svn-clean")


def test_load_config_reads_diagnosis_prompt_options(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                'diagnosis_output_language: "zh-CN"',
                'diagnosis_prompt_append: "优先输出可执行的修复方向。"',
            ]
        ),
        encoding="utf-8",
    )

    config = load_config(str(config_path))

    assert config.diagnosis_output_language == "zh-CN"
    assert config.diagnosis_prompt_append == "优先输出可执行的修复方向。"
