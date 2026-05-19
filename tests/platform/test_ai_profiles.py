from __future__ import annotations

from backend.infrastructure.ai.profiles import AIProfile


def test_ai_profile_reads_key_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("TEST_LLM_KEY", "secret")

    profile = AIProfile.from_config(
        "unit",
        {
            "base_url": "https://example.test/v1",
            "model": "demo-model",
            "api_key_env": "TEST_LLM_KEY",
            "runtime": "langchain",
            "profile_role": "text",
            "max_tokens": 1024,
        },
    )

    assert profile.api_key == "secret"
    assert profile.runtime == "langchain"
    assert profile.role == "text"
    assert profile.max_tokens == 1024
    assert profile.trace_metadata()["api_key_env"] == "TEST_LLM_KEY"


def test_ai_profile_rejects_missing_environment_key(monkeypatch) -> None:
    monkeypatch.delenv("MISSING_LLM_KEY", raising=False)

    try:
        AIProfile.from_config(
            "unit",
            {
                "base_url": "https://example.test/v1",
                "model": "demo-model",
                "api_key_env": "MISSING_LLM_KEY",
            },
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "set env var MISSING_LLM_KEY" in str(exc)
