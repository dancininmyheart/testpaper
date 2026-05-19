from __future__ import annotations

import unittest
from unittest.mock import patch

import langchain_runtime


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeBoundModel:
    def invoke(self, messages):
        raise RuntimeError(
            "Error code: 400 - {'error': {'code': 'InvalidParameter', 'message': "
            "'The parameter `response_format.type` specified in the request are not valid: "
            "`json_object` is not supported by this model.', 'param': 'response_format.type', "
            "'type': 'BadRequest'}}"
        )


class _FakeChatOpenAI:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    def bind(self, **kwargs):
        return _FakeBoundModel()

    def invoke(self, messages):
        return _FakeResponse('{"answers":[{"question_id":"Q1"}]}')


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class LangChainRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(langchain_runtime.is_langchain_available(), "langchain runtime unavailable")
    def test_real_chatopenai_init_tolerates_missing_langchain_root_globals(self) -> None:
        runtime = langchain_runtime.LangChainAgentRuntime(
            base_url="https://example.invalid",
            api_key="test-key",
            model="test-model",
            timeout=30,
            max_retries=0,
            backoff_base_sec=0.1,
            min_interval_sec=0.0,
        )

        model = runtime._build_model(
            max_tokens=256,
            enable_thinking=False,
            thinking="disabled",
            reasoning_effort="low",
        )

        self.assertIsNotNone(model)

    def test_build_model_omits_reasoning_effort_when_thinking_disabled(self) -> None:
        with patch.object(langchain_runtime, "ChatOpenAI", _FakeChatOpenAI):
            runtime = langchain_runtime.LangChainAgentRuntime(
                base_url="https://example.invalid",
                api_key="test-key",
                model="test-model",
                timeout=30,
                max_retries=0,
                backoff_base_sec=0.1,
                min_interval_sec=0.0,
            )
            model = runtime._build_model(
                max_tokens=256,
                enable_thinking=False,
                thinking="disabled",
                reasoning_effort="low",
            )
        self.assertEqual(model.kwargs["extra_body"], {"thinking": {"type": "disabled"}})

    def test_invoke_json_falls_back_when_response_format_is_unsupported(self) -> None:
        with patch.object(langchain_runtime, "ChatOpenAI", _FakeChatOpenAI), patch.object(
            langchain_runtime,
            "SystemMessage",
            _FakeMessage,
        ), patch.object(langchain_runtime, "HumanMessage", _FakeMessage):
            runtime = langchain_runtime.LangChainAgentRuntime(
                base_url="https://example.invalid",
                api_key="test-key",
                model="test-model",
                timeout=30,
                max_retries=0,
                backoff_base_sec=0.1,
                min_interval_sec=0.0,
            )
            text = runtime.invoke_json(
                prompt="test prompt",
                data_urls=[],
                max_tokens=256,
                enable_thinking=False,
                thinking="disabled",
                reasoning_effort="low",
                detail=None,
            )
        self.assertEqual(text, '{"answers":[{"question_id":"Q1"}]}')


if __name__ == "__main__":
    unittest.main()
