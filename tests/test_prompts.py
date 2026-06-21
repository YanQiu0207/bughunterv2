"""Tests for diagnosis prompt construction."""

from src.agent.prompts import build_system_prompt


def test_prompt_requests_configured_output_language() -> None:
    prompt = build_system_prompt(output_language="zh-CN")

    assert "Write all natural-language diagnosis fields in zh-CN" in prompt


def test_prompt_includes_extra_instructions() -> None:
    prompt = build_system_prompt(
        output_language="zh-CN",
        extra_instructions="优先输出可执行的修复方向。",
    )

    assert "User-Configured Extra Instructions" in prompt
    assert "优先输出可执行的修复方向。" in prompt
