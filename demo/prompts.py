from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from demo.data_utils import _compact_answer_candidates, _compact_profile_answers, _compact_question_contexts, _compact_raw_answer_texts, _compact_skill_graph
from prompt_store import PROFILE_LITERACY_DIMENSIONS, PromptStore


def _paper_prompt(
    knowledge_points: List[Dict[str, Any]],
    *,
    mode: str = "full",
    target_question_ids: Optional[List[str]] = None,
) -> str:
    return PromptStore.paper_prompt(
        knowledge_points,
        mode=mode,
        target_question_ids=target_question_ids,
    )


def _question_anchor_text(question: Dict[str, Any]) -> str:
    for key in ("problem_text", "problem_text_full"):
        value = question.get(key)
        if isinstance(value, str) and value.strip():
            compact = re.sub(r"\s+", " ", value.strip())
            return compact[:80]
    return ""


def _attach_question_metadata(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    order_ids = [
        q.get("question_id")
        for q in questions
        if isinstance(q, dict) and isinstance(q.get("question_id"), str) and q.get("question_id")
    ]
    for idx, question in enumerate(questions):
        if not isinstance(question, dict):
            continue
        item = dict(question)
        qid = item.get("question_id")
        if not isinstance(qid, str) or not qid:
            continue
        item["question_order_index"] = idx
        item["question_anchor_text"] = _question_anchor_text(item)
        neighbors: List[str] = []
        if idx > 0 and isinstance(order_ids[idx - 1], str):
            neighbors.append(order_ids[idx - 1])
        if idx + 1 < len(order_ids) and isinstance(order_ids[idx + 1], str):
            neighbors.append(order_ids[idx + 1])
        item["neighbor_question_ids"] = neighbors
        if not isinstance(item.get("paper_page_index"), int):
            item["paper_page_index"] = 0
        normalized.append(item)
    return normalized


def _route_prompt(question_contexts: List[Dict[str, Any]], page_index: int) -> str:
    return PromptStore.route_prompt(question_contexts, page_index)


def _score_repair_prompt(
    question_contexts: List[Dict[str, Any]],
    candidate_summaries: List[Dict[str, Any]],
    target_question_ids: Optional[List[str]] = None,
) -> str:
    return PromptStore.score_repair_prompt(
        question_contexts,
        candidate_summaries,
        target_question_ids=target_question_ids,
    )


def _knowledge_tag_prompt(
    question_chunk: List[Dict[str, Any]],
    candidate_points: List[Dict[str, Any]],
    knowledge_groups_by_question: List[Dict[str, Any]],
) -> str:
    return PromptStore.knowledge_tag_prompt(question_chunk, candidate_points, knowledge_groups_by_question)


def _knowledge_group_prompt(
    question_chunk: List[Dict[str, Any]],
    candidate_groups: List[Dict[str, Any]],
) -> str:
    return PromptStore.knowledge_group_prompt(question_chunk, candidate_groups)


def _answer_raw_section_prompt(
    question_contexts: List[Dict[str, Any]],
    *,
    page_index: int,
    section_name: str,
    segment_class_name: Optional[str] = None,
) -> str:
    return PromptStore.answer_raw_section_prompt(
        question_contexts,
        page_index=page_index,
        section_name=section_name,
        segment_class_name=segment_class_name,
    )


def _answer_struct_from_raw_texts_prompt(
    question_contexts: List[Dict[str, Any]],
    raw_texts_by_page: List[Dict[str, Any]],
) -> str:
    return PromptStore.answer_struct_from_raw_texts_prompt(
        _compact_question_contexts(question_contexts),
        _compact_raw_answer_texts(raw_texts_by_page),
    )


def _answer_struct_and_align_prompt(
    question_contexts: List[Dict[str, Any]],
    raw_texts_by_page: List[Dict[str, Any]],
) -> str:
    return PromptStore.answer_struct_and_align_prompt(
        _compact_question_contexts(question_contexts),
        _compact_raw_answer_texts(raw_texts_by_page),
    )


def _answer_alignment_prompt(
    question_contexts: List[Dict[str, Any]],
    preliminary_answers: List[Dict[str, Any]],
    raw_texts_by_page: List[Dict[str, Any]],
) -> str:
    return PromptStore.answer_alignment_prompt(
        _compact_question_contexts(question_contexts),
        _compact_answer_candidates(preliminary_answers),
        _compact_raw_answer_texts(raw_texts_by_page),
    )


def _answer_score_sheet_prompt(
    question_contexts: List[Dict[str, Any]],
    candidate_summaries: List[Dict[str, Any]],
) -> str:
    return PromptStore.answer_score_sheet_prompt(
        _compact_question_contexts(question_contexts),
        _compact_answer_candidates(candidate_summaries),
    )


def _reference_answer_extract_prompt(
    question_contexts: List[Dict[str, Any]],
) -> str:
    return PromptStore.reference_answer_extract_prompt(_compact_question_contexts(question_contexts, full_text_limit=1200))


def _reference_answer_generate_prompt(
    question_contexts: List[Dict[str, Any]],
) -> str:
    return PromptStore.reference_answer_generate_prompt(_compact_question_contexts(question_contexts, full_text_limit=1600))


def _answer_key_correctness_prompt(items: List[Dict[str, Any]]) -> str:
    return PromptStore.answer_key_correctness_prompt(items)


def _blind_diagnosis_prompt(items: List[Dict[str, Any]]) -> str:
    return PromptStore.blind_diagnosis_prompt(items)


def _error_analysis_prompt(items: List[Dict[str, Any]]) -> str:
    return PromptStore.error_analysis_prompt(items)


def _profile_prompt(
    student_id: str,
    questions: List[Dict[str, Any]],
    answers: List[Dict[str, Any]],
    graph: Dict[str, Any],
    rule_based_literacy: Optional[List[Dict[str, Any]]] = None,
) -> str:
    compact_questions = _compact_question_contexts(questions, full_text_limit=500)
    compact_answers = _compact_profile_answers(answers)
    compact_graph = _compact_skill_graph(graph, compact_questions, compact_answers)
    return PromptStore.profile_prompt(
        student_id,
        compact_questions,
        compact_answers,
        compact_graph,
        rule_based_literacy,
    )
