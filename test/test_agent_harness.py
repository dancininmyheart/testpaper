from __future__ import annotations

import unittest

from agent_harness import AgentHarness, HarnessStageSpec


class _DummyLangChainAgent:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    def invoke_json(self, **kwargs):
        return self.payload

    def invoke_text(self, **kwargs):
        return self.payload


class AgentHarnessTests(unittest.TestCase):
    def test_build_invocation_options_supports_thinking_shorthand(self) -> None:
        harness = AgentHarness(
            default_max_tokens=600,
            default_use_env_proxy=True,
            should_use_langchain_runtime=lambda profile: False,
            get_langchain_agent=lambda profile: _DummyLangChainAgent(""),
            normalize_json_payload=lambda text, expected_list_key: {"ok": True},
            legacy_json_caller=lambda **kwargs: {"ok": True},
            legacy_text_caller=lambda **kwargs: "ok",
        )
        options = harness.build_invocation_options(
            {
                "max_tokens": 256,
                "enable_thinking": "false",
                "thinking": "disabled",
                "reasoning_effort": "high",
                "detail": "high",
            },
            thinking_override="low",
        )
        self.assertEqual(options.token_limit, 256)
        self.assertTrue(options.enable_thinking)
        self.assertEqual(options.thinking, "enabled")
        self.assertEqual(options.reasoning_effort, "low")
        self.assertEqual(options.detail, "high")

    def test_build_invocation_options_drops_reasoning_effort_when_thinking_disabled(self) -> None:
        harness = AgentHarness(
            default_max_tokens=600,
            default_use_env_proxy=True,
            should_use_langchain_runtime=lambda profile: False,
            get_langchain_agent=lambda profile: _DummyLangChainAgent(""),
            normalize_json_payload=lambda text, expected_list_key: {"ok": True},
            legacy_json_caller=lambda **kwargs: {"ok": True},
            legacy_text_caller=lambda **kwargs: "ok",
        )
        options = harness.build_invocation_options(
            {
                "enable_thinking": False,
                "thinking": "disabled",
                "reasoning_effort": "high",
            }
        )
        self.assertFalse(options.enable_thinking)
        self.assertEqual(options.thinking, "disabled")
        self.assertIsNone(options.reasoning_effort)

    def test_invoke_json_parses_string_boolean_proxy_flag(self) -> None:
        captured = {}

        def _legacy_json_caller(**kwargs):
            captured.update(kwargs)
            return {"answers": []}

        harness = AgentHarness(
            default_max_tokens=600,
            default_use_env_proxy=True,
            should_use_langchain_runtime=lambda profile: False,
            get_langchain_agent=lambda profile: _DummyLangChainAgent(""),
            normalize_json_payload=lambda text, expected_list_key: {"answers": []},
            legacy_json_caller=_legacy_json_caller,
            legacy_text_caller=lambda **kwargs: "ok",
        )
        result = harness.invoke_json(
            profile={
                "base_url": "https://example.invalid",
                "api_key": "test-key",
                "model": "test-model",
                "use_env_proxy": "false",
            },
            prompt="test",
            data_urls=[],
            expected_list_key="answers",
        )
        self.assertEqual(result, {"answers": []})
        self.assertIs(captured["use_env_proxy"], False)

    def test_run_stage_uses_stage_expected_list_key_for_langchain_json(self) -> None:
        harness = AgentHarness(
            default_max_tokens=600,
            default_use_env_proxy=True,
            should_use_langchain_runtime=lambda profile: True,
            get_langchain_agent=lambda profile: _DummyLangChainAgent('[{"question_id": "Q1"}]'),
            normalize_json_payload=lambda text, expected_list_key: (
                {expected_list_key: [{"question_id": "Q1"}]} if expected_list_key else None
            ),
            legacy_json_caller=lambda **kwargs: {"should_not": "happen"},
            legacy_text_caller=lambda **kwargs: "ok",
        )
        result = harness.run_stage(
            HarnessStageSpec(name="blind", mode="json", expected_list_key="items"),
            profile={
                "base_url": "https://example.invalid",
                "api_key": "test-key",
                "model": "test-model",
            },
            prompt="test",
            data_urls=[],
        )
        self.assertEqual(result, {"items": [{"question_id": "Q1"}]})


if __name__ == "__main__":
    unittest.main()
