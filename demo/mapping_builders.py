from __future__ import annotations

from typing import Any, Dict, List, Optional

from demo.data_utils import _canonical_question_id, _normalize_question_type
from demo.image_utils import _coerce_bbox_xyxy
from demo.prompts import _question_anchor_text


def _build_answer_contexts(questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    contexts: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for q in questions:
        if not isinstance(q, dict):
            continue
        raw = q.get("raw") if isinstance(q.get("raw"), dict) else {}
        qid = q.get("question_id")
        if not isinstance(qid, str):
            continue
        qid = qid.strip()
        if not qid or qid in seen_ids:
            continue
        seen_ids.add(qid)
        qtype = _normalize_question_type(q.get("question_type"))
        tags_raw = q.get("skill_tags")
        tags = [x for x in tags_raw if isinstance(x, str)] if isinstance(tags_raw, list) else []
        problem_text = (
            q.get("problem_text")
            if isinstance(q.get("problem_text"), str)
            else q.get("content")
            if isinstance(q.get("content"), str)
            else raw.get("problem_text")
            if isinstance(raw.get("problem_text"), str)
            else ""
        )
        problem_text_full = (
            q.get("problem_text_full")
            if isinstance(q.get("problem_text_full"), str)
            else raw.get("problem_text_full")
            if isinstance(raw.get("problem_text_full"), str)
            else problem_text
        )
        sub_questions = (
            q.get("sub_questions")
            if isinstance(q.get("sub_questions"), list)
            else raw.get("sub_questions")
            if isinstance(raw.get("sub_questions"), list)
            else []
        )
        question_image_urls = _collect_question_image_urls(q, raw)
        image_refs = _collect_question_image_refs(q, raw)
        contexts.append(
            {
                "question_id": qid,
                "raw_question_id": q.get("raw_question_id") if isinstance(q.get("raw_question_id"), str) else None,
                "question_type": qtype,
                "problem_text": problem_text[:300],
                "problem_text_full": problem_text_full[:2000],
                "sub_questions": sub_questions,
                "skill_tags": tags,
                "max_score": q.get("max_score") if isinstance(q.get("max_score"), (int, float)) else None,
                "paper_page_index": (
                    q.get("paper_page_index")
                    if isinstance(q.get("paper_page_index"), int)
                    else q.get("page_index")
                    if isinstance(q.get("page_index"), int)
                    else 0
                ),
                "question_anchor_text": q.get("question_anchor_text")
                if isinstance(q.get("question_anchor_text"), str)
                else _question_anchor_text(q),
                "neighbor_question_ids": q.get("neighbor_question_ids")
                if isinstance(q.get("neighbor_question_ids"), list)
                else [],
                "question_order_index": q.get("question_order_index")
                if isinstance(q.get("question_order_index"), int)
                else None,
                "answer_page_hint": q.get("answer_page_hint") if isinstance(q.get("answer_page_hint"), int) else None,
                "answer_page_hint_confidence": q.get("answer_page_hint_confidence")
                if isinstance(q.get("answer_page_hint_confidence"), (int, float))
                else None,
                "answer_page_hint_evidence": q.get("answer_page_hint_evidence")
                if isinstance(q.get("answer_page_hint_evidence"), str)
                else None,
                "question_image_urls": question_image_urls,
                "image_refs": image_refs,
            }
        )
    return contexts


def _collect_question_image_urls(question: Dict[str, Any], raw: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    for source in (question.get("question_image_urls"), raw.get("question_image_urls")):
        if isinstance(source, list):
            urls.extend(item.strip() for item in source if isinstance(item, str) and item.strip().startswith("data:image/"))
    for source in (question.get("images"), question.get("question_images"), raw.get("images"), raw.get("question_images")):
        if not isinstance(source, list):
            continue
        for item in source:
            if not isinstance(item, dict):
                continue
            data_url = item.get("data_url")
            if isinstance(data_url, str) and data_url.strip().startswith("data:image/"):
                urls.append(data_url.strip())
    seen: set[str] = set()
    deduped: List[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def _collect_question_image_refs(question: Dict[str, Any], raw: Dict[str, Any]) -> List[str]:
    refs: List[str] = []
    for key in ("image_refs", "images_on_page", "matched_image_ids"):
        for source in (question.get(key), raw.get(key)):
            if isinstance(source, list):
                refs.extend(item.strip() for item in source if isinstance(item, str) and item.strip())
    seen: set[str] = set()
    deduped: List[str] = []
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            deduped.append(ref)
    return deduped


def _build_answer_context_map(question_contexts: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    context_map: Dict[str, Dict[str, Any]] = {}
    for context in question_contexts:
        qid = context.get("question_id")
        if not isinstance(qid, str):
            continue
        raw_qid = qid.strip()
        if not raw_qid:
            continue
        context_map[raw_qid] = context
        canonical = _canonical_question_id(raw_qid)
        if isinstance(canonical, str) and canonical:
            context_map.setdefault(canonical, context)
        raw_from_step1 = context.get("raw_question_id")
        if isinstance(raw_from_step1, str) and raw_from_step1.strip():
            context_map.setdefault(raw_from_step1.strip(), context)
            canonical_from_raw = _canonical_question_id(raw_from_step1)
            if isinstance(canonical_from_raw, str) and canonical_from_raw:
                context_map.setdefault(canonical_from_raw, context)
    return context_map


def _normalize_selected_answer_block_payload(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    source = raw.get("source")
    if not isinstance(source, str) or source not in {"mineru", "project_segmenter"}:
        return None
    page_index = raw.get("page_index")
    if not isinstance(page_index, int) or page_index < 0:
        return None
    bbox_xyxy = _coerce_bbox_xyxy(raw.get("bbox_xyxy"))
    if bbox_xyxy is None:
        return None
    block_id = raw.get("block_id") if isinstance(raw.get("block_id"), str) and raw.get("block_id").strip() else None
    class_name = raw.get("class_name") if isinstance(raw.get("class_name"), str) and raw.get("class_name").strip() else "unknown"
    confidence = raw.get("confidence")
    if not isinstance(confidence, (int, float)):
        confidence = 0.0
    sort_key = raw.get("sort_key")
    return {
        "block_id": block_id or f"{source}_page_{page_index + 1}",
        "source": source,
        "page_index": page_index,
        "bbox_xyxy": bbox_xyxy,
        "class_name": class_name,
        "confidence": max(0.0, min(1.0, float(confidence))),
        "sort_key": sort_key if isinstance(sort_key, str) else f"{page_index:04d}-{bbox_xyxy[1]:06d}-{bbox_xyxy[0]:06d}",
    }


def _sync_mapping_report_pipeline_counters(
    mapping_report: Dict[str, Any],
    *,
    question_pass_chunks: int,
    answer_pass_chunks: int,
    route_pass_chunks: int,
    repair_rounds_used: int,
    repaired_questions_count: int,
    route_hinted_count: int,
) -> Dict[str, Any]:
    mapping_report["question_pass_chunks"] = question_pass_chunks
    mapping_report["answer_pass_chunks"] = answer_pass_chunks
    mapping_report["route_pass_chunks"] = route_pass_chunks
    mapping_report["repair_rounds_used"] = repair_rounds_used
    mapping_report["repaired_questions_count"] = repaired_questions_count
    mapping_report["route_hinted_count"] = route_hinted_count
    return mapping_report

