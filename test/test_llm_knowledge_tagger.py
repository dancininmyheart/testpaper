import unittest
from unittest.mock import patch

import llm_knowledge_tagger


class _FakeResponse:
    def json(self):
        return {"choices": [{"message": {"content": "{}"}}]}


class LlmKnowledgeTaggerRequestTests(unittest.TestCase):
    def test_call_llm_with_images_omits_reasoning_effort_when_thinking_disabled(self) -> None:
        captured = {}

        def _fake_post_with_retry(url, headers, payload, timeout, **kwargs):
            captured.update(payload)
            return _FakeResponse()

        with patch.object(llm_knowledge_tagger, "_post_with_retry", _fake_post_with_retry):
            llm_knowledge_tagger.call_llm_with_images(
                prompt="test",
                data_urls=[],
                base_url="https://example.invalid/v1",
                api_key="test-key",
                model="test-model",
                enable_thinking=False,
                thinking="disabled",
                reasoning_effort="low",
            )

        self.assertEqual(captured["thinking"], {"type": "disabled"})
        self.assertNotIn("reasoning_effort", captured)

    def test_call_llm_with_images_keeps_reasoning_effort_when_thinking_enabled(self) -> None:
        captured = {}

        def _fake_post_with_retry(url, headers, payload, timeout, **kwargs):
            captured.update(payload)
            return _FakeResponse()

        with patch.object(llm_knowledge_tagger, "_post_with_retry", _fake_post_with_retry):
            llm_knowledge_tagger.call_llm_with_images(
                prompt="test",
                data_urls=[],
                base_url="https://example.invalid/v1",
                api_key="test-key",
                model="test-model",
                enable_thinking=True,
                thinking="enabled",
                reasoning_effort="low",
            )

        self.assertEqual(captured["thinking"], {"type": "enabled"})
        self.assertEqual(captured["reasoning_effort"], "low")


if __name__ == "__main__":
    unittest.main()
