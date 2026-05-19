from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import demo_server


class AnswerBlockWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = demo_server.DemoService(
            Path("llm_config.json"),
            None,
            Path("key_word.json"),
            mock_mode=True,
        )

    def _base_payload(self) -> dict:
        pixel = (
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Ww0x1sAAAAASUVORK5CYII="
        )
        return {
            "student_id": "41201200",
            "input_mode": "paper_answer_with_key",
            "paper_files": [{"name": "paper.png", "data_url": pixel}],
            "answer_sheet_files": [
                {"name": "front.png", "data_url": pixel},
                {"name": "back.png", "data_url": pixel},
            ],
            "answer_key_files": [{"name": "answer_key.png", "data_url": pixel}],
        }

    def test_empty_selected_blocks_rejected(self) -> None:
        payload = self._base_payload()
        payload["selected_answer_blocks"] = []
        with self.assertRaisesRegex(ValueError, "请至少选择一个题块后再识别"):
            self.service.run(payload)

    def test_mock_run_sets_manual_block_summary(self) -> None:
        payload = self._base_payload()
        payload["selected_answer_blocks"] = [
            {
                "block_id": "mineru_p1_001",
                "source": "mineru",
                "page_index": 0,
                "bbox_xyxy": [10, 20, 110, 220],
                "class_name": "subjective_problem",
                "confidence": 0.9,
            },
            {
                "block_id": "project_segmenter_p2_001",
                "source": "project_segmenter",
                "page_index": 1,
                "bbox_xyxy": [15, 25, 115, 225],
                "class_name": "fillin_problem",
                "confidence": 0.8,
            },
        ]
        result = self.service.run(payload)
        mapping_report = result["mapping_report"]
        self.assertEqual(mapping_report["answer_block_mode"], "manual_confirmed")
        self.assertEqual(mapping_report["manual_block_count"], 2)
        self.assertEqual(mapping_report["mineru_selected_count"], 1)
        self.assertEqual(mapping_report["refine_selected_count"], 1)
        summary = result["selected_answer_blocks_summary"]
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["source_counts"]["mineru"], 1)
        self.assertEqual(summary["source_counts"]["project_segmenter"], 1)

    def test_overlap_filter_removes_duplicate_candidate(self) -> None:
        accepted = [
            {
                "block_id": "mineru_p1_001",
                "source": "mineru",
                "page_index": 0,
                "bbox_xyxy": [10, 10, 110, 110],
                "class_name": "subjective_problem",
                "confidence": 0.9,
                "sort_key": "0000-000010-000010",
            }
        ]
        candidates = [
            {
                "block_id": "project_segmenter_p1_001",
                "source": "project_segmenter",
                "page_index": 0,
                "bbox_xyxy": [12, 12, 108, 108],
                "class_name": "subjective_problem",
                "confidence": 0.8,
                "sort_key": "0000-000012-000012",
            },
            {
                "block_id": "project_segmenter_p1_002",
                "source": "project_segmenter",
                "page_index": 0,
                "bbox_xyxy": [140, 140, 200, 220],
                "class_name": "fillin_problem",
                "confidence": 0.7,
                "sort_key": "0000-000140-000140",
            },
        ]
        filtered = self.service._filter_overlapping_candidates(candidates, accepted, iou_threshold=0.6)
        self.assertEqual([item["block_id"] for item in filtered], ["project_segmenter_p1_002"])

    def test_request_summary_includes_selected_block_counts(self) -> None:
        payload = self._base_payload()
        payload["selected_answer_blocks"] = [
            {
                "block_id": "mineru_p1_001",
                "source": "mineru",
                "page_index": 0,
                "bbox_xyxy": [10, 20, 110, 220],
                "class_name": "subjective_problem",
                "confidence": 0.9,
            }
        ]
        summary = demo_server._build_request_summary(payload)
        self.assertEqual(summary["selected_answer_block_count"], 1)
        self.assertEqual(summary["selected_answer_block_source_counts"]["mineru"], 1)

    def test_extract_mineru_content_list_candidates(self) -> None:
        bundle = {
            "content_list": [
                {
                    "type": "text",
                    "bbox": [100, 200, 900, 800],
                    "page_idx": 0,
                    "score": 0.85,
                },
                {
                    "type": "header",
                    "bbox": [0, 0, 1000, 80],
                    "page_idx": 0,
                    "score": 1.0,
                },
            ]
        }
        result = self.service._extract_mineru_candidate_specs(bundle, width=500, height=1000)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["bbox_xyxy"], [50, 200, 450, 800])
        self.assertEqual(result[0]["class_name"], "subjective_problem")

    def test_extract_mineru_model_unit_bbox_candidates(self) -> None:
        bundle = {
            "model": [
                [
                    {
                        "type": "equation",
                        "bbox": [0.1, 0.2, 0.9, 0.4],
                        "score": 0.72,
                    }
                ]
            ]
        }
        result = self.service._extract_mineru_candidate_specs(bundle, width=400, height=600)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["bbox_xyxy"], [40, 120, 360, 240])
        self.assertEqual(result[0]["class_name"], "fillin_problem")

    def test_dedupe_mineru_candidate_specs_removes_near_duplicates(self) -> None:
        specs = [
            {
                "bbox_xyxy": [10, 10, 210, 210],
                "class_name": "subjective_problem",
                "confidence": 0.91,
            },
            {
                "bbox_xyxy": [14, 14, 206, 206],
                "class_name": "subjective_problem",
                "confidence": 0.84,
            },
            {
                "bbox_xyxy": [260, 40, 360, 180],
                "class_name": "subjective_problem",
                "confidence": 0.73,
            },
            {
                "bbox_xyxy": [12, 12, 208, 208],
                "class_name": "fillin_problem",
                "confidence": 0.88,
            },
        ]
        result = self.service._dedupe_mineru_candidate_specs(specs, iou_threshold=0.85)
        self.assertEqual(len(result), 3)
        self.assertIn([10, 10, 210, 210], [item["bbox_xyxy"] for item in result])
        self.assertIn([260, 40, 360, 180], [item["bbox_xyxy"] for item in result])
        self.assertIn([12, 12, 208, 208], [item["bbox_xyxy"] for item in result])

    def test_select_segment_contexts_adds_blank_fallback_for_subjective(self) -> None:
        answer_contexts = [
            {"question_id": "Q1", "question_type": "blank", "answer_page_hint": 0, "answer_page_hint_confidence": 0.9},
            {"question_id": "Q2", "question_type": "solution", "answer_page_hint": 0, "answer_page_hint_confidence": 0.9},
        ]
        choice_contexts = []
        blank_contexts = [answer_contexts[0]]
        solution_contexts = [answer_contexts[1]]
        result = demo_server._select_segment_contexts(
            page_index=0,
            class_name="subjective_problem",
            answer_contexts=answer_contexts,
            choice_contexts=choice_contexts,
            blank_contexts=blank_contexts,
            solution_contexts=solution_contexts,
            allow_blank_fallback_for_subjective=True,
        )
        self.assertEqual([item["question_id"] for item in result], ["Q1", "Q2"])

    def test_select_segment_contexts_keeps_subjective_only_without_blank_fallback(self) -> None:
        answer_contexts = [
            {"question_id": "Q1", "question_type": "blank", "answer_page_hint": 0, "answer_page_hint_confidence": 0.9},
            {"question_id": "Q2", "question_type": "solution", "answer_page_hint": 0, "answer_page_hint_confidence": 0.9},
        ]
        result = demo_server._select_segment_contexts(
            page_index=0,
            class_name="subjective_problem",
            answer_contexts=answer_contexts,
            choice_contexts=[],
            blank_contexts=[answer_contexts[0]],
            solution_contexts=[answer_contexts[1]],
            allow_blank_fallback_for_subjective=False,
        )
        self.assertEqual([item["question_id"] for item in result], ["Q2"])

    def test_select_manual_block_contexts_ignores_selected_block_class(self) -> None:
        answer_contexts = [
            {"question_id": "Q1", "question_type": "blank", "answer_page_hint": 0, "answer_page_hint_confidence": 0.9},
            {"question_id": "Q2", "question_type": "solution", "answer_page_hint": 0, "answer_page_hint_confidence": 0.9},
            {"question_id": "Q3", "question_type": "choice", "answer_page_hint": 1, "answer_page_hint_confidence": 0.9},
        ]
        result = demo_server._select_manual_block_contexts(page_index=0, answer_contexts=answer_contexts)
        self.assertEqual([item["question_id"] for item in result], ["Q1", "Q2"])

    def test_build_knowledge_groups_uses_id_prefix_layers(self) -> None:
        candidate_points = [
            {"id": "algebra.formula.expand_distribute", "name": "代数展开", "type": "method"},
            {"id": "algebra.formula.identity.square_sum", "name": "完全平方公式", "type": "formula"},
            {"id": "geometry.triangle.congruence", "name": "三角形全等", "type": "theorem"},
        ]
        groups = demo_server._build_knowledge_groups(candidate_points)
        self.assertEqual([item["group_id"] for item in groups], ["algebra.formula", "geometry.triangle"])
        self.assertEqual(groups[0]["point_count"], 2)

    def test_filter_candidate_points_by_selected_groups(self) -> None:
        candidate_points = [
            {"id": "algebra.formula.expand_distribute", "name": "代数展开", "type": "method"},
            {"id": "algebra.method.factor", "name": "因式分解", "type": "method"},
            {"id": "geometry.triangle.congruence", "name": "三角形全等", "type": "theorem"},
        ]
        selected = [{"question_id": "Q1", "knowledge_groups": ["algebra.formula"]}]
        filtered = demo_server._filter_candidate_points_by_groups(candidate_points, selected)
        self.assertEqual([item["id"] for item in filtered], ["algebra.formula.expand_distribute"])

    def test_build_mineru_segment_preview_only_uses_first_answer_sheet_page(self) -> None:
        payload = self._base_payload()
        seen_urls = []

        def fake_build(urls):
            seen_urls.append(list(urls))
            return [], []

        with patch.object(self.service, "_build_mineru_candidates", side_effect=fake_build):
            result = self.service.build_mineru_segment_preview(payload)
        self.assertEqual(len(seen_urls), 1)
        self.assertEqual(len(seen_urls[0]), 1)
        self.assertEqual(result["pages"], [{"page_index": 0, "candidates": []}])


if __name__ == "__main__":
    unittest.main()
