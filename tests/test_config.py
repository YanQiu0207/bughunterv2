"""Tests for runtime configuration loading."""

from pathlib import Path

from src.config import load_config


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
