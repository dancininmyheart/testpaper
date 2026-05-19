from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import demo_server


class StageContractWiringTests(unittest.TestCase):
    def test_harness_stages_use_shared_response_contract_keys(self) -> None:
        from demo.stage_contracts import expected_list_key
        from demo.service import (
            HARNESS_STAGE_ANSWER_KEY_CORRECTNESS,
            HARNESS_STAGE_ANSWER_STRUCT_AND_ALIGN,
            HARNESS_STAGE_BLIND_DIAGNOSIS,
            HARNESS_STAGE_QUESTION_ANALYSIS,
            HARNESS_STAGE_REFERENCE_ANSWER_GENERATE,
        )

        stage_specs = [
            HARNESS_STAGE_QUESTION_ANALYSIS,
            HARNESS_STAGE_ANSWER_STRUCT_AND_ALIGN,
            HARNESS_STAGE_REFERENCE_ANSWER_GENERATE,
            HARNESS_STAGE_ANSWER_KEY_CORRECTNESS,
            HARNESS_STAGE_BLIND_DIAGNOSIS,
        ]

        for spec in stage_specs:
            self.assertEqual(spec.expected_list_key, expected_list_key(spec.name))

    def test_prompt_texts_embed_shared_response_contract_examples(self) -> None:
        from demo.stage_contracts import response_contract

        self.assertIn(
            response_contract("answer_struct_and_align"),
            demo_server._answer_struct_and_align_prompt(
                [{"question_id": "Q1", "question_type": "solution", "problem_text": "x"}],
                [{"page_index": 0, "raw_text": "x=1"}],
            ),
        )
        self.assertIn(
            response_contract("reference_answer_generate"),
            demo_server._reference_answer_generate_prompt(
                [{"question_id": "Q1", "question_type": "solution", "problem_text": "x"}]
            ),
        )
        self.assertIn(
            response_contract("blind_step_analysis"),
            demo_server._blind_diagnosis_prompt(
                [{"question_id": "Q1", "problem_text": "x", "student_answer_text": "x=1"}]
            ),
        )


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _chat_payload(*, content: str = "", tool_args: str | None = None) -> dict:
    message = {"content": content}
    if tool_args is not None:
        message["tool_calls"] = [
            {
                "function": {
                    "arguments": tool_args,
                }
            }
        ]
    return {
        "choices": [
            {
                "message": message,
                "finish_reason": "stop",
            }
        ]
    }


class DemoServerJsonContractTests(unittest.TestCase):
    def _call_llm_json(self, payload: dict, *, expected_list_key: str | None = None) -> dict:
        with patch.object(demo_server, "_post_with_retry", return_value=_FakeResponse(payload)):
            return demo_server._call_llm_json(
                base_url="https://example.invalid",
                api_key="test-key",
                model="test-model",
                prompt="test prompt",
                data_urls=[],
                expected_list_key=expected_list_key,
            )

    def test_object_response_remains_supported(self) -> None:
        payload = _chat_payload(content='{"answers": [{"question_id": "Q1"}]}')
        data = self._call_llm_json(payload, expected_list_key="answers")
        self.assertEqual(data["answers"][0]["question_id"], "Q1")

    def test_array_response_wrapped_when_expected_key_is_provided(self) -> None:
        payload = _chat_payload(content='[{"question_id": "Q26"}]')
        data = self._call_llm_json(payload, expected_list_key="answers")
        self.assertEqual(data, {"answers": [{"question_id": "Q26"}]})

    def test_array_response_is_rejected_without_expected_key(self) -> None:
        payload = _chat_payload(content='[{"question_id": "Q26"}]')
        with self.assertRaisesRegex(ValueError, "valid JSON object"):
            self._call_llm_json(payload)

    def test_non_dict_array_items_are_rejected(self) -> None:
        payload = _chat_payload(content='["Q26"]')
        with self.assertRaisesRegex(ValueError, "valid JSON object"):
            self._call_llm_json(payload, expected_list_key="answers")

    def test_tool_call_arguments_follow_same_array_compatibility_rule(self) -> None:
        payload = _chat_payload(content="", tool_args='[{"question_id": "Q26"}]')
        data = self._call_llm_json(payload, expected_list_key="answers")
        self.assertEqual(data, {"answers": [{"question_id": "Q26"}]})

    def test_expected_list_payload_accepts_nested_data_alias(self) -> None:
        payload = _chat_payload(content='{"data":{"items":[{"question_id":"Q7"}]}}')
        data = self._call_llm_json(payload, expected_list_key="answers")
        self.assertEqual(data["answers"], [{"question_id": "Q7"}])

    def test_question_normalization_accepts_alias_fields(self) -> None:
        item = demo_server._normalize_question_item(
            {
                "题号": "第十二题",
                "题干": "计算下列各题",
                "题型": "解答题",
                "分值": "8分",
                "knowledge_points": ["algebra.linear"],
                "小题": [{"小题号": "一", "text": "第一问"}],
                "confidence": "0.86",
            }
        )
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item["question_id"], "Q12")
        self.assertEqual(item["question_type"], "solution")
        self.assertEqual(item["max_score"], 8.0)
        self.assertEqual(item["skill_tags"], ["algebra.linear"])

    def test_question_normalization_prefers_outer_page_index(self) -> None:
        item = demo_server._normalize_question_item(
            {
                "question_id": "Q20",
                "paper_page_index": 0,
                "problem_text": "page-local model output",
            },
            page_index=2,
        )
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item["paper_page_index"], 2)

    def test_question_merge_does_not_overwrite_text_across_pages(self) -> None:
        existing = {
            "question_id": "Q20",
            "paper_page_index": 2,
            "problem_text": "calculate radicals",
            "problem_text_full": "20. calculate radicals",
            "skill_tags": [],
            "sub_questions": [],
        }
        incoming = {
            "question_id": "Q20",
            "paper_page_index": 0,
            "problem_text": "parking lot equation with much longer but wrong text",
            "problem_text_full": "20. parking lot equation with much longer but wrong full text",
            "skill_tags": [],
            "sub_questions": [],
        }

        merged = demo_server._merge_question_items(existing, incoming)

        self.assertEqual(merged["paper_page_index"], 2)
        self.assertEqual(merged["problem_text"], "calculate radicals")
        self.assertEqual(merged["problem_text_full"], "20. calculate radicals")

    def test_answer_and_correctness_normalizers_accept_string_values(self) -> None:
        context = {
            "question_id": "Q3",
            "question_type": "choice",
            "skill_tags": [],
            "sub_questions": [],
            "max_score": 5,
        }
        context_map = {"Q3": context}
        answer = demo_server._normalize_answer_item(
            {
                "题号": 3,
                "status": "done",
                "answer": "A",
                "choice": "A",
                "得分": "5分",
                "满分": "5",
                "是否正确": "正确",
                "confidence": "0.92",
            },
            context_map,
        )
        self.assertIsNotNone(answer)
        assert answer is not None
        self.assertEqual(answer["question_id"], "Q3")
        self.assertEqual(answer["status"], "answered")
        self.assertTrue(answer["is_correct"])
        self.assertEqual(answer["score"], 5.0)
        self.assertEqual(answer["trace"]["confidence"], 0.92)

        correctness = demo_server._normalize_answer_key_correctness_item(
            {"题号": "3", "verdict": "wrong", "confidence": "0.7", "reason": "选项不一致"},
            context_map,
        )
        self.assertEqual(correctness["question_id"], "Q3")
        self.assertFalse(correctness["by_answer_key"])
        self.assertEqual(correctness["confidence"], 0.7)

    def test_answer_normalization_drops_self_sub_question_id(self) -> None:
        context_map = {
            "Q9": {
                "question_id": "Q9",
                "question_type": "blank",
                "skill_tags": [],
                "sub_questions": [],
                "max_score": 5,
            }
        }
        answer = demo_server._normalize_answer_item(
            {
                "question_id": "Q9",
                "sub_question_id": "Q9",
                "status": "answered",
                "student_answer_text": "4",
            },
            context_map,
        )

        self.assertIsNotNone(answer)
        assert answer is not None
        self.assertIsNone(answer["sub_question_id"])

    def test_call_llm_json_falls_back_when_json_object_response_format_is_unsupported(self) -> None:
        payload = _chat_payload(content='{"answers": [{"question_id": "Q1"}]}')

        captured_payloads = []

        def _fake_post(url, headers, request_payload, timeout, **kwargs):
            captured_payloads.append(dict(request_payload))
            if len(captured_payloads) == 1:
                raise RuntimeError(
                    "Error code: 400 - {'error': {'code': 'InvalidParameter', 'message': "
                    "'The parameter `response_format.type` specified in the request are not valid: "
                    "`json_object` is not supported by this model.', 'param': 'response_format.type', "
                    "'type': 'BadRequest'}}"
                )
            return _FakeResponse(payload)

        with patch.object(demo_server, "_post_with_retry", side_effect=_fake_post):
            data = demo_server._call_llm_json(
                base_url="https://example.invalid",
                api_key="test-key",
                model="test-model",
                prompt="test prompt",
                data_urls=[],
                expected_list_key="answers",
            )

        self.assertEqual(data, {"answers": [{"question_id": "Q1"}]})
        self.assertEqual(len(captured_payloads), 2)
        self.assertIn("response_format", captured_payloads[0])
        self.assertNotIn("response_format", captured_payloads[1])

    def test_answer_repair_q26_preview_is_wrapped_into_answers_object(self) -> None:
        payload = _chat_payload(
            content=(
                '[{"question_id":"Q26","sub_question_id":"Q26(1)","status":"unseen",'
                '"score":null,"max_score":null,"is_correct":null,"confidence":1.0,'
                '"page_index":0,"source_stage":"subjective","evidence":"图片中未显示Q26题目及作答区域"}]'
            )
        )
        data = self._call_llm_json(payload, expected_list_key="answers")
        self.assertEqual(data["answers"][0]["question_id"], "Q26")
        self.assertEqual(data["answers"][0]["sub_question_id"], "Q26(1)")

    def test_answer_trace_display_splits_sub_questions_for_frontend(self) -> None:
        structured_questions = [
            {
                "question_id": "Q26",
                "question_type": "solution",
                "skill_tags": ["root.method.rationalize_denominator"],
                "question_anchor_text": "化简题",
                "problem_text": "已知...",
                "sub_questions": [
                    {"sub_question_id": "Q26(1)", "sub_text": "先化简"},
                    {"sub_question_id": "Q26(2)", "sub_text": "再求值"},
                ],
                "answer_trace": {
                    "question_id": "Q26",
                    "status": "answered",
                    "score": 10,
                    "max_score": 14,
                    "trace": {"confidence": 0.8},
                },
                "sub_traces": [
                    {
                        "question_id": "Q26",
                        "sub_question_id": "Q26(1)",
                        "status": "answered",
                        "score": 4,
                        "max_score": 6,
                        "trace": {"confidence": 0.9},
                    },
                    {
                        "question_id": "Q26",
                        "sub_question_id": "Q26(2)",
                        "status": "unseen",
                        "score": None,
                        "max_score": 8,
                        "trace": {"confidence": 0.4},
                    },
                ],
            }
        ]
        display = demo_server._build_answer_trace_display(structured_questions)
        self.assertEqual([item["display_question_id"] for item in display], ["Q26(1)", "Q26(2)"])
        self.assertEqual(display[0]["sub_question_text"], "先化简")
        self.assertEqual(display[1]["parent_question_id"], "Q26")

    def test_prompt_texts_keep_json_contract_and_utf8_chinese(self) -> None:
        prompts = [
            demo_server._paper_prompt([], mode="index"),
            demo_server._paper_prompt([], mode="full", target_question_ids=["Q1"]),
            demo_server._route_prompt(
                [{"question_id": "Q1", "question_anchor_text": "anchor", "neighbor_question_ids": [], "sub_questions": []}],
                0,
            ),
            demo_server._score_repair_prompt(
                [{"question_id": "Q26", "question_type": "solution", "sub_questions": [{"sub_question_id": "Q26(1)"}]}],
                [{"question_id": "Q26", "status": "unseen"}],
                ["Q26"],
            ),
            demo_server._blind_diagnosis_prompt(
                [{"question_id": "Q1", "problem_text": "题目", "student_answer_text": "x=1", "steps": ["x=1"]}]
            ),
            demo_server._profile_prompt("41200105", [], [], {}),
            demo_server._new_point_prompt("new.skill", {"problem_text": "problem"}, ["existing.id"]),
        ]

        expected_snippets = [
            '"questions"',
            "\u53ea\u8fd4\u56de JSON \u5bf9\u8c61",
            '"routes"',
            '{"answers": [...]}',
            '"blind_diagnosis"',
            '"student_id"',
            '"new_point"',
        ]
        for prompt, snippet in zip(prompts, expected_snippets):
            self.assertIn(snippet, prompt)
        self.assertIn("失分", demo_server._error_analysis_prompt([]))

    def test_prompt_store_keeps_single_error_analysis_prompt_definition(self) -> None:
        source = Path("prompt_store.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("def error_analysis_prompt("), 1)

    def test_demo_index_uses_mode_config_table_for_payload(self) -> None:
        html = Path("demo_index.html").read_text(encoding="utf-8")
        self.assertIn("const MODE_CONFIG =", html)
        self.assertIn("function getModeConfig(mode)", html)
        self.assertIn("const config = getModeConfig(inputMode);", html)
        self.assertIn("const config = getModeConfig(mode);", html)
        self.assertIn("paper_answer_with_key", html)
        self.assertIn("paper_answer_auto_key", html)
        self.assertIn("paper_same_page", html)
        self.assertIn("pre_split_questions", html)
        self.assertIn("pre_split_questions: preSplitQuestions", html)
        self.assertIn("id=\"visionProfile\"", html)
        self.assertIn("id=\"textProfile\"", html)
        self.assertIn("vision_profile: visionProfile", html)
        self.assertIn("text_profile: textProfile", html)
        self.assertIn("/api/demo/model-options", html)

    def test_service_model_options_returns_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "llm_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "defaults": {"profile": "vision_profile"},
                        "openai_profiles": {
                            "vision_profile": {
                                "profile_role": "vision",
                                "runtime": "langchain",
                                "provider": "openai_compatible",
                                "base_url": "https://example.invalid/v1",
                                "model": "vision-model",
                                "api_key": "k1",
                                "text_profile": "text_profile",
                            },
                            "text_profile": {
                                "profile_role": "text",
                                "runtime": "langchain",
                                "provider": "openai_compatible",
                                "base_url": "https://example.invalid/v1",
                                "model": "text-model",
                                "api_key": "k2",
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            keyword_path = Path(tmp_dir) / "key_word.json"
            keyword_path.write_text(json.dumps({"nodes": []}, ensure_ascii=False), encoding="utf-8")
            service = demo_server.DemoService(config_path, None, keyword_path, mock_mode=False)
            options = service.get_model_options()
        self.assertIsInstance(options.get("vision_profiles"), list)
        self.assertIsInstance(options.get("text_profiles"), list)
        self.assertEqual(options.get("default_vision_profile"), "vision_profile")
        self.assertEqual(options.get("default_text_profile"), "text_profile")

    def test_real_config_exposes_gemini_deepseek_fast_profiles(self) -> None:
        service = demo_server.DemoService(Path("llm_config.json"), None, Path("key_word.json"), mock_mode=True)
        options = service.get_model_options()
        vision_names = {item["name"] for item in options.get("vision_profiles", [])}
        text_names = {item["name"] for item in options.get("text_profiles", [])}
        self.assertIn("openai_vision_gemini_3_flash_fast", vision_names)
        self.assertIn("openai_text_deepseek_v4_pro_fast", text_names)
        fast_vision = next(item for item in options["vision_profiles"] if item["name"] == "openai_vision_gemini_3_flash_fast")
        self.assertEqual(fast_vision["recommended_text_profile"], "openai_text_deepseek_v4_pro_fast")

    def test_load_profile_by_name_converts_system_exit_to_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "llm_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "defaults": {"profile": "safe_default"},
                        "openai_profiles": {
                            "safe_default": {
                                "runtime": "langchain",
                                "provider": "openai_compatible",
                                "base_url": "https://example.invalid/v1",
                                "model": "safe-model",
                                "api_key": "safe-key",
                                "text_profile": "safe_default",
                            },
                            "broken_profile": {
                                "runtime": "langchain",
                                "provider": "openai_compatible",
                                "base_url": "https://example.invalid/v1",
                                "model": "broken-model",
                                "api_key_env": "THIS_ENV_SHOULD_NOT_EXIST_FOR_TEST",
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            keyword_path = Path(tmp_dir) / "key_word.json"
            keyword_path.write_text(json.dumps({"nodes": []}, ensure_ascii=False), encoding="utf-8")
            service = demo_server.DemoService(config_path, None, keyword_path, mock_mode=False)
            with self.assertRaises(ValueError):
                service._load_profile_by_name("broken_profile")

    def test_blind_diagnosis_prompt_excludes_teacher_signal_keys(self) -> None:
        prompt = demo_server._blind_diagnosis_prompt(
            [
                {
                    "question_id": "Q1",
                    "problem_text": "解方程",
                    "student_answer_text": "2x=8\nx=4",
                    "answer_text": "2x=8\nx=4",
                    "steps": ["2x=8", "x=4"],
                }
            ]
        )
        self.assertIn('"blind_diagnosis"', prompt)
        self.assertNotIn('"score"', prompt)
        self.assertNotIn('"max_score"', prompt)
        self.assertNotIn('"is_correct"', prompt)

    def test_answer_alignment_prompt_references_preliminary_answers_and_raw_texts(self) -> None:
        prompt = demo_server._answer_alignment_prompt(
            [
                {
                    "question_id": "Q1",
                    "question_type": "solution",
                    "problem_text": "解方程",
                    "sub_questions": [{"sub_question_id": "Q1(1)", "sub_text": "求 x"}],
                }
            ],
            [{"question_id": "QX", "student_answer_text": "2x=8"}],
            [{"page_index": 0, "source": "page_1_seg_1", "raw_text": "2x=8"}],
        )
        self.assertIn('"answers"', prompt)
        self.assertIn("preliminary_answers=", prompt)
        self.assertIn("raw_answer_texts_by_page=", prompt)
        self.assertIn("structured_questions=", prompt)

    def test_combined_answer_struct_prompt_uses_compact_payload(self) -> None:
        prompt = demo_server._answer_struct_and_align_prompt(
            [
                {
                    "question_id": "Q1",
                    "question_type": "solution",
                    "problem_text": "short problem",
                    "problem_text_full": "x" * 3000,
                    "sub_questions": [{"sub_question_id": "Q1(1)", "sub_text": "sub" * 200}],
                    "debug_payload": "should not be sent",
                    "skill_tags": ["skill.a"],
                }
            ],
            [
                {
                    "page_index": 0,
                    "raw_text": "answer text",
                    "saved_crop_path": "outputs/crop.png",
                    "prompt": "debug prompt",
                    "context_question_ids": ["Q1"],
                }
            ],
        )
        self.assertIn('"answers"', prompt)
        self.assertIn("structured_questions=", prompt)
        self.assertIn("raw_answer_texts_by_page=", prompt)
        self.assertNotIn("debug_payload", prompt)
        self.assertNotIn("saved_crop_path", prompt)
        self.assertNotIn("debug prompt", prompt)

    def test_blind_diagnosis_target_selector_skips_clear_correct_answers(self) -> None:
        correct = {
            "question_id": "Q1",
            "status": "answered",
            "student_answer_text": "x=4",
            "score": 5,
            "max_score": 5,
            "is_correct": True,
            "trace": {"confidence": 0.92},
        }
        wrong = {
            "question_id": "Q2",
            "status": "answered",
            "student_answer_text": "x=3",
            "score": 2,
            "max_score": 5,
            "is_correct": False,
            "trace": {"confidence": 0.86},
        }
        uncertain = {
            "question_id": "Q3",
            "status": "unclear",
            "student_answer_text": "maybe x=4",
            "trace": {"confidence": 0.4},
        }
        self.assertFalse(demo_server._should_run_blind_diagnosis_for_answer(correct))
        self.assertTrue(demo_server._should_run_blind_diagnosis_for_answer(wrong))
        self.assertTrue(demo_server._should_run_blind_diagnosis_for_answer(uncertain))

    def test_blind_diagnosis_respects_max_item_limit(self) -> None:
        service = demo_server.DemoService(Path("llm_config.json"), None, Path("key_word.json"), mock_mode=True)
        service.blind_diagnosis_max_items = 2
        service.question_chunk_size = 8
        questions = [
            {"question_id": f"Q{i}", "question_type": "solution", "problem_text": f"Q{i}"}
            for i in range(1, 5)
        ]
        answers = [
            {
                "question_id": f"Q{i}",
                "status": "answered",
                "student_answer_text": f"answer {i}",
                "score": i - 1,
                "max_score": 5,
                "is_correct": False,
                "trace": {"confidence": 0.8},
            }
            for i in range(1, 5)
        ]

        def fake_stage(*args, **kwargs):
            return {
                "items": [
                    {
                        "question_id": "Q1",
                        "blind_diagnosis": {
                            "error_type": "calculation",
                            "reason": "r",
                            "confidence": 0.8,
                        },
                    },
                    {
                        "question_id": "Q2",
                        "blind_diagnosis": {
                            "error_type": "concept",
                            "reason": "r",
                            "confidence": 0.8,
                        },
                    },
                ]
            }

        with patch.object(service, "_run_harness_stage", side_effect=fake_stage):
            blind_by_id, count = service._run_blind_diagnosis(questions, answers, [])
        self.assertEqual(service._last_blind_diagnosis_target_count, 2)
        self.assertEqual(count, 2)
        self.assertLessEqual(len(blind_by_id), 2)

    def test_profile_prompt_uses_compact_graph_subset(self) -> None:
        prompt = demo_server._profile_prompt(
            "S1",
            [{"question_id": "Q1", "problem_text_full": "p" * 2000, "skill_tags": ["skill.keep"]}],
            [{"question_id": "Q1", "student_answer_text": "a" * 1200, "skill_tags": ["skill.keep"]}],
            {
                "nodes": [
                    {"id": "skill.keep", "name": "Keep", "description": "d" * 1000},
                    {"id": "skill.drop", "name": "Drop", "description": "d" * 1000},
                ]
            },
        )
        self.assertIn("skill.keep", prompt)
        self.assertNotIn("skill.drop", prompt)
        self.assertNotIn('"description"', prompt)

    def test_reference_answer_generate_runs_in_chunks(self) -> None:
        service = demo_server.DemoService(Path("llm_config.json"), None, Path("key_word.json"), mock_mode=True)
        service.profile = {"name": "vision_profile", "profile_role": "vision"}
        service.text_profile = {"name": "text_profile", "profile_role": "text"}
        service.question_chunk_size = 2
        service.reference_answer_chunk_size = 2
        service.answer_concurrency = 2
        answer_contexts = [
            {"question_id": f"Q{i}", "question_type": "solution", "problem_text": f"Q{i}"}
            for i in range(1, 6)
        ]
        calls: list[int] = []
        data_url_calls: list[list[str]] = []
        profile_calls: list[str] = []

        def fake_common(**kwargs):
            contexts = kwargs["answer_contexts"]
            calls.append(len(contexts))
            data_url_calls.append(list(kwargs.get("data_urls") or []))
            profile = kwargs.get("profile")
            profile_calls.append(profile.get("name") if isinstance(profile, dict) else "")
            return [
                {
                    "question_id": item["question_id"],
                    "reference_answer_text": "ref",
                    "reference_final_answer": "ref",
                    "reference_steps": ["ref"],
                    "confidence": 0.9,
                }
                for item in contexts
            ]

        with patch.object(service, "_run_reference_answer_common", side_effect=fake_common):
            refs = service._run_reference_answer_generate(
                answer_contexts=answer_contexts,
                paper_urls=["paper-page-1", "paper-page-2"],
                warnings=[],
            )
        self.assertEqual(len(refs), 5)
        self.assertEqual(sorted(calls), [1, 2, 2])
        self.assertTrue(data_url_calls)
        self.assertTrue(all(call == ["paper-page-1", "paper-page-2"] for call in data_url_calls))
        self.assertTrue(profile_calls)
        self.assertTrue(all(name == "vision_profile" for name in profile_calls))
        self.assertEqual(service._last_reference_generate_stats["chunk_count"], 3)

    def test_reference_answer_generate_retries_missing_chunk_items_as_single_questions(self) -> None:
        service = demo_server.DemoService(Path("llm_config.json"), None, Path("key_word.json"), mock_mode=True)
        service.question_chunk_size = 4
        service.reference_answer_chunk_size = 4
        service.answer_concurrency = 1
        answer_contexts = [
            {"question_id": f"Q{i}", "question_type": "solution", "problem_text": f"Q{i}"}
            for i in range(1, 5)
        ]
        calls: list[list[str]] = []

        def fake_common(**kwargs):
            contexts = kwargs["answer_contexts"]
            ids = [item["question_id"] for item in contexts]
            calls.append(ids)
            if len(contexts) > 1:
                return []
            item = contexts[0]
            return [
                {
                    "question_id": item["question_id"],
                    "reference_answer_text": "ref",
                    "reference_final_answer": "ref",
                    "reference_steps": ["ref"],
                    "confidence": 0.9,
                }
            ]

        with patch.object(service, "_run_reference_answer_common", side_effect=fake_common):
            refs = service._run_reference_answer_generate(answer_contexts=answer_contexts, warnings=[])

        self.assertEqual({item["question_id"] for item in refs}, {"Q1", "Q2", "Q3", "Q4"})
        self.assertEqual(calls[0], ["Q1", "Q2", "Q3", "Q4"])
        self.assertEqual(calls[1:], [["Q1"], ["Q2"], ["Q3"], ["Q4"]])

    def test_answer_raw_section_prompt_does_not_require_question_id_output(self) -> None:
        prompt = demo_server._answer_raw_section_prompt(
            [],
            page_index=0,
            section_name="page-1-segment-1",
            segment_class_name="subjective_problem",
        )
        self.assertNotIn("candidate_questions=", prompt)
        self.assertNotIn("本区域无候选题号", prompt)
        self.assertIn("不要输出 question_id", prompt)

    def test_call_json_with_profile_uses_langchain_runtime_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            keyword_path = Path(tmp_dir) / "key_word.json"
            keyword_path.write_text(json.dumps({"nodes": []}, ensure_ascii=False), encoding="utf-8")
            service = demo_server.DemoService(Path(tmp_dir) / "llm_config.json", None, keyword_path, mock_mode=True)
            profile = {
                "name": "text_analysis",
                "runtime": "langchain",
                "provider": "openai_compatible",
                "base_url": "https://example.invalid",
                "api_key": "test-key",
                "model": "test-model",
                "timeout_sec": 30,
                "max_retries": 0,
                "backoff_base_sec": 0.1,
                "min_interval_sec": 0.0,
                "max_tokens": 512,
            }
            with patch.object(service, "_should_use_langchain_runtime", return_value=True):
                with patch.object(service, "_get_langchain_agent") as get_agent:
                    get_agent.return_value.invoke_json.return_value = '{"answers": [{"question_id": "Q1"}]}'
                    data = service._call_json_with_profile(
                        profile,
                        prompt="test prompt",
                        data_urls=[],
                        expected_list_key="answers",
                    )
        self.assertEqual(data, {"answers": [{"question_id": "Q1"}]})

    def test_normalize_profile_payload_fills_all_literacy_dimensions(self) -> None:
        profile = demo_server._normalize_profile_payload(
            "41200105",
            {
                "student_id": "41200105",
                "literacy": [
                    {
                        "literacy_id": "number_sense",
                        "name": "数感",
                        "value": 0.8,
                        "level": "high",
                        "evidence": ["Q1"],
                        "reason": "数量关系判断较稳",
                        "suggestion": "保持估算训练",
                    }
                ],
            },
        )
        literacy = profile.get("literacy")
        self.assertIsInstance(literacy, list)
        self.assertEqual(len(literacy), len(demo_server.PROFILE_LITERACY_DIMENSIONS))
        self.assertEqual(literacy[0]["literacy_id"], "number_sense")
        self.assertIn("definition", literacy[0])
        self.assertIn("confidence", literacy[0])
        self.assertIn("source_breakdown", literacy[0])

    def test_rule_based_literacy_profile_uses_mapping_rules(self) -> None:
        mapping = demo_server._load_literacy_mapping_payload(Path("literacy_mapping.json"))
        profile = demo_server._build_rule_based_literacy_profile(
            [
                {
                    "question_id": "Q1",
                    "question_type": "blank",
                    "skill_tags": ["eq.method.linear_transpose"],
                    "problem_text": "解方程并填空",
                }
            ],
            [
                {
                    "question_id": "Q1",
                    "status": "answered",
                    "score": 0,
                    "max_score": 5,
                    "error_analysis": {
                        "error_type": "calculation",
                        "wrong_step": "移项环节出错",
                        "reason": "移项后符号错误",
                    },
                }
            ],
            mapping,
        )
        self.assertEqual(len(profile), len(demo_server.PROFILE_LITERACY_DIMENSIONS))
        operation_item = next(item for item in profile if item["literacy_id"] == "operation_ability")
        self.assertLess(operation_item["value"], 0.5)
        self.assertIn("Q1", operation_item["evidence"])
        self.assertGreater(operation_item["source_breakdown"]["skill_tag"], 0)

    def test_apply_diagnosis_fields_attaches_blind_and_teacher_channels(self) -> None:
        answers = [
            {
                "question_id": "Q1",
                "status": "answered",
                "score": 3,
                "max_score": 5,
                "is_correct": False,
                "trace": {"confidence": 0.86},
            }
        ]
        structured_questions = [
            {
                "question_id": "Q1",
                "answer_trace": {"question_id": "Q1", "trace": {"confidence": 0.86}},
                "sub_traces": [{"question_id": "Q1", "sub_question_id": "Q1(1)", "trace": {"confidence": 0.5}}],
            }
        ]
        blind_by_id = {
            "Q1": {
                "standard_steps": [{"step_index": 1, "content": "标准步骤", "skill_tags": ["skill.a"]}],
                "student_steps": [{"step_index": 1, "content": "学生步骤", "evidence": "2x=8"}],
                "divergence_point": "移项环节",
                "error_type": "calculation",
                "reason": "移项后符号错误",
                "evidence_span": "2x=8",
                "repair_suggestion": "检查移项符号",
                "suggestion": "复盘移项步骤",
                "is_correct_estimate": False,
                "confidence": 0.84,
            }
        }
        teacher_review_by_id = {
            "Q1": {"score": 3, "max_score": 5, "is_correct": False, "score_source_confidence": 0.86}
        }

        demo_server._apply_diagnosis_fields_to_answers(
            answers,
            structured_questions,
            blind_by_id,
            teacher_review_by_id,
        )

        self.assertIn("blind_diagnosis", answers[0])
        self.assertIn("teacher_review", answers[0])
        self.assertIn("diagnosis_validation", answers[0])
        self.assertEqual(answers[0]["diagnosis_validation"]["validated"], True)
        self.assertEqual(answers[0]["error_analysis"]["wrong_step"], "移项环节")
        self.assertIn("blind_diagnosis", structured_questions[0]["sub_traces"][0])

    def test_mask_red_review_marks_data_url_whitens_red_pixels(self) -> None:
        if demo_server.cv2 is None or demo_server.np is None:
            self.skipTest("opencv/numpy unavailable")
        image = demo_server.np.full((8, 8, 3), 255, dtype=demo_server.np.uint8)
        image[3:5, 3:5] = [0, 0, 255]
        ok, encoded = demo_server.cv2.imencode(".png", image)
        self.assertTrue(ok)
        data_url = demo_server._image_bytes_to_data_url(encoded.tobytes(), "png")

        filtered_url = demo_server._mask_red_review_marks_data_url(data_url)
        _, filtered_bytes = demo_server._decode_image_data_url(filtered_url)
        filtered = demo_server.cv2.imdecode(
            demo_server.np.frombuffer(filtered_bytes, dtype=demo_server.np.uint8),
            demo_server.cv2.IMREAD_COLOR,
        )

        self.assertIsNotNone(filtered)
        center_pixel = filtered[4, 4].tolist()
        self.assertGreaterEqual(center_pixel[0], 240)
        self.assertGreaterEqual(center_pixel[1], 240)
        self.assertGreaterEqual(center_pixel[2], 240)

    def test_normalize_answer_item_accepts_string_steps_and_infers_from_answer_text(self) -> None:
        context_map = {
            "Q1": {
                "question_id": "Q1",
                "question_type": "solution",
                "skill_tags": [],
                "answer_page_hint": 0,
                "max_score": 6,
            }
        }
        normalized_from_string = demo_server._normalize_answer_item(
            {
                "question_id": "Q1",
                "status": "answered",
                "student_answer_text": "2x+3=11\n2x=8\nx=4",
                "steps": "2x+3=11 -> 2x=8 -> x=4",
            },
            context_map,
        )
        self.assertEqual(normalized_from_string["steps"], ["2x+3=11", "2x=8", "x=4"])

        normalized_inferred = demo_server._normalize_answer_item(
            {
                "question_id": "Q1",
                "status": "answered",
                "student_answer_text": "2x+3=11\n2x=8\nx=4",
            },
            context_map,
        )
        self.assertEqual(normalized_inferred["steps"], ["2x+3=11", "2x=8", "x=4"])

    def test_canonical_sub_question_id_accepts_ascii_and_chinese_tokens(self) -> None:
        self.assertEqual(demo_server._canonical_sub_question_id("Q26", "1"), "Q26(1)")
        self.assertEqual(demo_server._canonical_sub_question_id("Q26", "二"), "Q26(二)")

    def test_parent_steps_are_distributed_to_sub_traces_when_sub_steps_missing(self) -> None:
        questions = [
            {
                "question_id": "Q26",
                "question_type": "solution",
                "sub_questions": [
                    {"sub_question_id": "Q26(1)", "sub_text": "先化简"},
                    {"sub_question_id": "Q26(2)", "sub_text": "再求值"},
                ],
            }
        ]
        merged_answers = [
            {
                "question_id": "Q26",
                "question_type": "solution",
                "status": "answered",
                "student_answer_text": "2x+3=11\n2x=8\nx=4",
                "answer_text": "2x+3=11\n2x=8\nx=4",
                "steps": ["2x+3=11", "2x=8", "x=4"],
                "trace": {"confidence": 0.8},
            }
        ]
        structured, _ = demo_server._build_structured_questions_and_mapping_report(
            questions,
            merged_answers,
            merged_answers,
            [],
            [],
        )
        sub_traces = structured[0]["sub_traces"]
        self.assertEqual(sub_traces[0]["steps"], ["2x+3=11", "2x=8"])
        self.assertEqual(sub_traces[1]["steps"], ["x=4"])

    def test_raw_text_fallback_builds_answer_steps_for_single_question_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            keyword_path = Path(tmp_dir) / "key_word.json"
            keyword_path.write_text(json.dumps({"nodes": []}, ensure_ascii=False), encoding="utf-8")
            service = demo_server.DemoService(Path(tmp_dir) / "llm_config.json", None, keyword_path, mock_mode=True)
            answer_context_map = {
                "Q1": {
                    "question_id": "Q1",
                    "question_type": "solution",
                    "skill_tags": [],
                    "answer_page_hint": 0,
                    "max_score": 6,
                }
            }
            fallback_answers = service._build_raw_text_fallback_answers(
                page_raw_items=[
                    {
                        "page_index": 0,
                        "raw_text": "[source=page_1_seg_1 section=sec page=0]\n2x+3=11\n2x=8\nx=4",
                        "context_question_ids": ["Q1"],
                    }
                ],
                answer_context_map=answer_context_map,
            )
        self.assertEqual(len(fallback_answers), 1)
        self.assertEqual(fallback_answers[0]["question_id"], "Q1")
        self.assertEqual(fallback_answers[0]["steps"], ["2x+3=11", "2x=8", "x=4"])

    def test_merge_and_fill_answers_preserves_combined_trace_fragments(self) -> None:
        question_contexts = [
            {
                "question_id": "Q1",
                "raw_question_id": "Q1",
                "question_type": "solution",
                "skill_tags": [],
                "answer_page_hint": 0,
                "max_score": 6,
            }
        ]
        answer_candidates = [
            {
                "question_id": "Q1",
                "raw_question_id": "Q1",
                "question_type": "solution",
                "status": "answered",
                "score": 5,
                "max_score": 6,
                "student_answer_text": "2x+3=11\n2x=8",
                "answer_text": "2x+3=11\n2x=8",
                "steps": ["2x+3=11", "2x=8"],
                "trace": {
                    "scratchwork": False,
                    "corrections": False,
                    "readability": 0.6,
                    "confidence": 0.6,
                    "notes": "左侧主解",
                },
            },
            {
                "question_id": "Q1",
                "raw_question_id": "Q1",
                "question_type": "solution",
                "status": "answered",
                "student_answer_text": "x=4\n扣1分",
                "answer_text": "x=4\n扣1分",
                "steps": ["x=4"],
                "trace": {
                    "scratchwork": True,
                    "corrections": True,
                    "readability": 0.8,
                    "confidence": 0.8,
                    "notes": "右侧批注",
                },
            },
        ]

        merged = demo_server._merge_and_fill_answers(answer_candidates, question_contexts)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["steps"], ["2x+3=11", "2x=8", "x=4"])
        self.assertIn("2x+3=11", merged[0]["student_answer_text"])
        self.assertIn("x=4", merged[0]["student_answer_text"])
        self.assertIn("左侧主解", merged[0]["trace"]["notes"])
        self.assertIn("右侧批注", merged[0]["trace"]["notes"])
        self.assertTrue(merged[0]["trace"]["scratchwork"])
        self.assertTrue(merged[0]["trace"]["corrections"])

    def test_merge_and_fill_answers_uses_best_single_blank_candidate(self) -> None:
        question_contexts = [
            {
                "question_id": "Q11",
                "raw_question_id": "Q11",
                "question_type": "fill_blank",
                "skill_tags": [],
                "answer_page_hint": 0,
                "max_score": 3,
            }
        ]
        answer_candidates = [
            {
                "question_id": "Q11",
                "question_type": "fill_blank",
                "status": "answered",
                "student_answer_text": "9.07x10^6",
                "trace": {"confidence": 0.4},
            },
            {
                "question_id": "Q11",
                "question_type": "fill_blank",
                "status": "answered",
                "student_answer_text": "9.07x10^-4",
                "trace": {"confidence": 0.9},
            },
        ]

        merged = demo_server._merge_and_fill_answers(answer_candidates, question_contexts)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["student_answer_text"], "9.07x10^-4")
        self.assertNotIn("9.07x10^6", merged[0]["student_answer_text"])

    def test_merge_and_fill_answers_sets_reason_code_when_no_candidate_exists(self) -> None:
        question_contexts = [
            {
                "question_id": "Q1",
                "raw_question_id": "Q1",
                "question_type": "solution",
                "skill_tags": [],
                "answer_page_hint": 0,
                "max_score": 6,
            }
        ]
        merged = demo_server._merge_and_fill_answers(
            [],
            question_contexts,
            default_empty_reason_code="no_nonempty_raw_text",
        )
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["trace"]["reason_code"], "no_nonempty_raw_text")
        self.assertIn("原始转写", merged[0]["trace"]["notes"])

    def test_merge_and_fill_answers_sets_reason_code_when_candidate_has_no_signal(self) -> None:
        question_contexts = [
            {
                "question_id": "Q1",
                "raw_question_id": "Q1",
                "question_type": "solution",
                "skill_tags": [],
                "answer_page_hint": 0,
                "max_score": 6,
            }
        ]
        answer_candidates = [
            {
                "question_id": "Q1",
                "raw_question_id": "Q1",
                "question_type": "solution",
                "status": "unseen",
                "score": None,
                "max_score": None,
                "is_correct": None,
                "student_answer_text": None,
                "answer_text": None,
                "steps": [],
                "trace": {},
            }
        ]
        merged = demo_server._merge_and_fill_answers(answer_candidates, question_contexts)
        self.assertEqual(merged[0]["trace"]["reason_code"], "candidate_without_signal")
        self.assertIn("候选区域", merged[0]["trace"]["notes"])

    def test_structured_questions_set_sub_trace_reason_code_from_unmatched_reason(self) -> None:
        questions = [
            {
                "question_id": "Q26",
                "question_type": "solution",
                "sub_questions": [
                    {"sub_question_id": "Q26(1)", "sub_text": "鍏堝寲绠€"},
                ],
            }
        ]
        merged_answers = [
            demo_server._default_answer_item(
                {
                    "question_id": "Q26",
                    "question_type": "solution",
                    "skill_tags": [],
                }
            )
        ]
        structured, _ = demo_server._build_structured_questions_and_mapping_report(
            questions,
            merged_answers,
            [],
            [
                {
                    "question_id": "Q26",
                    "sub_question_id": "Q26(1)",
                    "reason": "question_id_not_in_step1_or_invalid",
                }
            ],
            [],
        )
        self.assertEqual(
            structured[0]["sub_traces"][0]["trace"]["reason_code"],
            "sub_question_unmatched_in_structuring",
        )

    def test_save_answer_trace_debug_json_writes_payload_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            keyword_path = Path(tmp_dir) / "key_word.json"
            keyword_path.write_text(json.dumps({"nodes": []}, ensure_ascii=False), encoding="utf-8")
            service = demo_server.DemoService(Path(tmp_dir) / "llm_config.json", None, keyword_path, mock_mode=True)
            service.answer_trace_debug_output_dir = Path(tmp_dir) / "debug_outputs"
            warnings: list[str] = []
            save_path = service._save_answer_trace_debug_json(
                output_root=None,
                student_id="S1",
                run_token="R1",
                payload={"records": [{"source": "page_1_seg_1", "raw_text": "2x=8"}]},
                warnings=warnings,
            )
            self.assertIsInstance(save_path, str)
            self.assertEqual(warnings, [])
            saved_payload = json.loads(Path(save_path).read_text(encoding="utf-8"))
            self.assertEqual(saved_payload["records"][0]["source"], "page_1_seg_1")
            self.assertEqual(saved_payload["records"][0]["raw_text"], "2x=8")

    def test_answer_trace_postprocess_saves_structuring_debug_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            keyword_path = Path(tmp_dir) / "key_word.json"
            keyword_path.write_text(json.dumps({"nodes": []}, ensure_ascii=False), encoding="utf-8")
            service = demo_server.DemoService(Path(tmp_dir) / "llm_config.json", None, keyword_path, mock_mode=True)
            questions = [
                {
                    "question_id": "Q1",
                    "raw_question_id": "Q1",
                    "question_type": "solution",
                    "skill_tags": [],
                    "answer_page_hint": 0,
                    "max_score": 6,
                }
            ]
            page_raw_items = [
                {
                    "source": "page_1_seg_1",
                    "page_index": 0,
                    "section_name": "sec",
                    "raw_text": "[source=page_1_seg_1 section=sec page=0]\n2x+3=11\n2x=8\nx=4",
                    "context_question_ids": ["Q1"],
                }
            ]
            warnings: list[str] = []
            raw_stage_stats = {
                "answer_trace_debug_dir": str(Path(tmp_dir) / "debug_outputs"),
                "raw_vlm_debug_json_path": str(Path(tmp_dir) / "debug_outputs" / "raw_vlm_outputs.json"),
            }
            with patch.object(service, "_run_harness_stage", return_value={"answers": [{"question_id": "Q1", "status": "answered", "student_answer_text": "2x+3=11\n2x=8\nx=4"}]}):
                raw_answers, _, answer_stats = service._run_answer_trace_postprocess(
                    questions,
                    page_raw_items,
                    warnings,
                    raw_stage_stats=raw_stage_stats,
                )
            self.assertGreaterEqual(len(raw_answers), 1)
            self.assertEqual(warnings, [])
            self.assertIsInstance(answer_stats.get("structuring_debug_json_path"), str)
            self.assertIsInstance(answer_stats.get("alignment_debug_json_path"), str)
            saved_payload = json.loads(Path(answer_stats["structuring_debug_json_path"]).read_text(encoding="utf-8"))
            self.assertEqual(saved_payload["status"], "success")
            self.assertEqual(saved_payload["llm_response"]["answers"][0]["question_id"], "Q1")
            self.assertEqual(saved_payload["normalized_answers"][0]["question_id"], "Q1")
            alignment_payload = json.loads(Path(answer_stats["alignment_debug_json_path"]).read_text(encoding="utf-8"))
            self.assertIn(alignment_payload["status"], {"success", "fallback_to_preliminary"})
            self.assertEqual(alignment_payload["preliminary_answers"][0]["question_id"], "Q1")

    def test_answer_trace_postprocess_splits_structuring_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            keyword_path = Path(tmp_dir) / "key_word.json"
            keyword_path.write_text(json.dumps({"nodes": []}, ensure_ascii=False), encoding="utf-8")
            service = demo_server.DemoService(Path(tmp_dir) / "llm_config.json", None, keyword_path, mock_mode=True)
            service.answer_structuring_chunk_size = 2
            questions = [
                {
                    "question_id": "Q1",
                    "raw_question_id": "Q1",
                    "question_type": "solution",
                    "skill_tags": [],
                    "answer_page_hint": 0,
                    "max_score": 6,
                }
            ]
            page_raw_items = [
                {
                    "source": f"page_1_seg_{i}",
                    "page_index": 0,
                    "section_name": "sec",
                    "raw_text": f"answer text {i}",
                    "context_question_ids": ["Q1"],
                }
                for i in range(5)
            ]
            with patch.object(service, "_run_harness_stage", return_value={"answers": [{"question_id": "Q1", "status": "answered", "student_answer_text": "x=4"}]}):
                _, _, answer_stats = service._run_answer_trace_postprocess(
                    questions,
                    page_raw_items,
                    [],
                    raw_stage_stats={"answer_trace_debug_dir": str(Path(tmp_dir) / "debug_outputs")},
                )
            self.assertEqual(answer_stats["answer_structuring_chunk_count"], 3)


if __name__ == "__main__":
    unittest.main()
