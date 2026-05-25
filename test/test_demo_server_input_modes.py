from __future__ import annotations

import json
import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

import demo_server


PIXEL_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Ww0x1sAAAAASUVORK5CYII="
)
PDF_DATA_URL = "data:application/pdf;base64,SGVsbG8="


class DemoServerInputModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = demo_server.DemoService(
            Path("llm_config.json"),
            None,
            Path("key_word.json"),
            mock_mode=True,
        )

    def test_answer_slice_plan_adds_full_page_supplement_when_only_subjective_blocks_detected(self) -> None:
        class _SubjectiveOnlySegmenter:
            def segment_file(self, image_path):
                return {
                    "detections": [
                        {
                            "bbox_xyxy": [0, 0, 1, 1],
                            "class_name": "subjective_problem",
                            "confidence": 0.9,
                            "index": 1,
                        }
                    ]
                }

        class _WorkspaceTempDir:
            def __init__(self, prefix: str = "") -> None:
                self.path = Path("outputs") / "test_runtime" / f"{prefix}unit"

            def __enter__(self) -> str:
                self.path.mkdir(parents=True, exist_ok=True)
                return str(self.path)

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

        service = demo_server.DemoService(Path("llm_config.json"), None, Path("key_word.json"), mock_mode=True)
        service.answer_segment_margin_px = 0
        import numpy as np

        with patch.object(service, "_ensure_answer_segmenter", return_value=_SubjectiveOnlySegmenter()), patch(
            "demo.service.tempfile.TemporaryDirectory",
            _WorkspaceTempDir,
        ), patch("demo.service.cv2.imread", return_value=np.zeros((2, 2, 3), dtype=np.uint8)), patch(
            "demo.service.cv2.imencode",
            return_value=(True, np.array([1, 2, 3], dtype=np.uint8)),
        ):
            specs = service._build_answer_slice_plan_for_page(
                page_url=PIXEL_DATA_URL,
                page_index=0,
                answer_contexts=[],
                crop_output_root=None,
                saved_crop_paths=[],
                warnings=[],
            )

        self.assertEqual([spec["segment_class_name"] for spec in specs], ["subjective_problem", "full_page"])
        self.assertEqual(specs[-1]["source"], "page_1_full_supplement")

    def test_validate_input_mode_with_key(self) -> None:
        payload = {
            "student_id": "s1",
            "input_mode": "paper_answer_with_key",
            "paper_files": [{"name": "paper.png", "data_url": PIXEL_DATA_URL}],
            "answer_sheet_files": [{"name": "answer.png", "data_url": PIXEL_DATA_URL}],
            "answer_key_files": [{"name": "key.png", "data_url": PIXEL_DATA_URL}],
        }
        _, mode, paper_urls, answer_urls, answer_key_urls, answer_key_source = self.service._validate_input(payload)
        self.assertEqual(mode, "paper_answer_with_key")
        self.assertEqual(len(paper_urls), 1)
        self.assertEqual(len(answer_urls), 1)
        self.assertEqual(len(answer_key_urls), 1)
        self.assertEqual(answer_key_source, "uploaded")

    def test_validate_input_mode_auto_key(self) -> None:
        payload = {
            "student_id": "s1",
            "input_mode": "paper_answer_auto_key",
            "paper_files": [{"name": "paper.png", "data_url": PIXEL_DATA_URL}],
            "answer_sheet_files": [{"name": "answer.png", "data_url": PIXEL_DATA_URL}],
        }
        _, mode, _, _, answer_key_urls, answer_key_source = self.service._validate_input(payload)
        self.assertEqual(mode, "paper_answer_auto_key")
        self.assertEqual(answer_key_urls, [])
        self.assertEqual(answer_key_source, "generated")

    def test_validate_input_mode_same_page_without_uploaded_key(self) -> None:
        payload = {
            "student_id": "s1",
            "input_mode": "paper_same_page",
            "combined_files": [{"name": "combined.png", "data_url": PIXEL_DATA_URL}],
        }
        _, mode, paper_urls, answer_urls, answer_key_urls, answer_key_source = self.service._validate_input(payload)
        self.assertEqual(mode, "paper_same_page")
        self.assertEqual(len(paper_urls), 1)
        self.assertEqual(paper_urls, answer_urls)
        self.assertEqual(answer_key_urls, [])
        self.assertEqual(answer_key_source, "generated")

    def test_validate_input_rejects_answer_key_for_auto_mode(self) -> None:
        payload = {
            "student_id": "s1",
            "input_mode": "paper_answer_auto_key",
            "paper_files": [{"name": "paper.png", "data_url": PIXEL_DATA_URL}],
            "answer_sheet_files": [{"name": "answer.png", "data_url": PIXEL_DATA_URL}],
            "answer_key_files": [{"name": "key.png", "data_url": PIXEL_DATA_URL}],
        }
        with self.assertRaisesRegex(ValueError, "does not accept answer_key_files"):
            self.service._validate_input(payload)

    def test_validate_input_expands_pdf_file_entries(self) -> None:
        payload = {
            "student_id": "s1",
            "input_mode": "paper_answer_with_key",
            "paper_files": [{"name": "paper.pdf", "data_url": PDF_DATA_URL}],
            "answer_sheet_files": [{"name": "answer.pdf", "data_url": PDF_DATA_URL}],
            "answer_key_files": [{"name": "key.pdf", "data_url": PDF_DATA_URL}],
        }
        fake_pages = [PIXEL_DATA_URL, PIXEL_DATA_URL]
        with patch.object(demo_server._service, "_pdf_bytes_to_image_data_urls", return_value=fake_pages):
            _, _, paper_urls, answer_urls, answer_key_urls, _ = self.service._validate_input(payload)
        self.assertEqual(len(paper_urls), 2)
        self.assertEqual(len(answer_urls), 2)
        self.assertEqual(len(answer_key_urls), 2)

    def test_validate_input_mode_pre_split_questions(self) -> None:
        payload = {
            "student_id": "s1",
            "input_mode": "pre_split_questions",
            "answer_sheet_files": [{"name": "answer.png", "data_url": PIXEL_DATA_URL}],
            "pre_split_questions": [{"question_id": "Q1", "problem_text": "mock"}],
        }
        _, mode, paper_urls, answer_urls, answer_key_urls, answer_key_source = self.service._validate_input(payload)
        self.assertEqual(mode, "pre_split_questions")
        self.assertEqual(paper_urls, [])
        self.assertEqual(len(answer_urls), 1)
        self.assertEqual(answer_key_urls, [])
        self.assertEqual(answer_key_source, "generated")

    def test_validate_input_mode_pre_split_requires_question_list(self) -> None:
        payload = {
            "student_id": "s1",
            "input_mode": "pre_split_questions",
            "answer_sheet_files": [{"name": "answer.png", "data_url": PIXEL_DATA_URL}],
        }
        with self.assertRaisesRegex(ValueError, "requires non-empty pre_split_questions"):
            self.service._validate_input(payload)

    def test_normalize_pre_split_questions_payload(self) -> None:
        questions = self.service._normalize_pre_split_questions_payload(
            {
                "pre_split_questions": [
                    {"question_id": "1", "problem_text": "short"},
                    {"question_id": "Q1", "problem_text_full": "longer text", "question_type": "solution"},
                    {"question_id": "Q2", "problem_text": "q2"},
                ]
            }
        )
        self.assertEqual([item["question_id"] for item in questions], ["Q1", "Q2"])
        self.assertEqual(questions[0]["problem_text_full"], "longer text")

    def test_model_options_are_loaded_from_config_file(self) -> None:
        runtime_dir = Path("outputs") / "test_runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        config_path = runtime_dir / "llm_config_options_test.json"
        config_path.write_text(
            json.dumps(
                {
                    "defaults": {"profile": "vision_custom", "text_profile": "text_custom"},
                    "openai_profiles": {
                        "vision_custom": {
                            "profile_role": "vision",
                            "runtime": "langchain",
                            "provider": "openai_compatible",
                            "base_url": "https://example.com/v1",
                            "model": "vision-model",
                            "api_key_env": "VISION_KEY",
                            "text_profile": "text_custom",
                        },
                        "text_custom": {
                            "profile_role": "text",
                            "runtime": "langchain",
                            "provider": "openai_compatible",
                            "base_url": "https://example.com/v1",
                            "model": "text-model",
                            "api_key_env": "TEXT_KEY",
                        },
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        service = demo_server.DemoService(
            config_path,
            None,
            Path("key_word.json"),
            mock_mode=True,
        )

        options = service.get_model_options()

        self.assertEqual(options["default_vision_profile"], "vision_custom")
        self.assertEqual(options["default_text_profile"], "text_custom")
        self.assertEqual([item["name"] for item in options["vision_profiles"]], ["vision_custom"])
        self.assertEqual([item["name"] for item in options["text_profiles"]], ["text_custom"])
        self.assertEqual(options["vision_profiles"][0]["recommended_text_profile"], "text_custom")

    def test_request_model_selection_applies_runtime_options(self) -> None:
        runtime_dir = Path("outputs") / "test_runtime"
        runtime_dir.mkdir(parents=True, exist_ok=True)
        config_path = runtime_dir / "llm_config_runtime_options_test.json"
        config_path.write_text(
            json.dumps(
                {
                    "defaults": {"profile": "vision_default"},
                    "openai_profiles": {
                        "vision_default": {
                            "profile_role": "vision",
                            "runtime": "langchain",
                            "provider": "openai_compatible",
                            "base_url": "https://example.com/v1",
                            "model": "vision-model",
                            "api_key": "k",
                            "text_profile": "text_fast",
                        },
                        "vision_fast": {
                            "profile_role": "vision",
                            "runtime": "langchain",
                            "provider": "openai_compatible",
                            "base_url": "https://example.com/v1",
                            "model": "vision-fast",
                            "api_key": "k",
                            "text_profile": "text_fast",
                            "question_full_discovery_enabled": False,
                            "answer_trace_save_debug_json": False,
                            "knowledge_tagging_mode": "fast",
                            "profile_mode": "rule_first",
                            "answer_concurrency": 8,
                            "question_chunk_size": 12,
                        },
                        "text_fast": {
                            "profile_role": "text",
                            "runtime": "langchain",
                            "provider": "openai_compatible",
                            "base_url": "https://example.com/v1",
                            "model": "text-fast",
                            "api_key": "k",
                        },
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        service = demo_server.DemoService(config_path, None, Path("key_word.json"), mock_mode=False)
        selection = service._apply_request_model_selection({"vision_profile": "vision_fast"})
        self.assertEqual(selection["vision_profile"], "vision_fast")
        self.assertEqual(selection["text_profile"], "text_fast")
        self.assertFalse(service.question_full_discovery_enabled)
        self.assertFalse(service.answer_trace_save_debug_json)
        self.assertEqual(service.knowledge_tagging_mode, "fast")
        self.assertEqual(service.profile_mode, "rule_first")
        self.assertEqual(service.answer_concurrency, 8)
        self.assertEqual(service.question_chunk_size, 12)

class DemoServerCorrectnessPolicyTests(unittest.TestCase):
    def test_answer_key_correctness_items_include_source_and_teacher_review(self) -> None:
        structured_questions_full = [
            {
                "question_id": "Q1",
                "problem_text_full": "2x=8",
                "answer_trace": {
                    "question_id": "Q1",
                    "student_answer_text": "x=5",
                    "steps": ["2x=8", "x=5"],
                },
                "sub_traces": [],
            }
        ]
        reference_answers = [
            {
                "question_id": "Q1",
                "reference_answer_text": "x=4",
                "reference_final_answer": "x=4",
                "reference_steps": ["2x=8", "x=4"],
            }
        ]
        teacher_review_by_id = {"Q1": {"score": 0, "max_score": 5, "is_correct": False}}

        items = demo_server._build_answer_key_correctness_items(
            structured_questions_full,
            reference_answers,
            reference_source="generated",
            teacher_review_by_id=teacher_review_by_id,
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["reference_source"], "generated")
        self.assertEqual(items[0]["teacher_review"], teacher_review_by_id["Q1"])

    def test_answer_key_correctness_uses_single_sub_reference_for_parent_trace(self) -> None:
        structured_questions_full = [
            {
                "question_id": "Q17",
                "problem_text_full": "solve equation",
                "answer_trace": {
                    "question_id": "Q17",
                    "status": "answered",
                    "student_answer_text": "x=1",
                },
                "sub_traces": [],
            }
        ]
        reference_answers = [
            {
                "question_id": "Q17",
                "sub_question_id": "Q17(1)",
                "reference_answer_text": "x=2",
                "reference_final_answer": "x=2",
                "reference_steps": ["solve"],
            }
        ]

        items = demo_server._build_answer_key_correctness_items(
            structured_questions_full,
            reference_answers,
            reference_source="generated",
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["question_id"], "Q17")
        self.assertIsNone(items[0]["sub_question_id"])
        self.assertEqual(items[0]["reference_final_answer"], "x=2")

    def test_answer_key_correctness_skips_uncertain_generated_reference(self) -> None:
        structured_questions_full = [
            {
                "question_id": "Q7",
                "problem_text_full": "incomplete geometry question",
                "answer_trace": {
                    "question_id": "Q7",
                    "status": "answered",
                    "student_answer_text": "D",
                },
                "sub_traces": [],
            }
        ]
        reference_answers = [
            {
                "question_id": "Q7",
                "reference_answer_text": "题目不完整，无法确定答案。",
                "reference_final_answer": "无法确定",
                "reference_steps": ["题干缺失，无法给出确切答案。"],
            }
        ]

        items = demo_server._build_answer_key_correctness_items(
            structured_questions_full,
            reference_answers,
            reference_source="generated",
        )

        self.assertEqual(items, [])

    def test_answer_key_correctness_deduplicates_parent_sub_trace(self) -> None:
        structured_questions_full = [
            {
                "question_id": "Q26",
                "problem_text_full": "proof question",
                "answer_trace": {
                    "question_id": "Q26",
                    "sub_question_id": "Q26(1)",
                    "status": "answered",
                    "student_answer_text": "parent duplicate",
                },
                "sub_traces": [
                    {
                        "question_id": "Q26",
                        "sub_question_id": "Q26(1)",
                        "status": "answered",
                        "student_answer_text": "sub trace",
                    }
                ],
            }
        ]
        reference_answers = [
            {
                "question_id": "Q26",
                "sub_question_id": "Q26(1)",
                "reference_answer_text": "proof",
                "reference_final_answer": "proved",
                "reference_steps": ["proof"],
            }
        ]

        items = demo_server._build_answer_key_correctness_items(
            structured_questions_full,
            reference_answers,
            reference_source="generated",
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["student_answer_text"], "sub trace")

    def test_answer_key_verdict_overrides_teacher_verdict(self) -> None:
        answers = [
            {
                "question_id": "Q1",
                "status": "answered",
                "score": 4,
                "max_score": 5,
                "is_correct": True,
                "teacher_review": {"score": 4, "max_score": 5, "is_correct": True},
                "diagnosis_validation": {},
            }
        ]
        structured_questions_full = [
            {
                "question_id": "Q1",
                "answer_trace": {
                    "question_id": "Q1",
                    "status": "answered",
                    "score": 4,
                    "max_score": 5,
                    "is_correct": True,
                    "teacher_review": {"score": 4, "max_score": 5, "is_correct": True},
                    "diagnosis_validation": {},
                },
                "sub_traces": [],
            }
        ]
        correctness_items = [
            {
                "question_id": "Q1",
                "sub_question_id": None,
                "by_answer_key": False,
                "confidence": 0.91,
                "reason": "reference answer mismatch",
            }
        ]
        teacher_review_by_id = {"Q1": {"score": 4, "max_score": 5, "is_correct": True}}

        demo_server._apply_answer_key_correctness_policy(
            answers,
            structured_questions_full,
            correctness_items,
            teacher_review_by_id,
        )

        self.assertEqual(answers[0]["is_correct"], False)
        self.assertEqual(answers[0]["score"], 4)
        self.assertEqual(answers[0]["max_score"], 5)
        self.assertEqual(answers[0]["correctness"]["source"], "answer_key")
        self.assertEqual(answers[0]["correctness"]["conflict_with_teacher"], True)
        self.assertEqual(
            answers[0]["diagnosis_validation"]["answer_key_conflict_with_teacher"],
            True,
        )

    def test_generated_answer_key_conflict_keeps_teacher_verdict(self) -> None:
        answers = [
            {
                "question_id": "Q1",
                "status": "answered",
                "is_correct": True,
                "teacher_review": {"deducted_score": 0.0},
                "diagnosis_validation": {},
            }
        ]
        structured_questions_full = [
            {
                "question_id": "Q1",
                "answer_trace": {
                    "question_id": "Q1",
                    "status": "answered",
                    "is_correct": True,
                    "teacher_review": {"deducted_score": 0.0},
                    "diagnosis_validation": {},
                },
                "sub_traces": [],
            }
        ]
        correctness_items = [
            {
                "question_id": "Q1",
                "sub_question_id": None,
                "by_answer_key": False,
                "confidence": 0.95,
                "reason": "generated reference mismatch",
            }
        ]

        demo_server._apply_answer_key_correctness_policy(
            answers,
            structured_questions_full,
            correctness_items,
            {"Q1": {"deducted_score": 0.0}},
            answer_key_source="generated",
        )

        self.assertEqual(answers[0]["is_correct"], True)
        self.assertEqual(answers[0]["correctness"]["source"], "teacher_review_conflict_generated_reference")
        self.assertEqual(answers[0]["correctness"]["conflict_with_teacher"], True)
        self.assertEqual(answers[0]["correctness"]["reference_source"], "generated")


class DemoServerFlowSimplifyTests(unittest.TestCase):
    def setUp(self) -> None:
        for env_name in ("ARK_API_KEY", "DASHSCOPE_API_KEY", "OPENAI_API_KEY", "PACKYAPI_KEY", "GEMINI_API_KEY"):
            os.environ.setdefault(env_name, "test-key")
        self.service = demo_server.DemoService(
            Path("llm_config.json"),
            None,
            Path("key_word.json"),
            mock_mode=False,
        )
        if self.service.profile is None:
            self.service.profile = {"name": "test_profile"}
        if self.service.text_profile is None:
            self.service.text_profile = self.service.profile
        self.service.max_repair_rounds = 1

    def _payload(self) -> dict:
        return {
            "student_id": "s1",
            "input_mode": "paper_answer_with_key",
            "paper_files": [{"name": "paper.png", "data_url": PIXEL_DATA_URL}],
            "answer_sheet_files": [{"name": "answer.png", "data_url": PIXEL_DATA_URL}],
            "answer_key_files": [{"name": "key.png", "data_url": PIXEL_DATA_URL}],
        }

    def test_run_uses_single_mapping_refresh_when_no_repair_targets(self) -> None:
        questions = [
            {
                "question_id": "Q1",
                "question_type": "solution",
                "problem_text": "mock",
                "problem_text_full": "mock",
                "sub_questions": [],
                "skill_tags": [],
            }
        ]
        question_stats = {
            "index_batches_total": 1,
            "index_batches_success": 1,
            "index_batches_failed": 0,
            "question_pass_chunks": 1,
            "question_repair_rounds": 0,
            "repaired_questions_count": 0,
            "paper_parallel_tasks": 1,
        }
        answer_stats = {
            "batches_total": 0,
            "batches_success": 0,
            "batches_failed": 0,
            "objective_pass_chunks": 0,
            "subjective_pass_chunks": 0,
            "answer_parallel_tasks": 0,
            "saved_crop_count": 0,
            "saved_crop_dir": None,
            "answer_block_mode": "auto",
            "plan_build_ms": 0.0,
            "raw_vlm_ms": 0.0,
            "structuring_ms": 0.0,
            "alignment_ms": 0.0,
            "nonempty_raw_text_count": 0,
            "raw_plan_count": 0,
            "structured_answer_count": 0,
            "answer_trace_debug_dir": None,
            "raw_vlm_debug_json_path": None,
            "structuring_debug_json_path": None,
            "alignment_debug_json_path": None,
        }
        mapped_answers = [
            {
                "question_id": "Q1",
                "question_type": "solution",
                "status": "unseen",
                "score": None,
                "max_score": None,
                "is_correct": None,
                "trace": {"confidence": 0.0},
            }
        ]
        structured_questions = [
            {
                "question_id": "Q1",
                "question_type": "solution",
                "problem_text": "mock",
                "problem_text_full": "mock",
                "sub_questions": [],
                "skill_tags": [],
                "answer_trace": {
                    "question_id": "Q1",
                    "status": "unseen",
                    "score": None,
                    "max_score": None,
                    "is_correct": None,
                    "trace": {"confidence": 0.0},
                },
                "sub_traces": [],
            }
        ]
        mapping_report = {
            "total_questions": 1,
            "mapped_questions": 0,
            "missing_from_step1": [],
            "unmatched_traces": [],
            "sub_question_mapped_count": 0,
            "question_pass_chunks": 1,
            "answer_pass_chunks": 0,
            "route_pass_chunks": 0,
            "repair_rounds_used": 0,
            "repaired_questions_count": 0,
            "route_hinted_count": 0,
            "score_conflict_count": 0,
            "score_conflict_question_ids": [],
        }
        profile_payload = {
            "student_id": "s1",
            "mastery": [],
            "error_profile": {},
            "literacy": [],
            "weaknesses": [],
            "summary": "ok",
        }
        with patch.object(
            self.service,
            "_run_question_analysis_parallel",
            return_value=(questions, question_stats, [], 0, 0),
        ), patch.object(
            self.service,
            "_run_answer_raw_trace_parallel",
            return_value=([], answer_stats),
        ), patch.object(
            self.service,
            "_tag_questions_with_text_llm",
            return_value=(
                questions,
                {
                    "question_count": 1,
                    "tagged_question_count": 0,
                    "group_count": 0,
                    "group_pass_chunks": 0,
                    "refine_pass_chunks": 0,
                    "filtered_candidate_count_avg": 0,
                },
            ),
        ), patch.object(
            self.service,
            "_prepare_reference_answers",
            return_value=([], "none"),
        ), patch.object(
            self.service,
            "_ensure_new_points",
            return_value=[],
        ), patch.object(
            self.service,
            "_run_answer_trace_postprocess",
            return_value=([], [], answer_stats),
        ), patch.object(
            self.service,
            "_run_answer_score_recognition",
            return_value=([], {"score_answer_count": 0, "score_scan_ms": 0.0, "score_page_count": 1}),
        ), patch.object(
            self.service,
            "_run_blind_diagnosis",
            return_value=({}, 0),
        ), patch.object(
            self.service,
            "_run_answer_key_correctness",
            return_value=[],
        ), patch.object(
            self.service,
            "_run_harness_stage",
            return_value=profile_payload,
        ), patch.object(
            demo_server._service,
            "_collect_answer_repair_targets",
            return_value=[],
        ), patch.object(
            demo_server._service,
            "_refresh_answer_mapping",
            return_value=(mapped_answers, structured_questions, mapping_report),
        ) as refresh_mock:
            result = self.service.run(self._payload())

        self.assertEqual(refresh_mock.call_count, 1)
        self.assertEqual(result["mapping_report"]["repair_rounds_used"], 0)
        self.assertEqual(result["mapping_report"]["repaired_questions_count"], 0)

    def test_reference_answer_extract_and_generate_share_same_normalization(self) -> None:
        answer_contexts = [
            {
                "question_id": "Q1",
                "question_type": "solution",
                "problem_text": "mock",
                "problem_text_full": "mock",
                "sub_questions": [],
            }
        ]
        llm_payload = {
            "reference_answers": [
                {
                    "question_id": "Q1",
                    "reference_answer_text": "x=4",
                    "reference_final_answer": "x=4",
                    "reference_steps": ["2x=8", "x=4"],
                    "confidence": 0.9,
                    "reason": "mock",
                }
            ]
        }
        with patch.object(self.service, "_run_harness_stage", return_value=llm_payload):
            extracted = self.service._run_reference_answer_extract(
                answer_key_urls=[PIXEL_DATA_URL],
                answer_contexts=answer_contexts,
                warnings=[],
            )
            generated = self.service._run_reference_answer_generate(
                answer_contexts=answer_contexts,
                warnings=[],
            )
        self.assertEqual(extracted[0]["source"], "uploaded")
        self.assertEqual(generated[0]["source"], "generated")
        extracted_payload = dict(extracted[0])
        generated_payload = dict(generated[0])
        extracted_payload.pop("source")
        generated_payload.pop("source")
        self.assertEqual(extracted_payload, generated_payload)

    def test_answer_repair_retries_single_target_after_json_failure(self) -> None:
        target_ids = ["Q7", "Q22", "Q23"]
        questions = [
            {
                "question_id": qid,
                "question_type": "objective",
                "problem_text": f"question {qid}",
                "problem_text_full": f"question {qid}",
                "sub_questions": [],
                "skill_tags": [],
                "paper_page_index": 0,
            }
            for qid in target_ids
        ]
        answer_context_map = {
            qid: {
                "question_id": qid,
                "question_type": "objective",
                "sub_questions": [],
                "skill_tags": [],
                "answer_page_hint": 0,
            }
            for qid in target_ids
        }

        self.service.answer_concurrency = 1
        self.service.score_chunk_size = len(target_ids)

        def _fake_repair_call(profile, *, prompt, data_urls, max_tokens=None, expected_list_key=None, **kwargs):
            match = re.search(r"target_question_ids=(\[.*?\])", prompt, flags=re.S)
            current_ids = json.loads(match.group(1)) if match else []
            if len(current_ids) > 1:
                raise ValueError('LangChain did not return valid JSON object (preview={"answers":[{"question_id":"Q7"')
            qid = current_ids[0]
            return {
                "answers": [
                    {
                        "question_id": qid,
                        "status": "answered",
                        "student_answer_text": "mock answer",
                        "confidence": 0.9,
                    }
                ]
            }

        with patch.object(self.service, "_call_json_with_profile", side_effect=_fake_repair_call) as call_mock:
            result = self.service._run_answer_repair_round_parallel(
                repair_targets=target_ids,
                questions=questions,
                answer_urls=[PIXEL_DATA_URL],
                raw_answers=[],
                answer_context_map=answer_context_map,
            )

        repaired_ids = {item.get("question_id") for item in result["raw_answers"] if isinstance(item, dict)}
        self.assertEqual(repaired_ids, set(target_ids))
        self.assertEqual(result["pass_chunks"], 1)
        self.assertGreaterEqual(call_mock.call_count, 4)
        self.assertTrue(any("answer_repair failed" in item for item in result["warnings"]))
        self.assertFalse(any("retry failed" in item for item in result["warnings"]))

    def test_question_analysis_full_discovery_adds_questions_missed_by_index(self) -> None:
        self.service.max_repair_rounds = 0
        self.service.question_full_discovery_enabled = True
        paper_urls = ["page_1", "page_2"]

        def _fake_stage_call(spec, *, prompt, data_urls, profile=None, **kwargs):
            page = data_urls[0] if data_urls else ""
            if "target_question_ids=" not in prompt:
                if page == "page_1":
                    return {"questions": [{"question_id": "1", "problem_text": "q1"}]}
                return {"questions": []}
            if "target_question_ids=[]" in prompt:
                if page == "page_1":
                    return {"questions": [{"question_id": "Q1", "problem_text": "q1"}]}
                return {"questions": [{"question_id": "第十二题", "problem_text": "q12"}]}
            return {"questions": []}

        with patch.object(self.service, "_run_harness_stage", side_effect=_fake_stage_call):
            questions, stats, missing_from_step1, repair_rounds, repaired_count = self.service._run_question_analysis_parallel(
                paper_urls,
                [],
                [],
            )

        detected_ids = {item.get("question_id") for item in questions if isinstance(item, dict)}
        self.assertIn("Q1", detected_ids)
        self.assertIn("Q12", detected_ids)
        self.assertEqual(stats["index_batches_total"], 2)
        self.assertEqual(stats["index_batches_success"], 2)
        self.assertEqual(repair_rounds, 0)
        self.assertEqual(repaired_count, 0)
        self.assertIsInstance(missing_from_step1, list)

    def test_normalize_question_item_accepts_chinese_and_numeric_question_ids(self) -> None:
        from demo_server import _normalize_question_item

        first = _normalize_question_item({"question_id": "第十二题", "problem_text": "q12"})
        second = _normalize_question_item({"question_id": 7, "problem_text": "q7"})
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first["question_id"], "Q12")
        self.assertEqual(second["question_id"], "Q7")


if __name__ == "__main__":
    unittest.main()
