from __future__ import annotations

import argparse
import ast
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
import json
import re
import tempfile
import warnings
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from llm_knowledge_tagger import (
    _content_to_text,
    _extract_json_text,
    _extract_points_from_nodes,
    _load_key_word_payload,
    _load_llm_profile,
    _loads_json_like,
    _post_with_retry,
    _strip_code_fences,
    call_llm_with_images,
)

from agent_harness import AgentHarness, HarnessStageSpec
from demo.stage_contracts import expected_list_key, response_contract
from demo.http_utils import _terminal_log
from demo.stages.new_knowledge_points import _new_point_prompt
from demo.export_builders import _build_export_payload, _build_export_pdf_bytes, _build_request_summary, _pdf_safe_text, _pdf_wrap_lines

from demo.mapping_builders import (
    _build_answer_contexts,
    _build_answer_context_map,
    _normalize_selected_answer_block_payload,
    _sync_mapping_report_pipeline_counters,
)

from demo.profile_builders import (
    _normalize_profile_payload,
    _build_rule_based_literacy_profile,
    _build_mock_exam_questions,
    _mock_localize_skill_name,
    _mock_localize_skill_tags,
    _mock_localize_skill_payload,
)

from demo.prompts import (
    _paper_prompt,
    _question_anchor_text,
    _attach_question_metadata,
    _route_prompt,
    _score_repair_prompt,
    _knowledge_tag_prompt,
    _knowledge_group_prompt,
    _answer_raw_section_prompt,
    _answer_struct_from_raw_texts_prompt,
    _answer_struct_and_align_prompt,
    _answer_alignment_prompt,
    _answer_score_sheet_prompt,
    _reference_answer_extract_prompt,
    _reference_answer_generate_prompt,
    _answer_key_correctness_prompt,
    _blind_diagnosis_prompt,
    _error_analysis_prompt,
    _profile_prompt,
)
from demo.data_utils import (
    _as_bool,
    _coerce_optional_bool,
    _first_present,
    _coerce_confidence,
    _coerce_optional_number,
    _build_chat_completions_url,
    _is_choice_or_blank,
    _strip_ellipsis_text,
    _normalize_question_type,
    _now_iso,
    _extract_file_names,
    _skill_group_id,
    _chunk_list,
    _compact_answer_candidates,
    _compact_raw_answer_texts,
    _compact_sub_questions,
    _compact_text,
    _compact_profile_answers,
    _compact_question_contexts,
    _compact_skill_graph,
    _count_blocks_by_source,
    _compact_steps,
    _extract_main_and_sub_ids,
    _canonical_question_id,
    _canonical_sub_question_id,
    _mapping_pattern_matches,
    _pick_questions_by_ids,
    _question_literacy_signal,
    _question_sort_key,
    _is_choice_question_type,
    _answer_confidence,
    _has_answer_signal,
    _normalize_merge_text,
)

from demo.image_utils import (
    _DATA_URL_PATTERN,
    _bbox_iou,
    _clip_bbox_xyxy,
    _coerce_bbox_xyxy,
    _decode_data_url_payload,
    _decode_image_data_url,
    _image_bytes_to_data_url,
    _image_suffix_from_mime,
    _mask_red_review_marks_data_url,
    _pdf_bytes_to_image_data_urls,
)
from demo.json_utils import (
    _extract_json_array_text,
    _is_llm_json_payload_error,
    _loads_json_list_like,
    _loads_json_object_like,
    _normalize_expected_list_payload,
    _normalize_llm_json_payload,
    _safe_literal_eval,
)
from prompt_store import PROFILE_LITERACY_DIMENSIONS, PromptStore
from mineru_client import MinerUStandardClient
from langchain_runtime import (
    LangChainAgentRuntime,
    _is_unsupported_json_response_format_error,
    is_langchain_available,
)
try:
    import numpy as np
except Exception as exc:  # pragma: no cover - optional runtime dependency
    np = None  # type: ignore[assignment]
    _NUMPY_IMPORT_ERROR = str(exc)
else:
    _NUMPY_IMPORT_ERROR = ""
try:
    import cv2
except Exception as exc:  # pragma: no cover - optional runtime dependency
    cv2 = None  # type: ignore[assignment]
    _CV2_IMPORT_ERROR = str(exc)
else:
    _CV2_IMPORT_ERROR = ""
try:
    import fitz  # type: ignore[import-not-found]
except Exception as exc:  # pragma: no cover - optional runtime dependency
    fitz = None  # type: ignore[assignment]
    _PYMUPDF_IMPORT_ERROR = str(exc)
else:
    _PYMUPDF_IMPORT_ERROR = ""

try:
    from major_seg_tool import BigQuestionSegmenter
except Exception as exc:  # pragma: no cover - optional runtime dependency
    BigQuestionSegmenter = None  # type: ignore[assignment]
    _MAJOR_SEG_IMPORT_ERROR = str(exc)
else:
    _MAJOR_SEG_IMPORT_ERROR = ""

try:
    from temporal_analysis_demo import run_temporal_demo
except Exception as exc:  # pragma: no cover - runtime dependency check
    run_temporal_demo = None  # type: ignore[assignment]
    _TEMPORAL_IMPORT_ERROR = str(exc)
else:
    _TEMPORAL_IMPORT_ERROR = ""

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas as reportlab_canvas
except Exception as exc:  # pragma: no cover - optional runtime dependency
    A4 = None  # type: ignore[assignment]
    pdfmetrics = None  # type: ignore[assignment]
    UnicodeCIDFont = None  # type: ignore[assignment]
    reportlab_canvas = None  # type: ignore[assignment]
    _REPORTLAB_IMPORT_ERROR = str(exc)
else:
    _REPORTLAB_IMPORT_ERROR = ""


def _load_literacy_mapping_payload(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else {}


def _read_llm_config_payload(config_path: Path) -> Dict[str, Any]:
    if not config_path.exists():
        raise ValueError(f"LLM config not found: {config_path}")
    payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("LLM config must be a JSON object")
    profiles = payload.get("openai_profiles")
    if profiles is None:
        payload["openai_profiles"] = {}
    elif not isinstance(profiles, dict):
        raise ValueError("Invalid LLM config: openai_profiles must be an object")
    defaults = payload.get("defaults")
    if defaults is None:
        payload["defaults"] = {}
    elif not isinstance(defaults, dict):
        raise ValueError("Invalid LLM config: defaults must be an object")
    return payload


def _call_llm_json(
    *,
    base_url: str,
    api_key: str,
    model: str,
    provider: str = "openai_compatible",
    prompt: str,
    data_urls: List[str],
    timeout: int = 120,
    max_retries: int = 2,
    backoff_base_sec: float = 1.5,
    min_interval_sec: float = 0.0,
    max_tokens: int = 600,
    use_env_proxy: bool = True,
    enable_thinking: bool = False,
    thinking: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
    detail: Optional[str] = None,
    image_pixel_limit: Optional[Dict[str, Any]] = None,
    expected_list_key: Optional[str] = None,
) -> Dict[str, Any]:
    provider_key = provider.strip().lower() if isinstance(provider, str) else "openai_compatible"
    if provider_key == "openai_compatible":
        url = _build_chat_completions_url(base_url)
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        detail_mode = str(detail).strip().lower() if isinstance(detail, str) else None
        for data_url in data_urls:
            image_obj: Dict[str, Any] = {"url": data_url}
            if detail_mode in {"auto", "low", "high", "xhigh"}:
                image_obj["detail"] = detail_mode
            content.append({"type": "image_url", "image_url": image_obj})
        payload: Dict[str, Any] = {
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": "You are a strict JSON generator."},
                {"role": "user", "content": content},
            ],
            "response_format": {"type": "json_object"},
            "enable_thinking": bool(enable_thinking),
        }
        if max_tokens > 0:
            payload["max_tokens"] = max_tokens

        def _invoke_openai_json(request_payload: Dict[str, Any]) -> Dict[str, Any]:
            response = _post_with_retry(
                url,
                headers,
                request_payload,
                timeout,
                max_retries=max_retries,
                backoff_base_sec=backoff_base_sec,
                min_interval_sec=min_interval_sec,
                use_env_proxy=use_env_proxy,
            )
            return response.json()

        try:
            raw = _invoke_openai_json(payload)
        except Exception as exc:
            if _is_unsupported_json_response_format_error(exc):
                fallback_payload = dict(payload)
                fallback_payload.pop("response_format", None)
                raw = _invoke_openai_json(fallback_payload)
            else:
                raise
    else:
        raw = call_llm_with_images(
            prompt=prompt,
            data_urls=data_urls,
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=timeout,
            max_retries=max_retries,
            backoff_base_sec=backoff_base_sec,
            min_interval_sec=min_interval_sec,
        use_env_proxy=use_env_proxy,
        enable_thinking=enable_thinking,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
        detail=detail,
        image_pixel_limit=image_pixel_limit,
        provider=provider,
        max_tokens=max_tokens,
        json_mode=True,
        )
    choices = raw.get("choices", [])
    if not choices:
        raise ValueError("LLM response missing choices")
    first_choice = choices[0] if isinstance(choices[0], dict) else {}
    msg = first_choice.get("message", {}) if isinstance(first_choice.get("message", {}), dict) else {}
    text = _content_to_text(msg.get("content", ""))
    data = _normalize_llm_json_payload(text, expected_list_key=expected_list_key)
    if not isinstance(data, dict):
        tool_calls = msg.get("tool_calls", [])
        if isinstance(tool_calls, list) and tool_calls:
            first_tool = tool_calls[0] if isinstance(tool_calls[0], dict) else {}
            fn = first_tool.get("function", {}) if isinstance(first_tool.get("function", {}), dict) else {}
            args = fn.get("arguments")
            if isinstance(args, str):
                parsed_args = _normalize_llm_json_payload(args, expected_list_key=expected_list_key)
                if isinstance(parsed_args, dict):
                    return parsed_args
        finish_reason = first_choice.get("finish_reason")
        preview = text.strip()[:300] if isinstance(text, str) else ""
        raise ValueError(
            f"LLM did not return valid JSON object (finish_reason={finish_reason}, preview={preview})"
        )
    return data


def _call_llm_text(
    *,
    base_url: str,
    api_key: str,
    model: str,
    provider: str = "openai_compatible",
    prompt: str,
    data_urls: List[str],
    timeout: int = 120,
    max_retries: int = 2,
    backoff_base_sec: float = 1.5,
    min_interval_sec: float = 0.0,
    max_tokens: int = 600,
    use_env_proxy: bool = True,
    enable_thinking: bool = False,
    thinking: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
    detail: Optional[str] = None,
    image_pixel_limit: Optional[Dict[str, Any]] = None,
) -> str:
    raw = call_llm_with_images(
        prompt=prompt,
        data_urls=data_urls,
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout=timeout,
        max_retries=max_retries,
        backoff_base_sec=backoff_base_sec,
        min_interval_sec=min_interval_sec,
        use_env_proxy=use_env_proxy,
        enable_thinking=enable_thinking,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
        detail=detail,
        image_pixel_limit=image_pixel_limit,
        provider=provider,
        max_tokens=max_tokens,
        json_mode=False,
    )
    choices = raw.get("choices", [])
    if not choices:
        raise ValueError("LLM response missing choices")
    first_choice = choices[0] if isinstance(choices[0], dict) else {}
    msg = first_choice.get("message", {}) if isinstance(first_choice.get("message", {}), dict) else {}
    text = _content_to_text(msg.get("content", ""))
    if isinstance(text, str) and text.strip():
        return text.strip()
    finish_reason = first_choice.get("finish_reason")
    raise ValueError(f"LLM returned empty text (finish_reason={finish_reason})")


def _looks_like_solution_step(text: str) -> bool:
    if not isinstance(text, str):
        return False
    compact = text.strip()
    if not compact:
        return False
    if len(compact) <= 1:
        return False
    return bool(
        re.search(r"[=+\-*/^<>]", compact)
        or re.search(r"\d", compact)
        or re.search(r"[A-Za-z]", compact)
        or ("→" in compact)
        or ("⇒" in compact)
        or ("得" in compact and len(compact) <= 20)
    )


def _normalize_steps_list(raw_steps: Any) -> List[str]:
    if isinstance(raw_steps, list):
        normalized: List[str] = []
        for step in raw_steps:
            cleaned = _strip_ellipsis_text(step)
            if isinstance(cleaned, str) and cleaned:
                normalized.append(cleaned)
        return normalized
    if isinstance(raw_steps, str):
        text = raw_steps.strip()
        if not text:
            return []
        parts = re.split(r"(?:\r?\n+|->|=>|⇒|→|；|;)", text)
        normalized = []
        for part in parts:
            cleaned = _strip_ellipsis_text(part)
            if isinstance(cleaned, str) and cleaned:
                normalized.append(cleaned)
        return normalized
    return []


def _infer_steps_from_answer_text(student_answer_text: Optional[str], answer_text: Optional[str]) -> List[str]:
    source_text = ""
    if isinstance(student_answer_text, str) and student_answer_text.strip():
        source_text = student_answer_text.strip()
    elif isinstance(answer_text, str) and answer_text.strip():
        source_text = answer_text.strip()
    if not source_text:
        return []
    if "\n" in source_text:
        parts = [part.strip() for part in re.split(r"\r?\n+", source_text) if part.strip()]
    else:
        parts = [part.strip() for part in re.split(r"(?:->|=>|⇒|→|；|;)", source_text) if part.strip()]
    steps = []
    for part in parts:
        cleaned = _strip_ellipsis_text(part)
        if isinstance(cleaned, str) and cleaned and _looks_like_solution_step(cleaned):
            steps.append(cleaned)
    if len(steps) >= 2:
        return steps
    return []


def _strip_raw_text_source_header(raw_text: Any) -> Optional[str]:
    if not isinstance(raw_text, str):
        return None
    text = raw_text.strip()
    if not text:
        return None
    text = re.sub(r"^\[source=.*?\]\s*", "", text, count=1, flags=re.S)
    text = text.strip()
    return text or None


def _is_useful_raw_text_fallback(raw_text: Optional[str]) -> bool:
    if not isinstance(raw_text, str):
        return False
    text = raw_text.strip()
    if not text:
        return False
    lowered = text.lower()
    if lowered in {"本区域无候选题号", "[未识别]"}:
        return False
    if re.fullmatch(r"(?:\[未识别\]\s*)+", text):
        return False
    return True


def _extract_sub_index(sub_question_id: Any) -> Optional[str]:
    if not isinstance(sub_question_id, str):
        return None
    match = re.search(r"[\(（](\d+)[\)）]$", sub_question_id.strip())
    if match:
        return match.group(1)
    return None


def _split_parent_steps_to_sub_traces(
    question: Dict[str, Any],
    answer_trace: Dict[str, Any],
    sub_entries: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not isinstance(answer_trace, dict) or not isinstance(sub_entries, list) or not sub_entries:
        return sub_entries
    parent_steps = answer_trace.get("steps") if isinstance(answer_trace.get("steps"), list) else []
    parent_steps = [step for step in parent_steps if isinstance(step, str) and step.strip()]
    if not parent_steps:
        return sub_entries
    if not any(not (isinstance(sub.get("steps"), list) and sub.get("steps")) for sub in sub_entries if isinstance(sub, dict)):
        return sub_entries

    assigned: Dict[str, List[str]] = {
        sub.get("sub_question_id"): []
        for sub in sub_entries
        if isinstance(sub, dict) and isinstance(sub.get("sub_question_id"), str)
    }
    unmatched_steps: List[str] = []
    for step in parent_steps:
        step_text = step.strip()
        matched_sub_id: Optional[str] = None
        for sub in sub_entries:
            if not isinstance(sub, dict):
                continue
            sub_id = sub.get("sub_question_id") if isinstance(sub.get("sub_question_id"), str) else None
            if not isinstance(sub_id, str):
                continue
            sub_index = _extract_sub_index(sub_id)
            sub_text = sub.get("sub_question_text") if isinstance(sub.get("sub_question_text"), str) else None
            if isinstance(sub_index, str) and re.search(
                rf"(?:^|[\s])(?:第{re.escape(sub_index)}(?:小题|题|步)?|[\(（]{re.escape(sub_index)}[\)）]|{re.escape(sub_index)}[、.)）:：-])",
                step_text,
            ):
                matched_sub_id = sub_id
                break
            if isinstance(sub_text, str) and sub_text.strip():
                anchor = re.sub(r"\s+", "", sub_text.strip())[:8]
                compact_step = re.sub(r"\s+", "", step_text)
                if anchor and anchor in compact_step:
                    matched_sub_id = sub_id
                    break
        if matched_sub_id is None:
            unmatched_steps.append(step_text)
        else:
            assigned.setdefault(matched_sub_id, []).append(step_text)

    empty_subs = [
        sub for sub in sub_entries
        if isinstance(sub, dict)
        and isinstance(sub.get("sub_question_id"), str)
        and not assigned.get(sub.get("sub_question_id"))
    ]
    empty_subs.sort(
        key=lambda sub: (
            int(_extract_sub_index(sub.get("sub_question_id")) or 10**6)
            if isinstance(sub.get("sub_question_id"), str)
            else 10**6,
            str(sub.get("sub_question_id") or ""),
        )
    )
    if unmatched_steps and empty_subs:
        chunk_size = max(1, (len(unmatched_steps) + len(empty_subs) - 1) // len(empty_subs))
        for idx, sub in enumerate(empty_subs):
            sub_id = sub.get("sub_question_id")
            if not isinstance(sub_id, str):
                continue
            start = idx * chunk_size
            end = start + chunk_size
            if start >= len(unmatched_steps):
                break
            assigned[sub_id].extend(unmatched_steps[start:end])
    elif unmatched_steps and len(sub_entries) == 1:
        sub_id = sub_entries[0].get("sub_question_id")
        if isinstance(sub_id, str):
            assigned.setdefault(sub_id, []).extend(unmatched_steps)

    updated_entries: List[Dict[str, Any]] = []
    for sub in sub_entries:
        if not isinstance(sub, dict):
            continue
        item = dict(sub)
        sub_id = item.get("sub_question_id") if isinstance(item.get("sub_question_id"), str) else None
        existing_steps = item.get("steps") if isinstance(item.get("steps"), list) else []
        if isinstance(sub_id, str) and (not existing_steps) and assigned.get(sub_id):
            item["steps"] = assigned[sub_id]
            if not isinstance(item.get("student_answer_text"), str) or not item.get("student_answer_text"):
                item["student_answer_text"] = "\n".join(assigned[sub_id])
            if not isinstance(item.get("answer_text"), str) or not item.get("answer_text"):
                item["answer_text"] = "\n".join(assigned[sub_id])
            trace = item.get("trace") if isinstance(item.get("trace"), dict) else {}
            trace = dict(trace)
            notes = trace.get("notes") if isinstance(trace.get("notes"), str) else ""
            inherited_note = "steps inherited from parent question trace"
            trace["notes"] = inherited_note if not notes else f"{notes}; {inherited_note}"
            item["trace"] = trace
        updated_entries.append(item)
    return updated_entries


EMPTY_TRACE_REASON_NOTES: Dict[str, str] = {
    "no_answer_candidate_mapped": "未找到可映射到该题的作答痕迹",
    "no_nonempty_raw_text": "原始转写阶段未提取到有效作答文本",
    "candidate_without_signal": "已命中候选区域，但未识别出有效作答信号",
    "question_id_unmatched_in_structuring": "识别到了作答内容，但结构化阶段未能稳定对齐题号",
    "sub_question_no_answer_candidate": "未找到可映射到该小题的作答痕迹",
    "sub_question_unmatched_in_structuring": "识别到了作答内容，但结构化阶段未能稳定对齐到该小题",
}


def _resolve_empty_trace_reason_note(reason_code: str, note: Optional[str] = None) -> str:
    if isinstance(note, str) and note.strip():
        return note.strip()
    resolved_reason = reason_code if reason_code in EMPTY_TRACE_REASON_NOTES else "no_answer_candidate_mapped"
    return EMPTY_TRACE_REASON_NOTES[resolved_reason]


def _build_empty_trace_payload(
    *,
    reason_code: str,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    resolved_reason = reason_code if reason_code in EMPTY_TRACE_REASON_NOTES else "no_answer_candidate_mapped"
    return {
        "scratchwork": None,
        "corrections": None,
        "readability": None,
        "confidence": None,
        "reason_code": resolved_reason,
        "notes": _resolve_empty_trace_reason_note(resolved_reason, note),
    }


def _default_sub_trace_item(
    question: Dict[str, Any],
    sub_question: Dict[str, Any],
    *,
    reason_code: str = "sub_question_no_answer_candidate",
    note: Optional[str] = None,
) -> Dict[str, Any]:
    qid = question.get("question_id")
    qtype = _normalize_question_type(question.get("question_type"))
    tags = question.get("skill_tags") if isinstance(question.get("skill_tags"), list) else []
    sub_id = sub_question.get("sub_question_id") if isinstance(sub_question, dict) else None
    raw_sub_id = sub_question.get("raw_sub_question_id") if isinstance(sub_question, dict) else None
    return {
        "question_id": qid,
        "raw_question_id": question.get("raw_question_id"),
        "sub_question_id": sub_id if isinstance(sub_id, str) else None,
        "raw_sub_question_id": raw_sub_id if isinstance(raw_sub_id, str) else None,
        "question_type": qtype,
        "skill_tags": tags,
        "status": "unseen",
        "score": None,
        "max_score": question.get("max_score") if isinstance(question.get("max_score"), (int, float)) else None,
        "is_correct": None,
        "selected_option": None,
        "filled_value": None,
        "student_answer_text": None,
        "answer_text": None,
        "steps": [],
        "skill_observations": [],
        "trace": _build_empty_trace_payload(reason_code=reason_code, note=note),
    }


def _build_knowledge_groups(candidate_points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for point in candidate_points:
        if not isinstance(point, dict):
            continue
        point_id = point.get("id")
        if not isinstance(point_id, str) or not point_id.strip():
            continue
        group_id = _skill_group_id(point_id)
        if not isinstance(group_id, str) or not group_id:
            continue
        bucket = grouped.setdefault(
            group_id,
            {
                "group_id": group_id,
                "point_count": 0,
                "sample_ids": [],
                "sample_names": [],
                "types": [],
            },
        )
        bucket["point_count"] += 1
        if len(bucket["sample_ids"]) < 3:
            bucket["sample_ids"].append(point_id)
        point_name = point.get("name")
        if isinstance(point_name, str) and point_name.strip() and len(bucket["sample_names"]) < 3:
            bucket["sample_names"].append(point_name.strip())
        point_type = point.get("type")
        if isinstance(point_type, str) and point_type.strip() and point_type not in bucket["types"]:
            bucket["types"].append(point_type)
    return sorted(grouped.values(), key=lambda item: str(item.get("group_id") or ""))


def _normalize_knowledge_groups_by_question(
    question_chunk: List[Dict[str, Any]],
    raw_items: Any,
) -> List[Dict[str, Any]]:
    valid_question_ids = {
        item.get("question_id")
        for item in question_chunk
        if isinstance(item, dict) and isinstance(item.get("question_id"), str) and item.get("question_id")
    }
    output: List[Dict[str, Any]] = []
    seen_question_ids: set[str] = set()
    if not isinstance(raw_items, list):
        return output
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        qid = _canonical_question_id(item.get("question_id"))
        if not isinstance(qid, str) or qid not in valid_question_ids or qid in seen_question_ids:
            continue
        raw_groups = item.get("knowledge_groups")
        groups: List[str] = []
        if isinstance(raw_groups, list):
            for value in raw_groups:
                if not isinstance(value, str):
                    continue
                normalized = _skill_group_id(value)
                if isinstance(normalized, str) and normalized and normalized not in groups:
                    groups.append(normalized)
        output.append({"question_id": qid, "knowledge_groups": groups})
        seen_question_ids.add(qid)
    return output


def _filter_candidate_points_by_groups(
    candidate_points: List[Dict[str, Any]],
    knowledge_groups_by_question: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    selected_groups: set[str] = set()
    for item in knowledge_groups_by_question:
        if not isinstance(item, dict):
            continue
        raw_groups = item.get("knowledge_groups")
        if not isinstance(raw_groups, list):
            continue
        for group_id in raw_groups:
            if isinstance(group_id, str) and group_id.strip():
                selected_groups.add(group_id.strip())
    if not selected_groups:
        return list(candidate_points)
    filtered = [
        point
        for point in candidate_points
        if isinstance(point, dict)
        and isinstance(point.get("id"), str)
        and _skill_group_id(point.get("id")) in selected_groups
    ]
    return filtered or list(candidate_points)


def _normalize_sub_questions(raw: Any, main_qid: str) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for idx, item in enumerate(raw):
        raw_sub_id: Optional[str] = None
        sub_text = ""
        if isinstance(item, dict):
            candidate = item.get("sub_question_id")
            if not isinstance(candidate, str):
                candidate = item.get("question_id") if isinstance(item.get("question_id"), str) else None
            if not isinstance(candidate, str):
                candidate = item.get("id") if isinstance(item.get("id"), str) else None
            if not isinstance(candidate, str):
                candidate = item.get("小题号") if isinstance(item.get("小题号"), str) else None
            raw_sub_id = candidate.strip() if isinstance(candidate, str) else None
            for key in ("sub_text", "problem_text", "text", "content", "题干"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    sub_text = value.strip()
                    break
        elif isinstance(item, str):
            sub_text = item.strip()
        if not raw_sub_id and not sub_text:
            continue
        sub_id = _canonical_sub_question_id(main_qid, raw_sub_id or "")
        if not sub_id:
            sub_id = f"{main_qid}({idx + 1})"
        if sub_id in seen_ids:
            continue
        seen_ids.add(sub_id)
        out.append(
            {
                "sub_question_id": sub_id,
                "raw_sub_question_id": raw_sub_id,
                "sub_text": sub_text,
            }
        )
    return out


def _normalize_question_item(raw: Dict[str, Any], *, page_index: Optional[int] = None) -> Optional[Dict[str, Any]]:
    raw_qid_value = raw.get("question_id")
    if raw_qid_value is None:
        for alt_key in ("id", "question_no", "question_number", "number", "no", "qid", "题号"):
            candidate = raw.get(alt_key)
            if candidate is not None:
                raw_qid_value = candidate
                break
    raw_qid: Optional[str] = None
    if isinstance(raw_qid_value, str) and raw_qid_value.strip():
        raw_qid = raw_qid_value.strip()
    elif isinstance(raw_qid_value, (int, float)):
        try:
            number = float(raw_qid_value)
            if number.is_integer():
                raw_qid = str(int(number))
        except Exception:
            raw_qid = None
    if not isinstance(raw_qid, str) or not raw_qid:
        return None
    canonical_qid = _canonical_question_id(raw_qid)
    if not isinstance(canonical_qid, str) or not canonical_qid:
        return None
    tags_raw = _first_present(raw, ["skill_tags", "knowledge_points", "knowledge_tags", "skills", "tags"])
    tags = [x for x in tags_raw if isinstance(x, str) and x.strip()] if isinstance(tags_raw, list) else []
    qtype = _normalize_question_type(_first_present(raw, ["question_type", "type", "题型"]))

    problem_text_value = _first_present(raw, ["problem_text", "question_text", "stem", "content", "text", "题干"])
    problem_text_full_value = _first_present(raw, ["problem_text_full", "full_text", "question_text_full", "content_full", "完整题干"])
    problem_text = problem_text_value if isinstance(problem_text_value, str) else ""
    problem_text_full = problem_text_full_value if isinstance(problem_text_full_value, str) else ""
    if not problem_text_full:
        problem_text_full = problem_text
    if not problem_text:
        problem_text = problem_text_full[:200]

    sub_questions = _normalize_sub_questions(
        _first_present(raw, ["sub_questions", "children", "sub_items", "parts", "小题"]),
        canonical_qid,
    )
    _, inferred_sub = _extract_main_and_sub_ids(raw_qid)
    if not sub_questions and isinstance(inferred_sub, str) and inferred_sub:
        sub_questions = [
            {
                "sub_question_id": f"{canonical_qid}({inferred_sub})",
                "raw_sub_question_id": raw_qid.strip(),
                "sub_text": problem_text_full.strip(),
            }
        ]

    page_value = _first_present(raw, ["paper_page_index", "page_index", "page", "页码"])
    raw_page_index = int(page_value) if isinstance(page_value, (int, float)) and int(page_value) >= 0 else None
    normalized_page_index = (
        page_index
        if isinstance(page_index, int) and page_index >= 0
        else (raw_page_index if isinstance(raw_page_index, int) and raw_page_index >= 0 else 0)
    )
    confidence_value = _coerce_confidence(raw.get("confidence"))
    max_score_value = _coerce_optional_number(_first_present(raw, ["max_score", "full_score", "score", "points", "分值"]))
    normalized = {
        "question_id": canonical_qid,
        "raw_question_id": raw_qid.strip(),
        "question_type": qtype,
        "problem_text": problem_text.strip(),
        "problem_text_full": problem_text_full.strip(),
        "skill_tags": tags,
        "confidence": confidence_value,
        "max_score": max_score_value,
        "sub_questions": sub_questions,
        "paper_page_index": normalized_page_index,
    }
    return normalized


def _merge_question_items(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(existing)
    existing_full = merged.get("problem_text_full") if isinstance(merged.get("problem_text_full"), str) else ""
    incoming_full = incoming.get("problem_text_full") if isinstance(incoming.get("problem_text_full"), str) else ""
    incoming_page = incoming.get("paper_page_index")
    existing_page = merged.get("paper_page_index")
    same_page_or_unknown = (
        not isinstance(existing_page, int)
        or not isinstance(incoming_page, int)
        or existing_page == incoming_page
    )
    if len(incoming_full) > len(existing_full) and (same_page_or_unknown or not existing_full.strip()):
        merged["problem_text_full"] = incoming_full
    existing_brief = merged.get("problem_text") if isinstance(merged.get("problem_text"), str) else ""
    incoming_brief = incoming.get("problem_text") if isinstance(incoming.get("problem_text"), str) else ""
    if len(incoming_brief) > len(existing_brief) and (same_page_or_unknown or not existing_brief.strip()):
        merged["problem_text"] = incoming_brief

    incoming_type = incoming.get("question_type")
    if isinstance(incoming_type, str) and incoming_type.strip():
        existing_type = merged.get("question_type")
        if not isinstance(existing_type, str) or _normalize_question_type(existing_type) == "unknown":
            merged["question_type"] = incoming_type

    tags_existing = merged.get("skill_tags") if isinstance(merged.get("skill_tags"), list) else []
    tags_incoming = incoming.get("skill_tags") if isinstance(incoming.get("skill_tags"), list) else []
    seen: set[str] = set()
    tags_merged: List[str] = []
    for tag in list(tags_existing) + list(tags_incoming):
        if not isinstance(tag, str) or not tag.strip() or tag in seen:
            continue
        seen.add(tag)
        tags_merged.append(tag)
    merged["skill_tags"] = tags_merged

    conf_existing = merged.get("confidence")
    conf_incoming = incoming.get("confidence")
    if isinstance(conf_incoming, (int, float)):
        if not isinstance(conf_existing, (int, float)) or float(conf_incoming) > float(conf_existing):
            merged["confidence"] = float(conf_incoming)
    if isinstance(incoming_page, int):
        incoming_has_text = bool(incoming_full.strip() or incoming_brief.strip())
        existing_has_text = bool(existing_full.strip() or existing_brief.strip())
        if not isinstance(existing_page, int) or (incoming_has_text and not existing_has_text):
            merged["paper_page_index"] = incoming_page

    sub_map: Dict[str, Dict[str, Any]] = {}
    for sub in merged.get("sub_questions", []):
        if isinstance(sub, dict) and isinstance(sub.get("sub_question_id"), str):
            sub_map[sub["sub_question_id"]] = dict(sub)
    for sub in incoming.get("sub_questions", []):
        if not isinstance(sub, dict):
            continue
        sqid = sub.get("sub_question_id")
        if not isinstance(sqid, str) or not sqid:
            continue
        cur = sub_map.get(sqid)
        if cur is None:
            sub_map[sqid] = dict(sub)
            continue
        cur_text = cur.get("sub_text") if isinstance(cur.get("sub_text"), str) else ""
        new_text = sub.get("sub_text") if isinstance(sub.get("sub_text"), str) else ""
        if len(new_text) > len(cur_text):
            cur["sub_text"] = new_text
        if not cur.get("raw_sub_question_id") and sub.get("raw_sub_question_id"):
            cur["raw_sub_question_id"] = sub.get("raw_sub_question_id")
    merged["sub_questions"] = list(sub_map.values())
    return merged


def _build_missing_from_step1(questions: List[Dict[str, Any]]) -> List[str]:
    nums: List[int] = []
    for q in questions:
        qid = q.get("question_id")
        if not isinstance(qid, str):
            continue
        match = re.fullmatch(r"Q(\d{1,3})", qid.strip())
        if not match:
            continue
        nums.append(int(match.group(1)))
    if len(nums) < 2:
        return []
    present = set(nums)
    low = min(nums)
    high = max(nums)
    return [f"Q{i}" for i in range(low, high + 1) if i not in present]


def _context_ids_from_raw_items(raw_items: List[Dict[str, Any]]) -> List[str]:
    ids: List[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        raw_ids = item.get("context_question_ids")
        if isinstance(raw_ids, list):
            for qid in raw_ids:
                if isinstance(qid, str) and qid.strip() and qid.strip() not in seen:
                    seen.add(qid.strip())
                    ids.append(qid.strip())
    return ids


def _select_answer_contexts_for_raw_items(
    answer_contexts: List[Dict[str, Any]],
    raw_items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    target_ids = set(_context_ids_from_raw_items(raw_items))
    if not target_ids:
        return answer_contexts
    selected = [
        ctx
        for ctx in answer_contexts
        if isinstance(ctx, dict) and isinstance(ctx.get("question_id"), str) and ctx["question_id"] in target_ids
    ]
    return selected or answer_contexts


def _chunk_raw_answer_items(
    raw_items: List[Dict[str, Any]],
    chunk_size: int,
) -> List[List[Dict[str, Any]]]:
    nonempty = [
        item
        for item in raw_items
        if isinstance(item, dict) and isinstance(item.get("raw_text"), str) and item["raw_text"].strip()
    ]
    return [chunk for chunk in _chunk_list(nonempty, max(1, int(chunk_size))) if chunk]


def _has_strong_answer_page_hint(context: Dict[str, Any]) -> bool:
    confidence = context.get("answer_page_hint_confidence")
    if isinstance(confidence, (int, float)) and float(confidence) >= 0.55:
        return True
    evidence = context.get("answer_page_hint_evidence")
    return isinstance(evidence, str) and evidence.strip() and evidence != "fallback_to_question_page"


def _select_answer_contexts_for_slice(
    *,
    page_index: int,
    primary_contexts: List[Dict[str, Any]],
    answer_contexts: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    base_contexts = primary_contexts if primary_contexts else answer_contexts
    strong_page_contexts = [
        ctx
        for ctx in base_contexts
        if isinstance(ctx, dict)
        and isinstance(ctx.get("answer_page_hint"), int)
        and ctx.get("answer_page_hint") == page_index
        and _has_strong_answer_page_hint(ctx)
    ]
    if strong_page_contexts:
        return strong_page_contexts
    return base_contexts


def _select_manual_block_contexts(
    *,
    page_index: int,
    answer_contexts: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    return _select_answer_contexts_for_slice(
        page_index=page_index,
        primary_contexts=[],
        answer_contexts=answer_contexts,
    )


def _merge_answer_contexts(*groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    for group in groups:
        if not isinstance(group, list):
            continue
        for ctx in group:
            if not isinstance(ctx, dict):
                continue
            qid = ctx.get("question_id")
            if not isinstance(qid, str) or not qid or qid in seen_ids:
                continue
            seen_ids.add(qid)
            merged.append(ctx)
    return merged


def _select_segment_contexts(
    *,
    page_index: int,
    class_name: str,
    answer_contexts: List[Dict[str, Any]],
    choice_contexts: List[Dict[str, Any]],
    blank_contexts: List[Dict[str, Any]],
    solution_contexts: List[Dict[str, Any]],
    allow_blank_fallback_for_subjective: bool,
) -> List[Dict[str, Any]]:
    class_context_map: Dict[str, List[Dict[str, Any]]] = {
        "objective_problem": choice_contexts,
        "fillin_problem": blank_contexts,
        "subjective_problem": solution_contexts,
    }
    primary_contexts = class_context_map.get(class_name) or []
    selected = _select_answer_contexts_for_slice(
        page_index=page_index,
        primary_contexts=primary_contexts,
        answer_contexts=answer_contexts,
    )
    if (
        class_name == "subjective_problem"
        and allow_blank_fallback_for_subjective
        and blank_contexts
    ):
        blank_selected = _select_answer_contexts_for_slice(
            page_index=page_index,
            primary_contexts=blank_contexts,
            answer_contexts=answer_contexts,
        )
        if blank_selected:
            selected = _merge_answer_contexts(blank_selected, selected)
    return selected


def _answer_record_rank(answer: Dict[str, Any]) -> float:
    score = 0.0
    status = answer.get("status")
    if status == "answered":
        score += 2.0
    elif status == "unclear":
        score += 0.5
    if isinstance(answer.get("score"), (int, float)):
        score += 1.0
    if isinstance(answer.get("max_score"), (int, float)):
        score += 0.5
    if isinstance(answer.get("deducted_score"), (int, float)):
        score += 0.7
    if isinstance(answer.get("is_correct"), bool):
        score += 0.5
    if isinstance(answer.get("selected_option"), str) and answer["selected_option"].strip():
        score += 0.8
    if isinstance(answer.get("filled_value"), str) and answer["filled_value"].strip():
        score += 0.8
    if isinstance(answer.get("student_answer_text"), str) and answer["student_answer_text"].strip():
        score += 0.6
    steps = answer.get("steps")
    if isinstance(steps, list):
        score += min(0.5, 0.1 * len(steps))
    trace = answer.get("trace")
    if isinstance(trace, dict) and isinstance(trace.get("confidence"), (int, float)):
        score += 0.5 * max(0.0, min(1.0, float(trace["confidence"])))
    source_stage = answer.get("_source_stage")
    if source_stage == "score":
        score += 0.9
    elif source_stage == "repair":
        score += 1.1
    if answer.get("_page_matches_hint") is True:
        score += 0.8
    evidence = answer.get("_evidence")
    if isinstance(evidence, str) and evidence.strip():
        score += 0.2
    conflicts = answer.get("_rule_conflicts")
    if isinstance(conflicts, list):
        score -= 1.2 * len(conflicts)
    return score


def _is_valid_sub_question_for_context(context: Dict[str, Any], sub_question_id: Optional[str]) -> bool:
    if not isinstance(sub_question_id, str) or not sub_question_id:
        return True
    declared = context.get("sub_questions")
    if not isinstance(declared, list) or not declared:
        return True
    valid_ids = {
        sub.get("sub_question_id")
        for sub in declared
        if isinstance(sub, dict) and isinstance(sub.get("sub_question_id"), str)
    }
    if not valid_ids:
        return True
    return sub_question_id in valid_ids


def _declared_sub_question_ids(context: Dict[str, Any]) -> set[str]:
    declared = context.get("sub_questions")
    if not isinstance(declared, list):
        return set()
    return {
        sub.get("sub_question_id")
        for sub in declared
        if isinstance(sub, dict) and isinstance(sub.get("sub_question_id"), str) and sub.get("sub_question_id")
    }


def _is_self_sub_question_reference(
    context_qid: str,
    raw_sub_question_id: Optional[str],
    normalized_sub_question_id: Optional[str],
) -> bool:
    if not isinstance(context_qid, str) or not context_qid:
        return False
    if not isinstance(raw_sub_question_id, str) or not raw_sub_question_id.strip():
        return False
    if normalized_sub_question_id == f"{context_qid}({context_qid})":
        return True
    compact = re.sub(r"\s+", "", raw_sub_question_id.strip()).upper()
    return compact in {context_qid.upper(), context_qid.upper().removeprefix("Q")}


def _answer_rule_conflicts(answer: Dict[str, Any], context: Dict[str, Any]) -> List[str]:
    conflicts: List[str] = []
    score = answer.get("score")
    max_score = answer.get("max_score")
    deducted_score = answer.get("deducted_score")
    is_correct = answer.get("is_correct")
    sub_question_id = answer.get("sub_question_id")
    if isinstance(score, (int, float)) and score < 0:
        conflicts.append("score_negative")
    if isinstance(score, (int, float)) and isinstance(max_score, (int, float)):
        if max_score < 0:
            conflicts.append("max_score_negative")
        elif score > max_score:
            conflicts.append("score_exceeds_max")
        if isinstance(is_correct, bool):
            if is_correct and score < max_score:
                conflicts.append("correct_but_not_full_score")
            if (not is_correct) and score == max_score:
                conflicts.append("incorrect_but_full_score")
    if isinstance(deducted_score, (int, float)):
        if deducted_score < 0:
            conflicts.append("deducted_score_negative")
        if isinstance(max_score, (int, float)) and deducted_score > max_score:
            conflicts.append("deducted_exceeds_max")
        if isinstance(is_correct, bool):
            if is_correct and deducted_score > 0:
                conflicts.append("correct_but_deducted")
            if (not is_correct) and deducted_score == 0:
                conflicts.append("incorrect_without_deduction")
    if not _is_valid_sub_question_for_context(context, sub_question_id):
        conflicts.append("sub_question_out_of_scope")
    return conflicts

def _pick_best_candidate(
    candidates: List[Dict[str, Any]],
    predicate,
) -> Optional[Dict[str, Any]]:
    matched = [item for item in candidates if predicate(item)]
    if not matched:
        return None
    return max(matched, key=_answer_record_rank)


def _normalize_answer_item(
    raw: Dict[str, Any],
    context_map: Dict[str, Dict[str, Any]],
    *,
    source_stage: str = "trace",
    page_index: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    qid_raw = _first_present(raw, ["question_id", "qid", "question_no", "question_number", "id", "题号"])
    if not isinstance(qid_raw, str):
        if isinstance(qid_raw, (int, float)):
            qid_raw = str(int(qid_raw)) if float(qid_raw).is_integer() else str(qid_raw)
        else:
            return None
    if not isinstance(qid_raw, str):
        return None
    qid = qid_raw.strip()
    if not qid:
        return None
    context = context_map.get(qid)
    if context is None:
        canonical_qid = _canonical_question_id(qid)
        if isinstance(canonical_qid, str) and canonical_qid:
            context = context_map.get(canonical_qid)
    if not context:
        return None
    context_qid = context.get("question_id") if isinstance(context.get("question_id"), str) else qid
    raw_sub = _first_present(raw, ["sub_question_id", "sub_qid", "part_id", "sub_id", "小题号"])
    raw_sub_question_id = raw_sub if isinstance(raw_sub, str) else None
    normalized_sub_question_id = _canonical_sub_question_id(context_qid, raw_sub_question_id)
    declared_sub_ids = _declared_sub_question_ids(context)
    if (
        normalized_sub_question_id
        and not declared_sub_ids
        and _is_self_sub_question_reference(context_qid, raw_sub_question_id, normalized_sub_question_id)
    ):
        normalized_sub_question_id = None
    if normalized_sub_question_id is None:
        _, inferred_sub = _extract_main_and_sub_ids(qid)
        if isinstance(inferred_sub, str) and inferred_sub:
            normalized_sub_question_id = f"{context_qid}({inferred_sub})"

    qtype = _normalize_question_type(raw.get("question_type"))
    if qtype == "unknown":
        qtype = _normalize_question_type(context.get("question_type"))

    tags_raw = _first_present(raw, ["skill_tags", "knowledge_points", "knowledge_tags", "skills", "tags"])
    tags = [x for x in tags_raw if isinstance(x, str)] if isinstance(tags_raw, list) else []
    if not tags:
        ctx_tags = context.get("skill_tags")
        tags = [x for x in ctx_tags if isinstance(x, str)] if isinstance(ctx_tags, list) else []

    trace = raw.get("trace") if isinstance(raw.get("trace"), dict) else {}
    evidence = raw.get("evidence") if isinstance(raw.get("evidence"), str) else None
    evidence_blocks = raw.get("evidence_blocks") if isinstance(raw.get("evidence_blocks"), list) else []
    status_raw = raw.get("status") if isinstance(raw.get("status"), str) else ""
    status_aliases = {
        "done": "answered",
        "recognized": "answered",
        "empty": "unseen",
        "missing": "unseen",
        "not_answered": "unseen",
        "unknown": "unclear",
    }
    status = status_aliases.get(status_raw.strip().lower(), status_raw.strip().lower())
    raw_student_answer = _first_present(raw, ["student_answer_text", "student_answer", "answer_text", "answer", "content", "作答"])
    if not isinstance(raw_student_answer, str):
        raw_student_answer = None
    if status not in {"answered", "unseen", "unclear"}:
        has_signal = any(
            (
                isinstance(_coerce_optional_number(_first_present(raw, ["score", "得分"])), (int, float)),
                isinstance(_coerce_optional_number(_first_present(raw, ["deducted_score", "lost_score", "score_deduction", "扣分"])), (int, float)),
                isinstance(_coerce_optional_bool(_first_present(raw, ["is_correct", "correct", "by_answer_key", "是否正确"])), bool),
                isinstance(raw_student_answer, str) and raw_student_answer.strip(),
                isinstance(_first_present(raw, ["selected_option", "choice", "option", "选项"]), str)
                and str(_first_present(raw, ["selected_option", "choice", "option", "选项"])).strip(),
                isinstance(_first_present(raw, ["filled_value", "fill_value", "blank_answer", "填空答案"]), str)
                and str(_first_present(raw, ["filled_value", "fill_value", "blank_answer", "填空答案"])).strip(),
            )
        )
        status = "answered" if has_signal else "unseen"
    student_answer_text = raw_student_answer if isinstance(raw_student_answer, str) else None
    final_answer_text = student_answer_text
    student_answer_text = _strip_ellipsis_text(student_answer_text)
    final_answer_text = _strip_ellipsis_text(final_answer_text)
    steps = _normalize_steps_list(raw.get("steps"))
    if not steps:
        steps = _infer_steps_from_answer_text(student_answer_text, final_answer_text)
    notes = trace.get("notes") if isinstance(trace.get("notes"), str) else None
    notes = _strip_ellipsis_text(notes)
    trace_confidence = trace.get("confidence")
    if not isinstance(trace_confidence, (int, float, str)):
        trace_confidence = _first_present(raw, ["confidence", "recognition_confidence", "置信度"])

    if normalized_sub_question_id and declared_sub_ids and normalized_sub_question_id not in declared_sub_ids:
        normalized_sub_question_id = None
    if normalized_sub_question_id and not _is_valid_sub_question_for_context(context, normalized_sub_question_id):
        normalized_sub_question_id = None

    deducted_score_raw = _coerce_optional_number(_first_present(raw, ["deducted_score", "lost_score", "score_deduction", "扣分"]))
    if not isinstance(deducted_score_raw, (int, float)):
        deducted_score_raw = _coerce_optional_number(raw.get("lost_score"))
    if not isinstance(deducted_score_raw, (int, float)):
        deducted_score_raw = _coerce_optional_number(raw.get("score_deduction"))
    if not isinstance(deducted_score_raw, (int, float)):
        deducted_score_raw = _coerce_optional_number(raw.get("扣分"))

    normalized_score = _coerce_optional_number(_first_present(raw, ["score", "得分"]))
    normalized_max_score = _coerce_optional_number(_first_present(raw, ["max_score", "full_score", "points", "满分"]))
    normalized_deducted = float(deducted_score_raw) if isinstance(deducted_score_raw, (int, float)) else None
    if normalized_deducted is None and isinstance(normalized_score, (int, float)) and isinstance(normalized_max_score, (int, float)):
        normalized_deducted = float(normalized_max_score) - float(normalized_score)
        if normalized_deducted < 0:
            normalized_deducted = None

    normalized = {
        "question_id": context_qid,
        "raw_question_id": qid,
        "sub_question_id": normalized_sub_question_id,
        "raw_sub_question_id": raw_sub_question_id,
        "question_type": qtype,
        "skill_tags": tags,
        "status": status,
        "score": float(normalized_score) if isinstance(normalized_score, (int, float)) else None,
        "max_score": float(normalized_max_score) if isinstance(normalized_max_score, (int, float)) else None,
        "deducted_score": normalized_deducted,
        "is_correct": _coerce_optional_bool(_first_present(raw, ["is_correct", "correct", "by_answer_key", "是否正确"])),
        "selected_option": _first_present(raw, ["selected_option", "choice", "option", "选项"])
        if isinstance(_first_present(raw, ["selected_option", "choice", "option", "选项"]), str)
        else None,
        "filled_value": _first_present(raw, ["filled_value", "fill_value", "blank_answer", "填空答案"])
        if isinstance(_first_present(raw, ["filled_value", "fill_value", "blank_answer", "填空答案"]), str)
        else None,
        "student_answer_text": student_answer_text,
        "answer_text": final_answer_text,
        "steps": steps,
        "skill_observations": raw.get("skill_observations") if isinstance(raw.get("skill_observations"), list) else [],
        "trace": {
            "scratchwork": trace.get("scratchwork") if isinstance(trace.get("scratchwork"), bool) else None,
            "corrections": trace.get("corrections") if isinstance(trace.get("corrections"), bool) else None,
            "readability": trace.get("readability") if isinstance(trace.get("readability"), (int, float)) else None,
            "confidence": _coerce_confidence(trace_confidence),
            "notes": notes,
        },
        "_source_stage": source_stage,
        "_page_index": page_index,
        "_route_page_hint": context.get("answer_page_hint") if isinstance(context.get("answer_page_hint"), int) else None,
        "_page_matches_hint": (
            isinstance(page_index, int)
            and isinstance(context.get("answer_page_hint"), int)
            and page_index == context.get("answer_page_hint")
        ),
        "_evidence": evidence,
        "_evidence_blocks": [item for item in evidence_blocks if isinstance(item, str)],
        "_rule_conflicts": [],
    }
    if normalized["max_score"] is None:
        context_max = context.get("max_score")
        normalized["max_score"] = float(context_max) if isinstance(context_max, (int, float)) else None
    if (
        normalized.get("deducted_score") is None
        and isinstance(normalized.get("score"), (int, float))
        and isinstance(normalized.get("max_score"), (int, float))
    ):
        deduced = float(normalized["max_score"]) - float(normalized["score"])
        if deduced >= 0:
            normalized["deducted_score"] = deduced
    normalized["_rule_conflicts"] = _answer_rule_conflicts(normalized, context)
    if normalized["_rule_conflicts"] and normalized["status"] == "answered":
        normalized["status"] = "unclear"
    return normalized


def _merge_text_fragments(fragments: List[Any]) -> Optional[str]:
    merged: List[tuple[str, str]] = []
    for raw in fragments:
        text = _normalize_merge_text(raw)
        if not isinstance(text, str):
            continue
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            continue
        if any(normalized == existing_norm or normalized in existing_norm for _, existing_norm in merged):
            continue
        merged = [
            (existing_text, existing_norm)
            for existing_text, existing_norm in merged
            if not (existing_norm in normalized and existing_norm != normalized)
        ]
        merged.append((text, normalized))
    if not merged:
        return None
    return "\n".join(text for text, _ in merged)


def _merge_step_lists(candidates: List[Dict[str, Any]]) -> List[str]:
    seen: set[str] = set()
    output: List[str] = []
    for item in candidates:
        steps = item.get("steps") if isinstance(item.get("steps"), list) else []
        for step in steps:
            text = _normalize_merge_text(step)
            if not isinstance(text, str):
                continue
            normalized = re.sub(r"\s+", " ", text).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            output.append(text)
    return output


def _merge_skill_observations(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    output: List[Dict[str, Any]] = []
    for item in candidates:
        observations = item.get("skill_observations") if isinstance(item.get("skill_observations"), list) else []
        for observation in observations:
            if not isinstance(observation, dict):
                continue
            key = json.dumps(observation, ensure_ascii=False, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            output.append(observation)
    return output


def _merge_trace_flag(candidates: List[Dict[str, Any]], key: str) -> Optional[bool]:
    values: List[bool] = []
    for item in candidates:
        trace = item.get("trace") if isinstance(item.get("trace"), dict) else {}
        value = trace.get(key)
        if isinstance(value, bool):
            values.append(value)
    if not values:
        return None
    if any(values):
        return True
    return False


def _merge_internal_evidence_blocks(candidates: List[Dict[str, Any]]) -> List[str]:
    seen: set[str] = set()
    output: List[str] = []
    for item in candidates:
        blocks = item.get("_evidence_blocks") if isinstance(item.get("_evidence_blocks"), list) else []
        for block in blocks:
            text = _normalize_merge_text(block)
            if not isinstance(text, str):
                continue
            if text in seen:
                continue
            seen.add(text)
            output.append(text)
    return output


def _apply_empty_trace_reason(
    answer: Dict[str, Any],
    reason_code: str,
    *,
    note: Optional[str] = None,
    overwrite: bool = False,
) -> Dict[str, Any]:
    if _has_answer_signal(answer):
        return answer
    trace = answer.get("trace") if isinstance(answer.get("trace"), dict) else {}
    trace = dict(trace)
    resolved_reason = reason_code if reason_code in EMPTY_TRACE_REASON_NOTES else "no_answer_candidate_mapped"
    if overwrite or not (isinstance(trace.get("reason_code"), str) and trace.get("reason_code").strip()):
        trace["reason_code"] = resolved_reason
    if overwrite or not (isinstance(trace.get("notes"), str) and trace.get("notes").strip()):
        trace["notes"] = _resolve_empty_trace_reason_note(resolved_reason, note)
    answer["trace"] = trace
    return answer


def _public_answer_item(answer: Dict[str, Any]) -> Dict[str, Any]:
    public: Dict[str, Any] = {}
    for key, value in answer.items():
        if key.startswith("_"):
            continue
        public[key] = value
    return public


def _normalize_reference_answer_item(
    raw: Any,
    context_map: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    qid = _canonical_question_id(_first_present(raw, ["question_id", "qid", "question_no", "question_number", "id", "题号"]))
    if not isinstance(qid, str) or not qid:
        qid = ""
    context = context_map.get(qid)
    if context is None:
        unique_contexts = {
            id(context_item): context_item
            for context_item in context_map.values()
            if isinstance(context_item, dict)
        }
        if len(unique_contexts) == 1:
            context = next(iter(unique_contexts.values()))
            fallback_qid = context.get("question_id")
            if isinstance(fallback_qid, str) and fallback_qid.strip():
                qid = fallback_qid.strip()
    if context is None:
        return None
    sub_qid = _canonical_sub_question_id(
        qid,
        _first_present(raw, ["sub_question_id", "sub_qid", "part_id", "sub_id", "小题号"]),
    )
    if sub_qid and not _is_valid_sub_question_for_context(context, sub_qid):
        sub_qid = None
    answer_text = None
    for key in ("reference_answer_text", "answer_text", "standard_answer", "correct_answer", "reference_answer", "答案"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            answer_text = value.strip()
            break
    analysis = raw.get("analysis")
    if not isinstance(analysis, str) or not analysis.strip():
        analysis = raw.get("解题分析")
        if not isinstance(analysis, str) or not analysis.strip():
            analysis = ""
        else:
            analysis = analysis.strip()
    else:
        analysis = analysis.strip()
    # Fallback: use analysis as answer_text if answer_text is missing
    if not answer_text and analysis:
        answer_text = analysis
    final_answer = None
    for key in ("reference_final_answer", "final_answer", "answer_final", "result", "最终答案"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            final_answer = value.strip()
            break
    steps = _normalize_steps_list(raw.get("reference_steps"))
    if not steps:
        steps = _infer_steps_from_answer_text(answer_text, answer_text)
    confidence_value = _coerce_confidence(raw.get("confidence"))
    reason = raw.get("reason") if isinstance(raw.get("reason"), str) else ""
    if not analysis and not answer_text and not final_answer and not steps:
        return None
    return {
        "question_id": qid,
        "sub_question_id": sub_qid,
        "analysis": analysis,
        "reference_answer_text": answer_text,
        "reference_final_answer": final_answer,
        "reference_steps": steps,
        "confidence": confidence_value,
        "reason": reason.strip(),
    }


def _reference_answer_maps(
    reference_answers: List[Dict[str, Any]],
) -> tuple[Dict[str, Dict[str, Any]], Dict[tuple[str, str], Dict[str, Any]]]:
    by_question: Dict[str, Dict[str, Any]] = {}
    by_sub: Dict[tuple[str, str], Dict[str, Any]] = {}
    for item in reference_answers:
        if not isinstance(item, dict):
            continue
        qid = item.get("question_id")
        if not isinstance(qid, str) or not qid:
            continue
        sub_qid = item.get("sub_question_id")
        if isinstance(sub_qid, str) and sub_qid:
            by_sub[(qid, sub_qid)] = item
        else:
            by_question[qid] = item
    return by_question, by_sub


def _find_reference_answer_for_trace(
    *,
    qid: str,
    sub_qid: Optional[str],
    by_question: Dict[str, Dict[str, Any]],
    by_sub: Dict[tuple[str, str], Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if isinstance(sub_qid, str) and sub_qid:
        hit = by_sub.get((qid, sub_qid))
        if isinstance(hit, dict):
            return hit
    hit = by_question.get(qid)
    if isinstance(hit, dict):
        return hit
    sub_hits = [item for (ref_qid, _), item in by_sub.items() if ref_qid == qid and isinstance(item, dict)]
    if len(sub_hits) == 1:
        return sub_hits[0]
    return None


_UNCERTAIN_GENERATED_REFERENCE_MARKERS = (
    "无法确定",
    "题目不完整",
    "无法给出",
    "不完整",
    "可能",
    "猜测",
    "常见题型",
    "不确定",
    "不合理",
    "需知",
    "假设",
)


def _is_uncertain_generated_reference(ref: Dict[str, Any]) -> bool:
    text_parts = [
        ref.get("reference_answer_text"),
        ref.get("reference_final_answer"),
        ref.get("reason"),
    ]
    steps = ref.get("reference_steps")
    if isinstance(steps, list):
        text_parts.extend(steps)
    combined = "\n".join(part for part in text_parts if isinstance(part, str))
    if not combined.strip():
        return True
    return any(marker in combined for marker in _UNCERTAIN_GENERATED_REFERENCE_MARKERS)


def _normalize_answer_key_correctness_item(
    raw: Any,
    context_map: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    qid = _canonical_question_id(_first_present(raw, ["question_id", "qid", "question_no", "question_number", "id", "题号"]))
    if not isinstance(qid, str) or qid not in context_map:
        return None
    sub_qid = _canonical_sub_question_id(
        qid,
        _first_present(raw, ["sub_question_id", "sub_qid", "part_id", "sub_id", "小题号"]),
    )
    if sub_qid and not _is_valid_sub_question_for_context(context_map[qid], sub_qid):
        sub_qid = None
    by_answer_key = _coerce_optional_bool(
        _first_present(raw, ["by_answer_key", "is_correct", "correct", "verdict", "是否正确"])
    )
    confidence_value = _coerce_confidence(raw.get("confidence"))
    reason = raw.get("reason") if isinstance(raw.get("reason"), str) else ""
    return {
        "question_id": qid,
        "sub_question_id": sub_qid,
        "by_answer_key": by_answer_key,
        "confidence": confidence_value,
        "reason": reason.strip(),
    }


def _build_answer_key_correctness_items(
    structured_questions_full: List[Dict[str, Any]],
    reference_answers: List[Dict[str, Any]],
    *,
    reference_source: str,
    teacher_review_by_id: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    by_question, by_sub = _reference_answer_maps(reference_answers)
    teacher_review_by_id = teacher_review_by_id or {}
    items_by_key: Dict[tuple[str, Optional[str]], Dict[str, Any]] = {}
    ranks_by_key: Dict[tuple[str, Optional[str]], float] = {}

    def _trace_teacher_review(qid: str, trace: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        trace_review = trace.get("teacher_review")
        if isinstance(trace_review, dict):
            return trace_review
        review = teacher_review_by_id.get(qid)
        return review if isinstance(review, dict) else None

    def _build_item(
        *,
        qid: str,
        sub_qid: Optional[str],
        question_text: Any,
        trace: Dict[str, Any],
        ref: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "question_id": qid,
            "sub_question_id": sub_qid,
            "question_text": _compact_text(question_text, 700),
            "student_answer_text": _compact_text(trace.get("student_answer_text") or trace.get("answer_text"), 700),
            "student_steps": _compact_steps(trace.get("steps"), limit=10, text_limit=260),
            "teacher_review": _trace_teacher_review(qid, trace),
            "reference_source": reference_source,
            "reference_answer_text": _compact_text(ref.get("reference_answer_text"), 900),
            "reference_final_answer": _compact_text(ref.get("reference_final_answer"), 360),
            "reference_steps": _compact_steps(ref.get("reference_steps"), limit=10, text_limit=260),
        }

    def _add_item(item: Dict[str, Any], trace: Dict[str, Any]) -> None:
        qid = item.get("question_id")
        if not isinstance(qid, str) or not qid:
            return
        sub_qid = item.get("sub_question_id") if isinstance(item.get("sub_question_id"), str) else None
        key = (qid, sub_qid)
        rank = _answer_record_rank(trace)
        if key not in items_by_key or rank > ranks_by_key.get(key, -1.0):
            items_by_key[key] = item
            ranks_by_key[key] = rank

    def _should_use_reference(ref: Dict[str, Any]) -> bool:
        if reference_source != "generated":
            return True
        return not _is_uncertain_generated_reference(ref)

    for question in structured_questions_full:
        if not isinstance(question, dict):
            continue
        qid = question.get("question_id")
        if not isinstance(qid, str) or not qid:
            continue
        problem_text = question.get("problem_text_full") if isinstance(question.get("problem_text_full"), str) else (
            question.get("problem_text") if isinstance(question.get("problem_text"), str) else ""
        )
        answer_trace = question.get("answer_trace") if isinstance(question.get("answer_trace"), dict) else {}
        sub_traces = question.get("sub_traces") if isinstance(question.get("sub_traces"), list) else []
        signaled_sub_ids = {
            sub.get("sub_question_id")
            for sub in sub_traces
            if isinstance(sub, dict)
            and _has_answer_signal(sub)
            and isinstance(sub.get("sub_question_id"), str)
            and sub.get("sub_question_id")
        }
        answer_trace_sub_qid = answer_trace.get("sub_question_id") if isinstance(answer_trace.get("sub_question_id"), str) else None
        parent_duplicates_sub_trace = isinstance(answer_trace_sub_qid, str) and answer_trace_sub_qid in signaled_sub_ids
        if _has_answer_signal(answer_trace) and not parent_duplicates_sub_trace:
            ref = _find_reference_answer_for_trace(
                qid=qid,
                sub_qid=answer_trace_sub_qid,
                by_question=by_question,
                by_sub=by_sub,
            )
            if isinstance(ref, dict) and _should_use_reference(ref):
                _add_item(
                    _build_item(
                        qid=qid,
                        sub_qid=answer_trace_sub_qid,
                        question_text=problem_text,
                        trace=answer_trace,
                        ref=ref,
                    ),
                    answer_trace,
                )
        for sub_trace in sub_traces:
            if not isinstance(sub_trace, dict) or not _has_answer_signal(sub_trace):
                continue
            sub_qid = sub_trace.get("sub_question_id") if isinstance(sub_trace.get("sub_question_id"), str) else None
            ref = _find_reference_answer_for_trace(
                qid=qid,
                sub_qid=sub_qid,
                by_question=by_question,
                by_sub=by_sub,
            )
            if not isinstance(ref, dict) or not _should_use_reference(ref):
                continue
            _add_item(
                _build_item(
                    qid=qid,
                    sub_qid=sub_qid,
                    question_text=sub_trace.get("sub_question_text") or problem_text,
                    trace=sub_trace,
                    ref=ref,
                ),
                sub_trace,
            )
    return list(items_by_key.values())


def _clean_math_expression(s: str) -> str:
    if not isinstance(s, str):
        return ""
    # Remove math delimiters, spaces, quotes, newlines, brackets, parentheses, backslashes
    s = s.strip().replace("$", "").replace(" ", "").replace("\n", "").replace("\r", "")
    s = s.replace("{", "").replace("}", "").replace("[", "").replace("]", "")
    s = s.replace("(", "").replace(")", "").replace("\\", "")
    s = s.replace("sqrt", "√")
    s = s.replace("根号", "√")
    return s.lower()


def _apply_answer_key_correctness_policy(
    answers: List[Dict[str, Any]],
    structured_questions_full: List[Dict[str, Any]],
    correctness_items: List[Dict[str, Any]],
    teacher_review_by_id: Dict[str, Dict[str, Any]],
    answer_key_source: str = "uploaded",
    reference_answers: Optional[List[Dict[str, Any]]] = None,
) -> int:
    correctness_map: Dict[tuple[str, Optional[str]], Dict[str, Any]] = {}
    for item in correctness_items:
        if not isinstance(item, dict):
            continue
        qid = item.get("question_id")
        if not isinstance(qid, str) or not qid:
            continue
        sub_qid = item.get("sub_question_id") if isinstance(item.get("sub_question_id"), str) else None
        correctness_map[(qid, sub_qid)] = item

    by_question = {}
    by_sub = {}
    if reference_answers:
        by_question, by_sub = _reference_answer_maps(reference_answers)

    verdict_count = 0

    def _attach(trace_item: Dict[str, Any], qid: str, sub_qid: Optional[str], teacher_review: Optional[Dict[str, Any]]) -> None:
        nonlocal verdict_count
        key_item = correctness_map.get((qid, sub_qid)) or correctness_map.get((qid, None))
        by_answer_key = key_item.get("by_answer_key") if isinstance(key_item, dict) and isinstance(key_item.get("by_answer_key"), bool) else None

        # Robust string matching fallback for math answers / choices / fills
        if by_answer_key is False:
            ref = _find_reference_answer_for_trace(
                qid=qid,
                sub_qid=sub_qid,
                by_question=by_question,
                by_sub=by_sub,
            )
            if isinstance(ref, dict):
                student_val = trace_item.get("student_answer_text") or trace_item.get("answer_text") or ""
                ref_val = ref.get("reference_final_answer") or ref.get("reference_answer_text") or ""
                clean_stud = _clean_math_expression(student_val)
                clean_ref = _clean_math_expression(ref_val)
                if clean_ref and clean_stud == clean_ref:
                    by_answer_key = True
                    if isinstance(key_item, dict):
                        key_item["by_answer_key"] = True
                        key_item["reason"] = ""

        teacher_verdict = _teacher_review_verdict(teacher_review or {})
        legacy_verdict = trace_item.get("is_correct") if isinstance(trace_item.get("is_correct"), bool) else None
        conflict_with_teacher = (
            isinstance(by_answer_key, bool)
            and isinstance(teacher_verdict, bool)
            and by_answer_key != teacher_verdict
        )
        generated_conflict = answer_key_source == "generated" and conflict_with_teacher
        if isinstance(by_answer_key, bool) and not generated_conflict:
            final_verdict = by_answer_key
            source = "answer_key"
            verdict_count += 1
        elif isinstance(teacher_verdict, bool):
            final_verdict = teacher_verdict
            source = "teacher_review_conflict_generated_reference" if generated_conflict else "teacher_review"
            if isinstance(by_answer_key, bool):
                verdict_count += 1
        elif isinstance(legacy_verdict, bool):
            final_verdict = legacy_verdict
            source = "legacy"
        else:
            final_verdict = None
            source = "none"
        correctness = {
            "by_answer_key": by_answer_key,
            "source": source,
            "reference_source": answer_key_source,
            "confidence": key_item.get("confidence") if isinstance(key_item, dict) and isinstance(key_item.get("confidence"), (int, float)) else None,
            "reason": key_item.get("reason") if isinstance(key_item, dict) and isinstance(key_item.get("reason"), str) else "",
            "conflict_with_teacher": conflict_with_teacher,
        }
        trace_item["correctness"] = correctness
        trace_item["is_correct"] = final_verdict if isinstance(final_verdict, bool) else None
        validation = trace_item.get("diagnosis_validation") if isinstance(trace_item.get("diagnosis_validation"), dict) else {}
        validation = dict(validation)
        validation["answer_key_conflict_with_teacher"] = conflict_with_teacher
        if conflict_with_teacher and not (isinstance(validation.get("conflict_reason"), str) and validation.get("conflict_reason")):
            validation["conflict_reason"] = "标准答案判定与教师批改结论冲突"
        trace_item["diagnosis_validation"] = validation

    for answer in answers:
        if not isinstance(answer, dict):
            continue
        qid = answer.get("question_id")
        if not isinstance(qid, str) or not qid:
            continue
        sub_qid = answer.get("sub_question_id") if isinstance(answer.get("sub_question_id"), str) else None
        teacher_review = (
            answer.get("teacher_review")
            if isinstance(answer.get("teacher_review"), dict)
            else teacher_review_by_id.get(qid)
        )
        _attach(answer, qid, sub_qid, teacher_review if isinstance(teacher_review, dict) else None)

    for question in structured_questions_full:
        if not isinstance(question, dict):
            continue
        qid = question.get("question_id")
        if not isinstance(qid, str) or not qid:
            continue
        teacher_review = teacher_review_by_id.get(qid)
        answer_trace = question.get("answer_trace")
        if isinstance(answer_trace, dict):
            if not isinstance(teacher_review, dict):
                teacher_review = answer_trace.get("teacher_review") if isinstance(answer_trace.get("teacher_review"), dict) else None
            _attach(answer_trace, qid, answer_trace.get("sub_question_id") if isinstance(answer_trace.get("sub_question_id"), str) else None, teacher_review if isinstance(teacher_review, dict) else None)
        sub_traces = question.get("sub_traces") if isinstance(question.get("sub_traces"), list) else []
        for sub_trace in sub_traces:
            if not isinstance(sub_trace, dict):
                continue
            sub_review = (
                sub_trace.get("teacher_review")
                if isinstance(sub_trace.get("teacher_review"), dict)
                else teacher_review
            )
            _attach(
                sub_trace,
                qid,
                sub_trace.get("sub_question_id") if isinstance(sub_trace.get("sub_question_id"), str) else None,
                sub_review if isinstance(sub_review, dict) else None,
            )
    return verdict_count


def _normalize_step_analysis_steps(
    raw_steps: Any,
    *,
    include_skill_tags: bool,
) -> List[Dict[str, Any]]:
    if not isinstance(raw_steps, list):
        return []
    output: List[Dict[str, Any]] = []
    for index, raw_step in enumerate(raw_steps, start=1):
        if isinstance(raw_step, dict):
            content = raw_step.get("content") if isinstance(raw_step.get("content"), str) else None
            if not content and isinstance(raw_step.get("step"), str):
                content = raw_step.get("step")
            if not isinstance(content, str) or not content.strip():
                continue
            item: Dict[str, Any] = {
                "step_index": int(raw_step.get("step_index")) if isinstance(raw_step.get("step_index"), (int, float)) else index,
                "content": content.strip(),
            }
            evidence = raw_step.get("evidence") if isinstance(raw_step.get("evidence"), str) else None
            if isinstance(evidence, str) and evidence.strip():
                item["evidence"] = evidence.strip()
            if include_skill_tags:
                tags = raw_step.get("skill_tags") if isinstance(raw_step.get("skill_tags"), list) else []
                item["skill_tags"] = [tag for tag in tags if isinstance(tag, str) and tag.strip()]
            output.append(item)
            continue
        if isinstance(raw_step, str) and raw_step.strip():
            item = {"step_index": index, "content": raw_step.strip()}
            if include_skill_tags:
                item["skill_tags"] = []
            output.append(item)
    return output


def _normalize_blind_diagnosis_payload(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    error_type = raw.get("error_type") if isinstance(raw.get("error_type"), str) else "unknown"
    if error_type not in {"concept", "calculation", "reading", "strategy", "unknown"}:
        error_type = "unknown"
    confidence = raw.get("confidence")
    confidence_value = max(0.0, min(1.0, float(confidence))) if isinstance(confidence, (int, float)) else 0.0
    is_correct_estimate = raw.get("is_correct_estimate") if isinstance(raw.get("is_correct_estimate"), bool) else None
    return {
        "standard_steps": _normalize_step_analysis_steps(raw.get("standard_steps"), include_skill_tags=True),
        "student_steps": _normalize_step_analysis_steps(raw.get("student_steps"), include_skill_tags=False),
        "divergence_point": raw.get("divergence_point") if isinstance(raw.get("divergence_point"), str) else "",
        "error_type": error_type,
        "reason": raw.get("reason") if isinstance(raw.get("reason"), str) else "",
        "evidence_span": raw.get("evidence_span") if isinstance(raw.get("evidence_span"), str) else "",
        "repair_suggestion": raw.get("repair_suggestion") if isinstance(raw.get("repair_suggestion"), str) else "",
        "suggestion": raw.get("suggestion") if isinstance(raw.get("suggestion"), str) else "",
        "is_correct_estimate": is_correct_estimate,
        "confidence": round(confidence_value, 2),
    }


def _build_blind_diagnosis_summary(blind_diagnosis: Dict[str, Any]) -> Dict[str, Any]:
    divergence_point = blind_diagnosis.get("divergence_point") if isinstance(blind_diagnosis.get("divergence_point"), str) else ""
    reason = blind_diagnosis.get("reason") if isinstance(blind_diagnosis.get("reason"), str) else ""
    evidence_span = blind_diagnosis.get("evidence_span") if isinstance(blind_diagnosis.get("evidence_span"), str) else ""
    repair_suggestion = (
        blind_diagnosis.get("repair_suggestion")
        if isinstance(blind_diagnosis.get("repair_suggestion"), str)
        else ""
    )
    suggestion = blind_diagnosis.get("suggestion") if isinstance(blind_diagnosis.get("suggestion"), str) else ""
    error_type = blind_diagnosis.get("error_type") if isinstance(blind_diagnosis.get("error_type"), str) else "unknown"
    return {
        "error_type": error_type,
        "wrong_step": divergence_point,
        "step_reason": reason,
        "step_evidence": evidence_span,
        "step_fix": repair_suggestion or suggestion,
        "reason": reason,
        "evidence": evidence_span,
        "suggestion": suggestion or repair_suggestion,
    }


def _teacher_review_verdict(teacher_review: Dict[str, Any]) -> Optional[bool]:
    if isinstance(teacher_review.get("is_correct"), bool):
        return teacher_review.get("is_correct")
    deducted_score = teacher_review.get("deducted_score")
    if isinstance(deducted_score, (int, float)):
        if float(deducted_score) > 0:
            return False
        if float(deducted_score) == 0:
            return True
    score = teacher_review.get("score")
    max_score = teacher_review.get("max_score")
    if isinstance(score, (int, float)) and isinstance(max_score, (int, float)) and float(max_score) > 0:
        return float(score) >= float(max_score)
    return None


def _build_teacher_review(answer: Dict[str, Any]) -> Dict[str, Any]:
    trace = answer.get("trace") if isinstance(answer.get("trace"), dict) else {}
    confidence = trace.get("confidence") if isinstance(trace.get("confidence"), (int, float)) else None
    return {
        "score": answer.get("score") if isinstance(answer.get("score"), (int, float)) else None,
        "max_score": answer.get("max_score") if isinstance(answer.get("max_score"), (int, float)) else None,
        "deducted_score": answer.get("deducted_score") if isinstance(answer.get("deducted_score"), (int, float)) else None,
        "is_correct": answer.get("is_correct") if isinstance(answer.get("is_correct"), bool) else None,
        "score_source_confidence": round(float(confidence), 2) if isinstance(confidence, (int, float)) else None,
    }


def _build_teacher_review_map(
    answer_contexts: List[Dict[str, Any]],
    teacher_score_answers: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    merged = _merge_and_fill_answers(teacher_score_answers, answer_contexts)
    output: Dict[str, Dict[str, Any]] = {}
    for answer in merged:
        qid = answer.get("question_id")
        if isinstance(qid, str) and qid:
            output[qid] = _build_teacher_review(answer)
    return output


def _build_diagnosis_validation(
    blind_diagnosis: Optional[Dict[str, Any]],
    teacher_review: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    if not isinstance(blind_diagnosis, dict):
        return {
            "validated": None,
            "conflict_type": None,
            "conflict_reason": "缺少学生独立诊断结果，未执行交叉验证",
        }
    blind_verdict = (
        blind_diagnosis.get("is_correct_estimate")
        if isinstance(blind_diagnosis.get("is_correct_estimate"), bool)
        else None
    )
    if blind_verdict is None:
        return {
            "validated": None,
            "conflict_type": None,
            "conflict_reason": "学生独立诊断未形成明确正确性判断",
        }
    teacher_verdict = _teacher_review_verdict(teacher_review or {})
    if teacher_verdict is None:
        return {
            "validated": None,
            "conflict_type": None,
            "conflict_reason": "教师批改信号不足，未执行交叉验证",
        }
    if blind_verdict == teacher_verdict:
        return {
            "validated": True,
            "conflict_type": None,
            "conflict_reason": "",
        }
    student_label = "正确" if blind_verdict else "错误"
    teacher_label = "正确" if teacher_verdict else "错误"
    return {
        "validated": False,
        "conflict_type": "teacher_vs_student",
        "conflict_reason": f"学生独立诊断倾向{student_label}，教师批改结果倾向{teacher_label}",
    }


def _build_blind_diagnosis_item(question: Dict[str, Any], answer: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    qid = question.get("question_id")
    if not isinstance(qid, str) or not qid:
        return None
    student_answer_text = answer.get("student_answer_text") if isinstance(answer.get("student_answer_text"), str) else ""
    answer_text = answer.get("answer_text") if isinstance(answer.get("answer_text"), str) else ""
    steps = answer.get("steps") if isinstance(answer.get("steps"), list) else []
    if not student_answer_text.strip() and not answer_text.strip() and not steps:
        return None
    trace = answer.get("trace") if isinstance(answer.get("trace"), dict) else {}
    return {
        "question_id": qid,
        "question_type": question.get("question_type"),
        "problem_text": _compact_text(question.get("problem_text"), 320),
        "problem_text_full": _compact_text(question.get("problem_text_full"), 700),
        "sub_questions": _compact_sub_questions(question.get("sub_questions")),
        "skill_tags": [tag for tag in (question.get("skill_tags") if isinstance(question.get("skill_tags"), list) else []) if isinstance(tag, str)][:8],
        "student_answer_text": _compact_text(student_answer_text, 520),
        "answer_text": _compact_text(answer_text, 520),
        "steps": _compact_steps(steps, limit=8, text_limit=220),
        "trace_notes": trace.get("notes") if isinstance(trace.get("notes"), str) else "",
    }


def _should_run_blind_diagnosis_for_answer(
    answer: Dict[str, Any],
    teacher_review: Optional[Dict[str, Any]] = None,
    *,
    min_confidence: float = 0.65,
) -> bool:
    if not _has_answer_signal(answer):
        return False
    correctness = answer.get("correctness") if isinstance(answer.get("correctness"), dict) else {}
    if correctness.get("conflict_with_teacher") is True:
        return True
    teacher_review = teacher_review if isinstance(teacher_review, dict) else (
        answer.get("teacher_review") if isinstance(answer.get("teacher_review"), dict) else None
    )
    teacher_verdict = _teacher_review_verdict(teacher_review or {})
    legacy_verdict = answer.get("is_correct") if isinstance(answer.get("is_correct"), bool) else None
    if legacy_verdict is False or teacher_verdict is False:
        return True
    for key in ("deducted_score", "lost_score"):
        value = answer.get(key)
        if isinstance(value, (int, float)) and float(value) > 0:
            return True
    score = answer.get("score")
    max_score = answer.get("max_score")
    if isinstance(score, (int, float)) and isinstance(max_score, (int, float)) and float(max_score) > 0:
        if float(score) < float(max_score):
            return True
        return False
    status = str(answer.get("status") or "").strip().lower()
    if status in {"unclear", "unseen"}:
        return True
    confidence = _answer_confidence(answer)
    if confidence > 0 and confidence < min_confidence:
        return True
    return True


def _diagnosis_priority_score(answer: Dict[str, Any]) -> tuple[int, float, float]:
    correctness = answer.get("correctness") if isinstance(answer.get("correctness"), dict) else {}
    conflict = 1 if correctness.get("conflict_with_teacher") is True else 0
    score = answer.get("score")
    max_score = answer.get("max_score")
    lost_ratio = 0.0
    if isinstance(score, (int, float)) and isinstance(max_score, (int, float)) and float(max_score) > 0:
        lost_ratio = max(0.0, min(1.0, (float(max_score) - float(score)) / float(max_score)))
    for key in ("deducted_score", "lost_score"):
        value = answer.get(key)
        if isinstance(value, (int, float)) and float(value) > 0:
            lost_ratio = max(lost_ratio, min(1.0, float(value) / max(float(max_score) if isinstance(max_score, (int, float)) and float(max_score) > 0 else float(value), 1.0)))
    confidence = _answer_confidence(answer)
    return (conflict, lost_ratio, 1.0 - confidence)


def _apply_diagnosis_fields_to_answers(
    answers: List[Dict[str, Any]],
    structured_questions_full: List[Dict[str, Any]],
    blind_by_id: Dict[str, Dict[str, Any]],
    teacher_review_by_id: Dict[str, Dict[str, Any]],
) -> None:
    for answer in answers:
        qid = answer.get("question_id")
        if not isinstance(qid, str):
            continue
        blind_diagnosis = blind_by_id.get(qid)
        teacher_review = teacher_review_by_id.get(qid) or _build_teacher_review(answer)
        answer["blind_diagnosis"] = blind_diagnosis
        answer["teacher_review"] = teacher_review
        answer["diagnosis_validation"] = _build_diagnosis_validation(blind_diagnosis, teacher_review)
        if isinstance(blind_diagnosis, dict):
            answer["error_analysis"] = _build_blind_diagnosis_summary(blind_diagnosis)
    for item in structured_questions_full:
        qid = item.get("question_id")
        if not isinstance(qid, str):
            continue
        answer_trace = item.get("answer_trace")
        blind_diagnosis = blind_by_id.get(qid)
        teacher_review = teacher_review_by_id.get(qid)
        if isinstance(answer_trace, dict):
            teacher_review = teacher_review or _build_teacher_review(answer_trace)
            answer_trace["blind_diagnosis"] = blind_diagnosis
            answer_trace["teacher_review"] = teacher_review
            answer_trace["diagnosis_validation"] = _build_diagnosis_validation(blind_diagnosis, teacher_review)
            if isinstance(blind_diagnosis, dict):
                answer_trace["error_analysis"] = _build_blind_diagnosis_summary(blind_diagnosis)
        sub_traces = item.get("sub_traces") if isinstance(item.get("sub_traces"), list) else []
        for sub_trace in sub_traces:
            if not isinstance(sub_trace, dict):
                continue
            sub_trace["blind_diagnosis"] = blind_diagnosis
            sub_trace["teacher_review"] = teacher_review or _build_teacher_review(sub_trace)
            sub_trace["diagnosis_validation"] = _build_diagnosis_validation(
                blind_diagnosis,
                sub_trace.get("teacher_review") if isinstance(sub_trace.get("teacher_review"), dict) else teacher_review,
            )
            if isinstance(blind_diagnosis, dict):
                sub_trace["error_analysis"] = _build_blind_diagnosis_summary(blind_diagnosis)


def _build_answer_trace_display(structured_questions_full: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    display_items: List[Dict[str, Any]] = []
    for question in structured_questions_full:
        if not isinstance(question, dict):
            continue
        qid = question.get("question_id")
        if not isinstance(qid, str) or not qid:
            continue

        question_type = question.get("question_type")
        question_tags = question.get("skill_tags") if isinstance(question.get("skill_tags"), list) else []
        question_anchor_text = question.get("question_anchor_text")
        problem_text = question.get("problem_text")
        declared_subs = question.get("sub_questions") if isinstance(question.get("sub_questions"), list) else []
        sub_text_map = {
            sub.get("sub_question_id"): sub.get("sub_text")
            for sub in declared_subs
            if isinstance(sub, dict) and isinstance(sub.get("sub_question_id"), str)
        }

        answer_trace = question.get("answer_trace") if isinstance(question.get("answer_trace"), dict) else None
        sub_traces = [sub for sub in (question.get("sub_traces") or []) if isinstance(sub, dict)]

        question_items: List[Dict[str, Any]] = []
        has_sub_signal = any(_has_answer_signal(sub) for sub in sub_traces)
        if declared_subs and isinstance(answer_trace, dict) and _has_answer_signal(answer_trace) and not has_sub_signal:
            summary = _public_answer_item(answer_trace)
            summary["display_question_id"] = f"{qid}锛堟暣棰橈級"
            summary["parent_question_id"] = qid
            summary["question_anchor_text"] = question_anchor_text
            summary["problem_text"] = problem_text
            summary["sub_question_text"] = None
            summary["is_question_summary"] = True
            if not isinstance(summary.get("question_type"), str) or not summary.get("question_type"):
                summary["question_type"] = question_type
            if not isinstance(summary.get("skill_tags"), list) or not summary.get("skill_tags"):
                summary["skill_tags"] = list(question_tags)
            question_items.append(summary)

        if declared_subs:
            for sub in sub_traces:
                display = dict(sub)
                sub_qid = display.get("sub_question_id") if isinstance(display.get("sub_question_id"), str) else None
                display["display_question_id"] = sub_qid or qid
                display["parent_question_id"] = qid
                display["question_anchor_text"] = question_anchor_text
                display["problem_text"] = problem_text
                display["sub_question_text"] = sub_text_map.get(sub_qid)
                display["is_question_summary"] = False
                if not isinstance(display.get("question_type"), str) or not display.get("question_type"):
                    display["question_type"] = question_type
                if not isinstance(display.get("skill_tags"), list) or not display.get("skill_tags"):
                    display["skill_tags"] = list(question_tags)
                question_items.append(display)
        elif isinstance(answer_trace, dict):
            display = _public_answer_item(answer_trace)
            display["display_question_id"] = qid
            display["parent_question_id"] = qid
            display["question_anchor_text"] = question_anchor_text
            display["problem_text"] = problem_text
            display["sub_question_text"] = None
            display["is_question_summary"] = False
            if not isinstance(display.get("question_type"), str) or not display.get("question_type"):
                display["question_type"] = question_type
            if not isinstance(display.get("skill_tags"), list) or not display.get("skill_tags"):
                display["skill_tags"] = list(question_tags)
            question_items.append(display)

        display_items.extend(question_items)
    return display_items


def _merge_and_fill_answers(
    answer_candidates: List[Dict[str, Any]],
    question_contexts: List[Dict[str, Any]],
    *,
    default_empty_reason_code: str = "no_answer_candidate_mapped",
) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    order: List[str] = []
    context_by_id: Dict[str, Dict[str, Any]] = {}
    for ctx in question_contexts:
        qid = ctx.get("question_id")
        if isinstance(qid, str) and qid:
            order.append(qid)
            context_by_id[qid] = ctx
    for item in answer_candidates:
        qid = item.get("question_id")
        if isinstance(qid, str) and qid in context_by_id:
            grouped.setdefault(qid, []).append(item)

    output: List[Dict[str, Any]] = []
    for qid in order:
        context = context_by_id[qid]
        candidates = grouped.get(qid, [])
        if not candidates:
            output.append(_default_answer_item(context, reason_code=default_empty_reason_code))
            continue

        merged = _default_answer_item(context, reason_code=default_empty_reason_code)
        merged["raw_question_id"] = context.get("raw_question_id")
        best_overall = max(candidates, key=_answer_record_rank)
        best_bundle = _pick_best_candidate(
            candidates,
            lambda item: any(
                (
                    isinstance(item.get("score"), (int, float)),
                    isinstance(item.get("max_score"), (int, float)),
                    isinstance(item.get("deducted_score"), (int, float)),
                    isinstance(item.get("is_correct"), bool),
                )
            ),
        )
        if best_bundle is None:
            best_bundle = best_overall

        status_candidate = _pick_best_candidate(
            candidates,
            lambda item: str(item.get("status") or "") in {"answered", "unclear"},
        )
        if status_candidate is None:
            status_candidate = best_overall

        sub_candidate = _pick_best_candidate(
            candidates,
            lambda item: isinstance(item.get("sub_question_id"), str) and item.get("sub_question_id"),
        )
        text_candidate = _pick_best_candidate(
            candidates,
            lambda item: isinstance(item.get("student_answer_text"), str) and item.get("student_answer_text").strip(),
        )
        option_candidate = _pick_best_candidate(
            candidates,
            lambda item: isinstance(item.get("selected_option"), str) and item.get("selected_option").strip(),
        )
        fill_candidate = _pick_best_candidate(
            candidates,
            lambda item: isinstance(item.get("filled_value"), str) and item.get("filled_value").strip(),
        )

        merged["status"] = status_candidate.get("status") if isinstance(status_candidate.get("status"), str) else "unseen"
        merged["score"] = best_bundle.get("score") if isinstance(best_bundle.get("score"), (int, float)) else None
        merged["max_score"] = best_bundle.get("max_score") if isinstance(best_bundle.get("max_score"), (int, float)) else merged.get("max_score")
        merged["deducted_score"] = (
            best_bundle.get("deducted_score")
            if isinstance(best_bundle.get("deducted_score"), (int, float))
            else None
        )
        if (
            merged["deducted_score"] is None
            and isinstance(merged.get("score"), (int, float))
            and isinstance(merged.get("max_score"), (int, float))
        ):
            deduced = float(merged["max_score"]) - float(merged["score"])
            if deduced >= 0:
                merged["deducted_score"] = deduced
        merged["is_correct"] = best_bundle.get("is_correct") if isinstance(best_bundle.get("is_correct"), bool) else None
        merged["sub_question_id"] = sub_candidate.get("sub_question_id") if sub_candidate is not None else None
        merged["raw_sub_question_id"] = (
            sub_candidate.get("raw_sub_question_id")
            if sub_candidate is not None and isinstance(sub_candidate.get("raw_sub_question_id"), str)
            else None
        )
        merged["selected_option"] = option_candidate.get("selected_option") if option_candidate is not None else None
        merged["filled_value"] = fill_candidate.get("filled_value") if fill_candidate is not None else None
        if _is_choice_or_blank(context.get("question_type")):
            primary_text = (
                text_candidate.get("student_answer_text")
                if text_candidate is not None and isinstance(text_candidate.get("student_answer_text"), str)
                else None
            )
            primary_answer_text = (
                text_candidate.get("answer_text")
                if text_candidate is not None and isinstance(text_candidate.get("answer_text"), str)
                else primary_text
            )
            merged["student_answer_text"] = primary_text
            merged["answer_text"] = primary_answer_text
        else:
            merged["student_answer_text"] = _merge_text_fragments(
                [item.get("student_answer_text") for item in candidates]
            )
            if merged["student_answer_text"] is None and text_candidate is not None:
                merged["student_answer_text"] = text_candidate.get("student_answer_text")
            merged["answer_text"] = _merge_text_fragments(
                [
                    item.get("answer_text") if isinstance(item.get("answer_text"), str) else item.get("student_answer_text")
                    for item in candidates
                ]
            )
            if merged["answer_text"] is None:
                merged["answer_text"] = merged["student_answer_text"]
        merged["steps"] = _merge_step_lists(candidates)
        if not merged["steps"]:
            inferred_steps = _infer_steps_from_answer_text(merged["student_answer_text"], merged["answer_text"])
            if inferred_steps:
                merged["steps"] = inferred_steps
        merged["skill_observations"] = _merge_skill_observations(candidates)
        merged["_source_stage"] = best_bundle.get("_source_stage")
        merged["_page_index"] = best_bundle.get("_page_index")
        merged["_route_page_hint"] = best_bundle.get("_route_page_hint")
        merged["_page_matches_hint"] = best_bundle.get("_page_matches_hint")
        merged["_evidence"] = _merge_text_fragments(
            [item.get("_evidence") for item in candidates]
        ) or best_bundle.get("_evidence") or best_overall.get("_evidence")
        merged["_evidence_blocks"] = _merge_internal_evidence_blocks(candidates)
        merged["_rule_conflicts"] = []

        confidence_values = []
        readability_values = []
        for item in candidates:
            trace = item.get("trace")
            if not isinstance(trace, dict):
                continue
            if isinstance(trace.get("confidence"), (int, float)):
                confidence_values.append(float(trace["confidence"]))
            if isinstance(trace.get("readability"), (int, float)):
                readability_values.append(float(trace["readability"]))
        merged["trace"]["confidence"] = max(confidence_values) if confidence_values else None
        merged["trace"]["readability"] = max(readability_values) if readability_values else None

        scratch_candidate = _pick_best_candidate(
            candidates,
            lambda item: isinstance(item.get("trace"), dict) and isinstance(item["trace"].get("scratchwork"), bool),
        )
        correction_candidate = _pick_best_candidate(
            candidates,
            lambda item: isinstance(item.get("trace"), dict) and isinstance(item["trace"].get("corrections"), bool),
        )
        merged["trace"]["scratchwork"] = _merge_trace_flag(candidates, "scratchwork")
        if merged["trace"]["scratchwork"] is None:
            merged["trace"]["scratchwork"] = (
                scratch_candidate["trace"].get("scratchwork") if scratch_candidate is not None else None
            )
        merged["trace"]["corrections"] = _merge_trace_flag(candidates, "corrections")
        if merged["trace"]["corrections"] is None:
            merged["trace"]["corrections"] = (
                correction_candidate["trace"].get("corrections") if correction_candidate is not None else None
            )
        merged["trace"]["notes"] = _merge_text_fragments(
            [
                item.get("trace", {}).get("notes")
                for item in candidates
                if isinstance(item.get("trace"), dict)
            ]
        )

        merged["_rule_conflicts"] = _answer_rule_conflicts(merged, context)
        if merged["_rule_conflicts"] and merged["status"] == "answered":
            merged["status"] = "unclear"
        if not _has_answer_signal(merged):
            _apply_empty_trace_reason(merged, "candidate_without_signal", overwrite=True)
        output.append(merged)
    return output


def _default_answer_item(
    context: Dict[str, Any],
    *,
    reason_code: str = "no_answer_candidate_mapped",
    note: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "question_id": context.get("question_id"),
        "question_type": _normalize_question_type(context.get("question_type")),
        "skill_tags": context.get("skill_tags") if isinstance(context.get("skill_tags"), list) else [],
        "status": "unseen",
        "score": None,
        "max_score": context.get("max_score") if isinstance(context.get("max_score"), (int, float)) else None,
        "deducted_score": None,
        "is_correct": None,
        "selected_option": None,
        "filled_value": None,
        "student_answer_text": None,
        "answer_text": None,
        "steps": [],
        "skill_observations": [],
        "trace": _build_empty_trace_payload(reason_code=reason_code, note=note),
        "_source_stage": "default",
        "_page_index": context.get("answer_page_hint") if isinstance(context.get("answer_page_hint"), int) else None,
        "_route_page_hint": context.get("answer_page_hint") if isinstance(context.get("answer_page_hint"), int) else None,
        "_page_matches_hint": None,
        "_evidence": None,
        "_rule_conflicts": [],
    }


def _build_candidate_summaries(
    answer_candidates: List[Dict[str, Any]],
    target_question_ids: List[str],
) -> List[Dict[str, Any]]:
    summaries: List[Dict[str, Any]] = []
    for qid in target_question_ids:
        candidates = [
            item
            for item in answer_candidates
            if isinstance(item, dict) and item.get("question_id") == qid
        ]
        candidates.sort(key=_answer_record_rank, reverse=True)
        for item in candidates[:3]:
            summaries.append(
                {
                    "question_id": item.get("question_id"),
                    "sub_question_id": item.get("sub_question_id"),
                    "status": item.get("status"),
                    "score": item.get("score"),
                    "max_score": item.get("max_score"),
                    "deducted_score": item.get("deducted_score"),
                    "is_correct": item.get("is_correct"),
                    "confidence": _answer_confidence(item),
                    "page_index": item.get("_page_index"),
                    "source_stage": item.get("_source_stage"),
                    "evidence": item.get("_evidence"),
                    "rule_conflicts": item.get("_rule_conflicts") if isinstance(item.get("_rule_conflicts"), list) else [],
                }
            )
    return summaries


def _collect_answer_repair_targets(
    structured_questions_full: List[Dict[str, Any]],
    mapping_report: Dict[str, Any],
    *,
    trigger_unseen: bool,
    trigger_unmatched: bool,
    min_answer_confidence_for_skip_repair: float,
) -> List[str]:
    targets: set[str] = set()
    conflict_ids = mapping_report.get("score_conflict_question_ids")
    if isinstance(conflict_ids, list):
        for qid in conflict_ids:
            if isinstance(qid, str) and qid:
                targets.add(qid)
    if trigger_unseen:
        for item in structured_questions_full:
            if not isinstance(item, dict):
                continue
            qid = item.get("question_id")
            if not isinstance(qid, str) or not qid:
                continue
            answer = item.get("answer_trace")
            if not isinstance(answer, dict):
                targets.add(qid)
                continue
            status = answer.get("status")
            if status == "unseen":
                targets.add(qid)
                continue
            if status == "unclear" and _answer_confidence(answer) < min_answer_confidence_for_skip_repair:
                targets.add(qid)
                continue
            if not _has_answer_signal(answer):
                targets.add(qid)
                continue
            if not _is_choice_or_blank(item.get("question_type")):
                sub_traces = item.get("sub_traces")
                if isinstance(sub_traces, list):
                    has_unseen_sub = any(
                        isinstance(sub_item, dict)
                        and str(sub_item.get("status") or "") == "unseen"
                        for sub_item in sub_traces
                    )
                    if has_unseen_sub:
                        targets.add(qid)
    if trigger_unmatched:
        unmatched = mapping_report.get("unmatched_traces")
        if isinstance(unmatched, list):
            for item in unmatched:
                if not isinstance(item, dict):
                    continue
                qid = item.get("question_id")
                canonical = _canonical_question_id(qid)
                if isinstance(canonical, str) and canonical:
                    targets.add(canonical)
    return sorted(targets, key=lambda qid: (0, int(qid[1:])) if re.fullmatch(r"Q\d{1,3}", qid) else (1, qid))


def _build_structured_questions_and_mapping_report(
    questions: List[Dict[str, Any]],
    merged_answers: List[Dict[str, Any]],
    answer_candidates: List[Dict[str, Any]],
    unmatched_traces: List[Dict[str, Any]],
    missing_from_step1: List[str],
    *,
    default_empty_reason_code: str = "no_answer_candidate_mapped",
    question_pass_chunks: int = 0,
    answer_pass_chunks: int = 0,
    route_pass_chunks: int = 0,
    repair_rounds_used: int = 0,
    repaired_questions_count: int = 0,
    route_hinted_count: int = 0,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    question_by_id: Dict[str, Dict[str, Any]] = {}
    for question in questions:
        if not isinstance(question, dict):
            continue
        qid = question.get("question_id")
        if isinstance(qid, str) and qid:
            question_by_id[qid] = question

    answer_by_id: Dict[str, Dict[str, Any]] = {}
    for answer in merged_answers:
        qid = answer.get("question_id")
        if isinstance(qid, str) and qid:
            answer_by_id[qid] = answer

    sub_trace_map: Dict[str, Dict[str, Dict[str, Any]]] = {}
    additional_unmatched: List[Dict[str, Any]] = []
    for item in answer_candidates:
        qid = item.get("question_id")
        if not isinstance(qid, str) or qid not in question_by_id:
            additional_unmatched.append(
                {
                    "question_id": item.get("question_id"),
                    "sub_question_id": item.get("sub_question_id"),
                    "reason": "question_not_in_step1",
                }
            )
            continue
        sub_qid = item.get("sub_question_id")
        if not isinstance(sub_qid, str) or not sub_qid:
            continue
        bucket = sub_trace_map.setdefault(qid, {})
        current = bucket.get(sub_qid)
        if current is None or _answer_record_rank(item) > _answer_record_rank(current):
            bucket[sub_qid] = item

    combined_unmatched = list(unmatched_traces) + additional_unmatched
    unique_unmatched: List[Dict[str, Any]] = []
    seen_unmatched: set[tuple[str, str, str]] = set()
    for item in combined_unmatched:
        qid = item.get("question_id")
        sqid = item.get("sub_question_id")
        reason = item.get("reason")
        qid_text = qid if isinstance(qid, str) else ""
        sqid_text = sqid if isinstance(sqid, str) else ""
        reason_text = reason if isinstance(reason, str) else ""
        key = (qid_text, sqid_text, reason_text)
        if key in seen_unmatched:
            continue
        seen_unmatched.add(key)
        unique_unmatched.append(
            {
                "question_id": qid,
                "sub_question_id": sqid,
                "reason": reason,
            }
        )

    def resolve_unmatched_reason_code(reason: Any, *, is_sub_question: bool) -> Optional[str]:
        if not isinstance(reason, str):
            return None
        if reason == "question_id_not_in_step1_or_invalid":
            return "sub_question_unmatched_in_structuring" if is_sub_question else "question_id_unmatched_in_structuring"
        return None

    unmatched_reason_by_question: Dict[str, str] = {}
    unmatched_reason_by_sub_question: Dict[tuple[str, str], str] = {}
    for item in unique_unmatched:
        qid = item.get("question_id")
        sqid = item.get("sub_question_id")
        reason = item.get("reason")
        if isinstance(qid, str) and qid:
            if isinstance(sqid, str) and sqid:
                reason_code = resolve_unmatched_reason_code(reason, is_sub_question=True)
                if isinstance(reason_code, str):
                    unmatched_reason_by_sub_question.setdefault((qid, sqid), reason_code)
            else:
                reason_code = resolve_unmatched_reason_code(reason, is_sub_question=False)
                if isinstance(reason_code, str):
                    unmatched_reason_by_question.setdefault(qid, reason_code)

    structured_questions_full: List[Dict[str, Any]] = []
    mapped_questions = 0
    sub_question_mapped_count = 0
    for question in questions:
        if not isinstance(question, dict):
            continue
        item = dict(question)
        qid = item.get("question_id")
        if not isinstance(qid, str):
            continue
        answer_trace = answer_by_id.get(qid)
        if answer_trace is None:
            answer_trace = _default_answer_item(
                item,
                reason_code=unmatched_reason_by_question.get(qid, default_empty_reason_code),
            )
        elif not _has_answer_signal(answer_trace):
            _apply_empty_trace_reason(
                answer_trace,
                unmatched_reason_by_question.get(qid, default_empty_reason_code),
                overwrite=True,
            )
        if _has_answer_signal(answer_trace):
            mapped_questions += 1
        sub_entries_by_id = dict(sub_trace_map.get(qid) or {})
        if not _is_choice_or_blank(item.get("question_type")):
            declared_subs = item.get("sub_questions") if isinstance(item.get("sub_questions"), list) else []
            for sub in declared_subs:
                if not isinstance(sub, dict):
                    continue
                sub_qid = sub.get("sub_question_id")
                if not isinstance(sub_qid, str) or not sub_qid:
                    continue
                if sub_qid not in sub_entries_by_id:
                    sub_entries_by_id[sub_qid] = _default_sub_trace_item(
                        item,
                        sub,
                        reason_code=unmatched_reason_by_sub_question.get(
                            (qid, sub_qid),
                            "sub_question_no_answer_candidate",
                        ),
                    )
        sub_entries = list(sub_entries_by_id.values())
        sub_entries.sort(key=lambda x: str(x.get("sub_question_id") or ""))
        sub_entries = _split_parent_steps_to_sub_traces(item, answer_trace, sub_entries)
        for sub_entry in sub_entries:
            if not isinstance(sub_entry, dict):
                continue
            sub_qid = sub_entry.get("sub_question_id") if isinstance(sub_entry.get("sub_question_id"), str) else None
            reason_code = (
                unmatched_reason_by_sub_question.get((qid, sub_qid))
                if isinstance(sub_qid, str)
                else None
            )
            if not isinstance(reason_code, str):
                reason_code = "sub_question_no_answer_candidate"
            _apply_empty_trace_reason(sub_entry, reason_code, overwrite=True)
        sub_question_mapped_count += sum(1 for sub in sub_entries if _has_answer_signal(sub))
        item["answer_trace"] = _public_answer_item(answer_trace)
        item["sub_traces"] = [_public_answer_item(sub) for sub in sub_entries]
        structured_questions_full.append(item)

    score_conflict_question_ids = sorted(
        [
            answer.get("question_id")
            for answer in merged_answers
            if isinstance(answer, dict)
            and isinstance(answer.get("question_id"), str)
            and isinstance(answer.get("_rule_conflicts"), list)
            and bool(answer.get("_rule_conflicts"))
        ],
        key=lambda qid: (0, int(qid[1:])) if isinstance(qid, str) and re.fullmatch(r"Q\d{1,3}", qid) else (1, str(qid)),
    )
    mapping_report = {
        "total_questions": len(structured_questions_full),
        "mapped_questions": mapped_questions,
        "missing_from_step1": missing_from_step1,
        "unmatched_traces": unique_unmatched,
        "sub_question_mapped_count": sub_question_mapped_count,
        "question_pass_chunks": question_pass_chunks,
        "answer_pass_chunks": answer_pass_chunks,
        "route_pass_chunks": route_pass_chunks,
        "repair_rounds_used": repair_rounds_used,
        "repaired_questions_count": repaired_questions_count,
        "route_hinted_count": route_hinted_count,
        "score_conflict_count": len(score_conflict_question_ids),
        "score_conflict_question_ids": score_conflict_question_ids,
    }
    return structured_questions_full, mapping_report


def _refresh_answer_mapping(
    *,
    questions: List[Dict[str, Any]],
    answer_contexts: List[Dict[str, Any]],
    raw_answers: List[Dict[str, Any]],
    unmatched_answer_traces: List[Dict[str, Any]],
    missing_from_step1: List[str],
    default_empty_reason_code: str = "no_answer_candidate_mapped",
    question_pass_chunks: int,
    answer_pass_chunks: int,
    route_pass_chunks: int,
    repair_rounds_used: int,
    repaired_questions_count: int,
    route_hinted_count: int,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    answers = _merge_and_fill_answers(
        raw_answers,
        answer_contexts,
        default_empty_reason_code=default_empty_reason_code,
    )
    structured_questions_full, mapping_report = _build_structured_questions_and_mapping_report(
        questions=questions,
        merged_answers=answers,
        answer_candidates=raw_answers,
        unmatched_traces=unmatched_answer_traces,
        missing_from_step1=missing_from_step1,
        default_empty_reason_code=default_empty_reason_code,
        question_pass_chunks=question_pass_chunks,
        answer_pass_chunks=answer_pass_chunks,
        route_pass_chunks=route_pass_chunks,
        repair_rounds_used=repair_rounds_used,
        repaired_questions_count=repaired_questions_count,
        route_hinted_count=route_hinted_count,
    )
    return answers, structured_questions_full, mapping_report


def _collect_frontend_visible_main_question_ids(
    questions: List[Dict[str, Any]],
    answer_trace_display: List[Dict[str, Any]],
) -> set[str]:
    visible_main_ids: set[str] = set()
    for question in questions:
        if not isinstance(question, dict):
            continue
        if _is_choice_question_type(question.get("question_type")):
            continue
        main_id, _ = _extract_main_and_sub_ids(question.get("question_id"))
        if isinstance(main_id, str) and main_id:
            visible_main_ids.add(main_id)

    for answer in answer_trace_display:
        if not isinstance(answer, dict):
            continue
        if _is_choice_question_type(answer.get("question_type")):
            continue
        for key in ("parent_question_id", "question_id", "sub_question_id", "display_question_id"):
            main_id, _ = _extract_main_and_sub_ids(answer.get(key))
            if isinstance(main_id, str) and main_id:
                visible_main_ids.add(main_id)
    return visible_main_ids


def _filter_profile_literacy_evidence_by_visible_questions(
    profile_data: Dict[str, Any],
    visible_main_question_ids: set[str],
) -> Dict[str, Any]:
    if not isinstance(profile_data, dict):
        return {}
    if not visible_main_question_ids:
        return profile_data

    literacy = profile_data.get("literacy")
    if not isinstance(literacy, list):
        return profile_data

    for item in literacy:
        if not isinstance(item, dict):
            continue
        evidence_raw = item.get("evidence")
        if not isinstance(evidence_raw, list):
            continue
        filtered: List[str] = []
        seen: set[str] = set()
        for evidence in evidence_raw:
            if not isinstance(evidence, str):
                continue
            token = evidence.strip()
            if not token:
                continue
            main_id, _ = _extract_main_and_sub_ids(token)
            if not isinstance(main_id, str) or not main_id:
                continue
            if main_id not in visible_main_question_ids:
                continue
            if token in seen:
                continue
            seen.add(token)
            filtered.append(token)
        item["evidence"] = filtered
    return profile_data


def _match_profile_literacy_evidence(
    literacy_id: str,
    questions: List[Dict[str, Any]],
) -> List[str]:
    keyword_map = {
        "number_sense": ["数量", "数", "估算", "比大小"],
        "measurement_sense": ["长度", "面积", "体积", "单位", "测量", "厘米", "米", "千克"],
        "symbol_awareness": ["方程", "式", "字母", "符号", "代数"],
        "operation_ability": ["计算", "化简", "解方程", "求值", "运算"],
        "geometric_intuition": ["图形", "几何", "三角形", "圆", "直线", "角"],
        "spatial_concept": ["立体", "展开图", "位置", "旋转", "平移", "空间"],
        "reasoning_awareness": ["证明", "推理", "判断", "为什么", "说明"],
        "data_awareness": ["统计", "数据", "概率", "平均数", "条形图", "折线图"],
        "model_awareness": ["建模", "规律", "函数", "关系式", "列式"],
        "application_awareness": ["实际", "应用", "生活", "情境", "解决问题"],
        "innovation_awareness": ["探究", "猜想", "规律", "开放", "方案"],
    }
    keywords = keyword_map.get(literacy_id, [])
    matches: List[str] = []
    for question in questions:
        if not isinstance(question, dict):
            continue
        qid = question.get("question_id")
        if not isinstance(qid, str) or not qid:
            continue
        text_parts: List[str] = []
        for key in ("problem_text", "problem_text_full", "question_anchor_text"):
            value = question.get(key)
            if isinstance(value, str) and value.strip():
                text_parts.append(value.strip())
        for tag in question.get("skill_tags", []):
            if isinstance(tag, str) and tag.strip():
                text_parts.append(tag.strip())
        combined = " ".join(text_parts)
        if any(keyword in combined for keyword in keywords):
            matches.append(qid)
    return matches[:3]


def _build_profile_literacy_fallback(
    *,
    questions: List[Dict[str, Any]],
    answers: List[Dict[str, Any]],
    avg_ratio: float,
) -> List[Dict[str, Any]]:
    error_profile = {"concept": 0, "calculation": 0, "reading": 0, "strategy": 0}
    for answer in answers:
        if not isinstance(answer, dict):
            continue
        analysis = answer.get("error_analysis") if isinstance(answer.get("error_analysis"), dict) else {}
        error_type = analysis.get("error_type")
        if isinstance(error_type, str) and error_type in error_profile:
            error_profile[error_type] += 1

    literacy_items: List[Dict[str, Any]] = []
    for item in PROFILE_LITERACY_DIMENSIONS:
        literacy_id = item["literacy_id"]
        evidence = _match_profile_literacy_evidence(literacy_id, questions)
        value = avg_ratio
        if literacy_id == "operation_ability":
            value = max(0.0, avg_ratio - 0.12 * min(3, error_profile["calculation"]))
        elif literacy_id == "symbol_awareness":
            value = max(0.0, avg_ratio - 0.08 * min(3, error_profile["concept"]))
        elif literacy_id == "reasoning_awareness":
            value = max(0.0, avg_ratio - 0.08 * min(3, error_profile["strategy"]))
        elif literacy_id == "application_awareness":
            value = min(1.0, avg_ratio + 0.05) if evidence else max(0.0, avg_ratio - 0.05)
        elif literacy_id in {"geometric_intuition", "spatial_concept", "data_awareness", "model_awareness"}:
            value = min(1.0, avg_ratio + 0.03) if evidence else max(0.0, avg_ratio - 0.02)
        elif literacy_id == "innovation_awareness":
            value = max(0.0, min(1.0, avg_ratio - 0.03 + (0.04 if evidence else 0.0)))
        value = max(0.0, min(1.0, value))
        if value >= 0.75:
            level = "high"
        elif value >= 0.45:
            level = "medium"
        else:
            level = "low"
        reason = (
            f"结合相关题目的得分稳定性与作答表现，当前{item['name']}表现为{level}。"
            if evidence
            else f"相关直接证据较少，当前{item['name']}先按整体作答稳定性估计为{level}。"
        )
        suggestion = f"围绕{item['name']}对应题型做1-2组专项训练，并在复盘时总结方法与易错点。"
        literacy_items.append(
            {
                "literacy_id": literacy_id,
                "name": item["name"],
                "definition": item["definition"],
                "value": round(value, 2),
                "level": level,
                "evidence": evidence,
                "reason": reason,
                "suggestion": suggestion,
            }
        )
    return literacy_items


HARNESS_STAGE_QUESTION_ANALYSIS = HarnessStageSpec(
    name="question_analysis", mode="json", expected_list_key=expected_list_key("question_analysis")
)
HARNESS_STAGE_ANSWER_RAW_TRACE = HarnessStageSpec(name="answer_trace_raw", mode="text")
HARNESS_STAGE_ANSWER_STRUCTURING = HarnessStageSpec(
    name="answer_structuring", mode="json", expected_list_key=expected_list_key("answer_structuring")
)
HARNESS_STAGE_ANSWER_STRUCT_AND_ALIGN = HarnessStageSpec(
    name="answer_struct_and_align", mode="json", expected_list_key=expected_list_key("answer_struct_and_align")
)
HARNESS_STAGE_ANSWER_ALIGNMENT = HarnessStageSpec(
    name="answer_alignment", mode="json", expected_list_key=expected_list_key("answer_alignment")
)
HARNESS_STAGE_ANSWER_SCORE = HarnessStageSpec(
    name="answer_score", mode="json", expected_list_key=expected_list_key("answer_score")
)
HARNESS_STAGE_REFERENCE_ANSWER_EXTRACT = HarnessStageSpec(
    name="reference_answer_extract",
    mode="json",
    profile_role="text",
    expected_list_key=expected_list_key("reference_answer_extract"),
)
HARNESS_STAGE_REFERENCE_ANSWER_GENERATE = HarnessStageSpec(
    name="reference_answer_generate",
    mode="json",
    profile_role="vision",
    expected_list_key=expected_list_key("reference_answer_generate"),
)
HARNESS_STAGE_ANSWER_KEY_CORRECTNESS = HarnessStageSpec(
    name="answer_key_correctness",
    mode="json",
    profile_role="text",
    expected_list_key=expected_list_key("answer_key_correctness"),
)
HARNESS_STAGE_BLIND_DIAGNOSIS = HarnessStageSpec(
    name="blind_step_analysis",
    mode="json",
    profile_role="text",
    expected_list_key=expected_list_key("blind_step_analysis"),
)
HARNESS_STAGE_PROFILE = HarnessStageSpec(name="student_profile", mode="json", profile_role="text")


class DemoService:
    def __init__(
        self,
        config_path: Path,
        profile_name: Optional[str],
        keyword_path: Path,
        *,
        mock_mode: bool = False,
    ):
        self.mock_mode = mock_mode
        self.config_path = config_path
        self.keyword_path = keyword_path
        self.literacy_mapping_path = Path("literacy_mapping.json")
        self.profile = None if mock_mode else _load_llm_profile(config_path, profile_name)
        self.text_profile = self.profile
        self.profile_name = (
            self.profile.get("name")
            if isinstance(self.profile, dict) and isinstance(self.profile.get("name"), str)
            else None
        )
        self.timeout_sec = 120
        self.max_retries = 2
        self.backoff_base_sec = 1.5
        self.min_interval_sec = 0.0
        self.paper_batch_size = 1
        self.answer_batch_size = 1
        self.question_page_batch_size = 1
        self.max_tokens = 8192
        self.use_env_proxy = True
        self.question_chunk_size = 4
        self.reference_answer_chunk_size = 4
        self.score_chunk_size = 6
        self.answer_chunk_size = 8
        self.answer_structuring_chunk_size = 4
        self.objective_chunk_size = 8
        self.subjective_chunk_size = 2
        self.question_full_discovery_enabled = True
        self.knowledge_tagging_mode = "normal"
        self.paper_concurrency = 8
        self.answer_concurrency = 8
        self.text_profile_name = "text_analysis"
        defaults_payload = self._load_llm_defaults_config()
        configured_text_profile = defaults_payload.get("text_profile")
        if isinstance(configured_text_profile, str) and configured_text_profile.strip():
            self.text_profile_name = configured_text_profile.strip()
        self.subjective_question_types = {"solution", "application", "unknown"}
        self.max_repair_rounds = 0
        self.repair_trigger_unseen = True
        self.repair_trigger_unmatched = True
        self.min_answer_confidence_for_skip_repair = 0.75
        self.answer_segmentation_enabled = True
        self.answer_segment_weights = Path("major_seg_tool") / "weights" / "best.pt"
        self.answer_segment_imgsz = 640
        self.answer_segment_conf = 0.25
        self.answer_segment_iou = 0.7
        self.answer_segment_device: Optional[str] = None
        self.answer_segment_include_student_id = False
        self.answer_segment_margin_px = 4
        self.answer_segment_save_crops = True
        self.answer_segment_crop_output_dir = Path("outputs") / "answer_sheet_crops"
        self.answer_trace_save_debug_json = True
        self.answer_trace_debug_output_dir = Path("outputs") / "answer_trace_debug"
        self.debug_save_all_stages = True
        self.debug_stage_output_dir = Path("outputs") / "stage_debug"
        self.blind_diagnosis_enabled = True
        self.blind_diagnosis_max_items = 0
        self.profile_mode = "llm"
        self.teacher_signal_usage = "validate_only"
        self.review_mark_filter_mode = "off"
        self.pdf_render_dpi = 144
        self.pdf_max_pages = 0
        self._answer_segmenter: Optional[Any] = None
        self._answer_segmenter_init_error: Optional[str] = None
        self._mineru_client: Optional[MinerUStandardClient] = None
        self._mineru_client_init_error: Optional[str] = None
        self._debug_active_run_dir: Optional[Path] = None
        self._debug_harness_seq: int = 0
        if self.profile is not None:
            timeout = self.profile.get("timeout_sec", 120)
            retries = self.profile.get("max_retries", 2)
            backoff = self.profile.get("backoff_base_sec", 1.5)
            interval = self.profile.get("min_interval_sec", 0.0)
            paper_batch_size = self.profile.get("paper_batch_size", 1)
            answer_batch_size = self.profile.get("answer_batch_size", 1)
            question_page_batch_size = self.profile.get("question_page_batch_size", 1)
            max_tokens = self.profile.get("max_tokens", 600)
            use_env_proxy = self.profile.get("use_env_proxy", True)
            question_chunk_size = self.profile.get("question_chunk_size", 8)
            reference_answer_chunk_size = self.profile.get("reference_answer_chunk_size")
            score_chunk_size = self.profile.get("score_chunk_size", 3)
            answer_chunk_size = self.profile.get("answer_chunk_size", 8)
            answer_structuring_chunk_size = self.profile.get("answer_structuring_chunk_size", 4)
            objective_chunk_size = self.profile.get("objective_chunk_size", 8)
            subjective_chunk_size = self.profile.get("subjective_chunk_size", 2)
            question_full_discovery_enabled = self.profile.get("question_full_discovery_enabled", True)
            knowledge_tagging_mode = self.profile.get("knowledge_tagging_mode", "normal")
            paper_concurrency = self.profile.get("paper_concurrency", 4)
            answer_concurrency = self.profile.get("answer_concurrency", 4)
            text_profile_name = self.profile.get("text_profile", "text_analysis")
            subjective_question_types = self.profile.get("subjective_question_types", ["solution", "application", "unknown"])
            max_repair_rounds = self.profile.get("max_repair_rounds", 1)
            repair_trigger_unseen = self.profile.get("repair_trigger_unseen", True)
            repair_trigger_unmatched = self.profile.get("repair_trigger_unmatched", True)
            min_answer_confidence_for_skip_repair = self.profile.get("min_answer_confidence_for_skip_repair", 0.75)
            answer_segmentation_enabled = self.profile.get("answer_segmentation_enabled", True)
            answer_segment_weights = self.profile.get("answer_segment_weights", str(self.answer_segment_weights))
            answer_segment_imgsz = self.profile.get("answer_segment_imgsz", 640)
            answer_segment_conf = self.profile.get("answer_segment_conf", 0.25)
            answer_segment_iou = self.profile.get("answer_segment_iou", 0.7)
            answer_segment_device = self.profile.get("answer_segment_device")
            answer_segment_include_student_id = self.profile.get("answer_segment_include_student_id", False)
            answer_segment_margin_px = self.profile.get("answer_segment_margin_px", 4)
            answer_segment_save_crops = self.profile.get("answer_segment_save_crops", True)
            answer_segment_crop_output_dir = self.profile.get(
                "answer_segment_crop_output_dir",
                str(self.answer_segment_crop_output_dir),
            )
            answer_trace_save_debug_json = self.profile.get("answer_trace_save_debug_json", True)
            answer_trace_debug_output_dir = self.profile.get(
                "answer_trace_debug_output_dir",
                str(self.answer_trace_debug_output_dir),
            )
            blind_diagnosis_enabled = self.profile.get("blind_diagnosis_enabled", True)
            blind_diagnosis_max_items = self.profile.get("blind_diagnosis_max_items", 0)
            profile_mode = self.profile.get("profile_mode", "llm")
            teacher_signal_usage = self.profile.get("teacher_signal_usage", "validate_only")
            review_mark_filter_mode = self.profile.get("review_mark_filter_mode", "off")
            pdf_render_dpi = self.profile.get("pdf_render_dpi", 144)
            pdf_max_pages = self.profile.get("pdf_max_pages", 0)
            self.timeout_sec = int(timeout) if isinstance(timeout, (int, float, str)) else 120
            self.max_retries = int(retries) if isinstance(retries, (int, float, str)) else 2
            self.backoff_base_sec = float(backoff) if isinstance(backoff, (int, float, str)) else 1.5
            self.min_interval_sec = float(interval) if isinstance(interval, (int, float, str)) else 0.0
            self.paper_batch_size = int(paper_batch_size) if isinstance(paper_batch_size, (int, float, str)) else 1
            if self.paper_batch_size <= 0:
                self.paper_batch_size = 1
            self.answer_batch_size = int(answer_batch_size) if isinstance(answer_batch_size, (int, float, str)) else 1
            if self.answer_batch_size <= 0:
                self.answer_batch_size = 1
            self.question_page_batch_size = (
                int(question_page_batch_size) if isinstance(question_page_batch_size, (int, float, str)) else 1
            )
            if self.question_page_batch_size <= 0:
                self.question_page_batch_size = 1
            self.max_tokens = int(max_tokens) if isinstance(max_tokens, (int, float, str)) else 600
            if self.max_tokens <= 0:
                self.max_tokens = 600
            self.use_env_proxy = _as_bool(use_env_proxy, True)
            self.question_chunk_size = int(question_chunk_size) if isinstance(question_chunk_size, (int, float, str)) else 8
            if self.question_chunk_size <= 0:
                self.question_chunk_size = 8
            self.reference_answer_chunk_size = (
                int(reference_answer_chunk_size)
                if isinstance(reference_answer_chunk_size, (int, float, str))
                else min(self.question_chunk_size, 4)
            )
            if self.reference_answer_chunk_size <= 0:
                self.reference_answer_chunk_size = min(self.question_chunk_size, 4)
            self.score_chunk_size = int(score_chunk_size) if isinstance(score_chunk_size, (int, float, str)) else 3
            if self.score_chunk_size <= 0:
                self.score_chunk_size = 3
            self.answer_chunk_size = int(answer_chunk_size) if isinstance(answer_chunk_size, (int, float, str)) else 8
            if self.answer_chunk_size <= 0:
                self.answer_chunk_size = 8
            self.answer_structuring_chunk_size = (
                int(answer_structuring_chunk_size)
                if isinstance(answer_structuring_chunk_size, (int, float, str))
                else 4
            )
            if self.answer_structuring_chunk_size <= 0:
                self.answer_structuring_chunk_size = 4
            self.objective_chunk_size = int(objective_chunk_size) if isinstance(objective_chunk_size, (int, float, str)) else 8
            if self.objective_chunk_size <= 0:
                self.objective_chunk_size = 8
            self.subjective_chunk_size = int(subjective_chunk_size) if isinstance(subjective_chunk_size, (int, float, str)) else 2
            if self.subjective_chunk_size <= 0:
                self.subjective_chunk_size = 2
            self.question_full_discovery_enabled = _as_bool(question_full_discovery_enabled, True)
            if isinstance(knowledge_tagging_mode, str) and knowledge_tagging_mode.strip().lower() in {"normal", "fast", "off"}:
                self.knowledge_tagging_mode = knowledge_tagging_mode.strip().lower()
            self.paper_concurrency = int(paper_concurrency) if isinstance(paper_concurrency, (int, float, str)) else 4
            if self.paper_concurrency <= 0:
                self.paper_concurrency = 4
            self.answer_concurrency = int(answer_concurrency) if isinstance(answer_concurrency, (int, float, str)) else 4
            if self.answer_concurrency <= 0:
                self.answer_concurrency = 4
            if isinstance(text_profile_name, str) and text_profile_name.strip():
                self.text_profile_name = text_profile_name.strip()
            if isinstance(subjective_question_types, list):
                normalized_subjective = {
                    _normalize_question_type(item)
                    for item in subjective_question_types
                    if isinstance(item, str) and _normalize_question_type(item)
                }
                if normalized_subjective:
                    self.subjective_question_types = normalized_subjective
            self.max_repair_rounds = int(max_repair_rounds) if isinstance(max_repair_rounds, (int, float, str)) else 1
            if self.max_repair_rounds < 0:
                self.max_repair_rounds = 0
            self.repair_trigger_unseen = _as_bool(repair_trigger_unseen, True)
            self.repair_trigger_unmatched = _as_bool(repair_trigger_unmatched, True)
            if isinstance(min_answer_confidence_for_skip_repair, (int, float, str)):
                self.min_answer_confidence_for_skip_repair = max(
                    0.0,
                    min(1.0, float(min_answer_confidence_for_skip_repair)),
                )
            self.answer_segmentation_enabled = _as_bool(answer_segmentation_enabled, True)
            if isinstance(answer_segment_weights, str) and answer_segment_weights.strip():
                self.answer_segment_weights = Path(answer_segment_weights.strip())
            if isinstance(answer_segment_imgsz, (int, float, str)):
                self.answer_segment_imgsz = max(128, int(answer_segment_imgsz))
            if isinstance(answer_segment_conf, (int, float, str)):
                self.answer_segment_conf = max(0.01, min(0.99, float(answer_segment_conf)))
            if isinstance(answer_segment_iou, (int, float, str)):
                self.answer_segment_iou = max(0.05, min(0.99, float(answer_segment_iou)))
            if isinstance(answer_segment_device, str) and answer_segment_device.strip():
                self.answer_segment_device = answer_segment_device.strip()
            self.answer_segment_include_student_id = _as_bool(answer_segment_include_student_id, False)
            if isinstance(answer_segment_margin_px, (int, float, str)):
                self.answer_segment_margin_px = max(0, int(float(answer_segment_margin_px)))
            self.answer_segment_save_crops = _as_bool(answer_segment_save_crops, True)
            if isinstance(answer_segment_crop_output_dir, str) and answer_segment_crop_output_dir.strip():
                self.answer_segment_crop_output_dir = Path(answer_segment_crop_output_dir.strip())
            self.answer_trace_save_debug_json = _as_bool(answer_trace_save_debug_json, True)
            if isinstance(answer_trace_debug_output_dir, str) and answer_trace_debug_output_dir.strip():
                self.answer_trace_debug_output_dir = Path(answer_trace_debug_output_dir.strip())
            debug_save_all_stages = self.profile.get("debug_save_all_stages", True)
            debug_stage_output_dir = self.profile.get("debug_stage_output_dir", str(self.debug_stage_output_dir))
            self.debug_save_all_stages = _as_bool(debug_save_all_stages, True)
            if isinstance(debug_stage_output_dir, str) and debug_stage_output_dir.strip():
                self.debug_stage_output_dir = Path(debug_stage_output_dir.strip())
            self.blind_diagnosis_enabled = _as_bool(blind_diagnosis_enabled, True)
            self.blind_diagnosis_max_items = (
                int(blind_diagnosis_max_items)
                if isinstance(blind_diagnosis_max_items, (int, float, str))
                else 0
            )
            if self.blind_diagnosis_max_items < 0:
                self.blind_diagnosis_max_items = 0
            if isinstance(profile_mode, str) and profile_mode.strip().lower() in {"llm", "rule_first", "rule_only"}:
                self.profile_mode = profile_mode.strip().lower()
            if isinstance(teacher_signal_usage, str) and teacher_signal_usage.strip():
                normalized_teacher_signal_usage = teacher_signal_usage.strip().lower()
                if normalized_teacher_signal_usage in {"validate_only", "legacy"}:
                    self.teacher_signal_usage = normalized_teacher_signal_usage
            if isinstance(review_mark_filter_mode, str) and review_mark_filter_mode.strip():
                normalized_filter_mode = review_mark_filter_mode.strip().lower()
                if normalized_filter_mode in {"off", "red_mask"}:
                    self.review_mark_filter_mode = normalized_filter_mode
            if isinstance(pdf_render_dpi, (int, float, str)):
                self.pdf_render_dpi = max(72, int(float(pdf_render_dpi)))
            if isinstance(pdf_max_pages, (int, float, str)):
                self.pdf_max_pages = max(0, int(float(pdf_max_pages)))
        if not mock_mode and self.profile is not None and self.text_profile_name != self.profile.get("name"):
            try:
                self.text_profile = _load_llm_profile(config_path, self.text_profile_name)
            except Exception:
                self.text_profile = self.profile
        self.graph = _load_key_word_payload(keyword_path)
        self.literacy_mapping = _load_literacy_mapping_payload(self.literacy_mapping_path)
        self._profile_cache: Dict[str, Dict[str, Any]] = {}
        if isinstance(self.profile_name, str) and self.profile_name:
            self._profile_cache[self.profile_name] = dict(self.profile or {})
        if isinstance(self.text_profile, dict) and isinstance(self.text_profile.get("name"), str):
            self._profile_cache[str(self.text_profile["name"])] = dict(self.text_profile)
        if not isinstance(self.graph, dict):
            self.graph = {"nodes": []}
        if not isinstance(self.graph.get("nodes"), list):
            self.graph["nodes"] = []
        self._langchain_agents: Dict[str, LangChainAgentRuntime] = {}
        self._agent_harness = AgentHarness(
            default_max_tokens=self.max_tokens,
            default_use_env_proxy=self.use_env_proxy,
            # Resolve through `self` at call time so instance-level patches and
            # late-bound overrides still take effect after harness construction.
            should_use_langchain_runtime=lambda profile: self._should_use_langchain_runtime(profile),
            get_langchain_agent=lambda profile: self._get_langchain_agent(profile),
            normalize_json_payload=lambda text, expected_list_key: _normalize_llm_json_payload(
                text,
                expected_list_key=expected_list_key,
            ),
            legacy_json_caller=_call_llm_json,
            legacy_text_caller=_call_llm_text,
        )

    @property
    def nodes(self) -> List[Dict[str, Any]]:
        return self.graph["nodes"]  # type: ignore[return-value]

    def _known_map(self) -> Dict[str, Dict[str, Any]]:
        known: Dict[str, Dict[str, Any]] = {}
        for node in self.nodes:
            if isinstance(node, dict) and isinstance(node.get("id"), str):
                known[node["id"]] = node
        return known

    def _save_graph(self) -> None:
        self.keyword_path.write_text(json.dumps(self.graph, ensure_ascii=False, indent=2), encoding="utf-8")

    def _log_progress(self, stage: str, event: str, **extra: Any) -> None:
        extra_parts = []
        for key, value in extra.items():
            if value is None:
                continue
            extra_parts.append(f"{key}={value}")
        suffix = f" | {' '.join(extra_parts)}" if extra_parts else ""
        _terminal_log(f"[demo.progress] stage={stage} event={event}{suffix}")

    def _build_skill_alias_map(self) -> Dict[str, str]:
        alias_map: Dict[str, str] = {}
        for node in self.nodes:
            if not isinstance(node, dict):
                continue
            node_id = node.get("id")
            if not isinstance(node_id, str) or not node_id.strip():
                continue
            short_name = node.get("short_name")
            if not isinstance(short_name, str) or not short_name.strip():
                name = node.get("name")
                if isinstance(name, str) and name.strip():
                    short_name = name
                else:
                    short_name = node_id
            alias_map[node_id] = short_name.strip()
        return alias_map

    def _load_openai_profiles_config(self) -> Dict[str, Dict[str, Any]]:
        try:
            payload = _read_llm_config_payload(self.config_path)
        except Exception:
            return {}
        profiles = payload.get("openai_profiles")
        if not isinstance(profiles, dict):
            return {}
        output: Dict[str, Dict[str, Any]] = {}
        for name, item in profiles.items():
            if not isinstance(name, str) or not name.strip() or not isinstance(item, dict):
                continue
            output[name.strip()] = item
        return output

    def _load_llm_defaults_config(self) -> Dict[str, Any]:
        try:
            payload = _read_llm_config_payload(self.config_path)
        except Exception:
            return {}
        defaults = payload.get("defaults")
        return defaults if isinstance(defaults, dict) else {}

    @staticmethod
    def _profile_option_item(name: str, profile: Dict[str, Any]) -> Dict[str, Any]:
        role_raw = profile.get("profile_role")
        role = (
            role_raw.strip().lower()
            if isinstance(role_raw, str) and role_raw.strip().lower() in {"vision", "text", "both"}
            else "both"
        )
        text_profile = profile.get("text_profile")
        return {
            "name": name,
            "model": profile.get("model") if isinstance(profile.get("model"), str) else "",
            "provider": profile.get("provider") if isinstance(profile.get("provider"), str) else "openai_compatible",
            "base_url": profile.get("base_url") if isinstance(profile.get("base_url"), str) else "",
            "runtime": profile.get("runtime") if isinstance(profile.get("runtime"), str) else "legacy",
            "profile_role": role,
            "recommended_text_profile": text_profile if isinstance(text_profile, str) and text_profile.strip() else None,
        }

    def get_model_options(self) -> Dict[str, Any]:
        profiles = self._load_openai_profiles_config()
        all_items = [self._profile_option_item(name, profile) for name, profile in sorted(profiles.items(), key=lambda x: x[0])]
        vision_profiles = [item for item in all_items if item.get("profile_role") in {"vision", "both"}]
        text_profiles = [item for item in all_items if item.get("profile_role") in {"text", "both"}]
        if not vision_profiles:
            vision_profiles = list(all_items)
        if not text_profiles:
            text_profiles = list(all_items)
        defaults = self._load_llm_defaults_config()
        configured_default_vision = defaults.get("profile")
        configured_default_text = defaults.get("text_profile")
        default_vision_profile = (
            self.profile_name
            if isinstance(self.profile_name, str) and self.profile_name
            else (
                configured_default_vision
                if isinstance(configured_default_vision, str) and configured_default_vision.strip()
                else None
            )
        )
        default_text_profile = (
            self.text_profile.get("name")
            if isinstance(self.text_profile, dict) and isinstance(self.text_profile.get("name"), str)
            else (
                configured_default_text
                if isinstance(configured_default_text, str) and configured_default_text.strip()
                else (self.text_profile_name if isinstance(self.text_profile_name, str) and self.text_profile_name else None)
            )
        )
        return {
            "vision_profiles": vision_profiles,
            "text_profiles": text_profiles,
            "default_vision_profile": default_vision_profile,
            "default_text_profile": default_text_profile,
        }

    def _load_profile_by_name(self, profile_name: str) -> Dict[str, Any]:
        name = profile_name.strip()
        cached = self._profile_cache.get(name)
        if isinstance(cached, dict) and cached:
            return dict(cached)
        try:
            profile = _load_llm_profile(self.config_path, name)
        except SystemExit as exc:
            message = str(exc).strip() or f"invalid profile configuration: {name}"
            raise ValueError(message) from None
        if not isinstance(profile, dict):
            raise ValueError(f"Unknown profile: {name}")
        self._profile_cache[name] = dict(profile)
        return profile

    def _apply_request_model_selection(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        vision_name_raw = payload.get("vision_profile")
        text_name_raw = payload.get("text_profile")
        vision_name = vision_name_raw.strip() if isinstance(vision_name_raw, str) and vision_name_raw.strip() else None
        text_name = text_name_raw.strip() if isinstance(text_name_raw, str) and text_name_raw.strip() else None

        if self.mock_mode:
            return {
                "vision_profile": vision_name,
                "text_profile": text_name,
                "vision_model": None,
                "text_model": None,
            }

        if vision_name:
            self.profile = self._load_profile_by_name(vision_name)
            self.profile_name = vision_name

        if text_name:
            self.text_profile = self._load_profile_by_name(text_name)
            self.text_profile_name = text_name
        elif isinstance(self.profile, dict):
            profile_linked_text = self.profile.get("text_profile")
            if isinstance(profile_linked_text, str) and profile_linked_text.strip():
                try:
                    self.text_profile = self._load_profile_by_name(profile_linked_text.strip())
                    self.text_profile_name = profile_linked_text.strip()
                except Exception:
                    self.text_profile = self.profile
                    self.text_profile_name = self.profile_name or self.text_profile_name
            elif self.text_profile is None:
                self.text_profile = self.profile
                self.text_profile_name = self.profile_name or self.text_profile_name

        self._apply_runtime_options_from_active_profiles()

        vision_profile_name = (
            self.profile.get("name")
            if isinstance(self.profile, dict) and isinstance(self.profile.get("name"), str)
            else None
        )
        text_profile_name = (
            self.text_profile.get("name")
            if isinstance(self.text_profile, dict) and isinstance(self.text_profile.get("name"), str)
            else None
        )
        return {
            "vision_profile": vision_profile_name,
            "text_profile": text_profile_name,
            "vision_model": self.profile.get("model") if isinstance(self.profile, dict) else None,
            "text_model": self.text_profile.get("model") if isinstance(self.text_profile, dict) else None,
        }

    def _apply_runtime_options_from_active_profiles(self) -> None:
        primary = self.profile if isinstance(self.profile, dict) else {}
        text = self.text_profile if isinstance(self.text_profile, dict) else {}

        def _profile_get(key: str, default: Any) -> Any:
            if key in primary:
                return primary.get(key)
            if key in text:
                return text.get(key)
            return default

        for attr, key, default, minimum in (
            ("question_chunk_size", "question_chunk_size", self.question_chunk_size, 1),
            ("reference_answer_chunk_size", "reference_answer_chunk_size", self.reference_answer_chunk_size, 1),
            ("score_chunk_size", "score_chunk_size", self.score_chunk_size, 1),
            ("answer_chunk_size", "answer_chunk_size", self.answer_chunk_size, 1),
            ("answer_structuring_chunk_size", "answer_structuring_chunk_size", self.answer_structuring_chunk_size, 1),
            ("objective_chunk_size", "objective_chunk_size", self.objective_chunk_size, 1),
            ("subjective_chunk_size", "subjective_chunk_size", self.subjective_chunk_size, 1),
            ("paper_concurrency", "paper_concurrency", self.paper_concurrency, 1),
            ("answer_concurrency", "answer_concurrency", self.answer_concurrency, 1),
            ("max_repair_rounds", "max_repair_rounds", self.max_repair_rounds, 0),
            ("blind_diagnosis_max_items", "blind_diagnosis_max_items", self.blind_diagnosis_max_items, 0),
        ):
            value = _profile_get(key, default)
            if isinstance(value, (int, float, str)):
                try:
                    setattr(self, attr, max(minimum, int(float(value))))
                except Exception:
                    pass

        self.question_full_discovery_enabled = _as_bool(
            _profile_get("question_full_discovery_enabled", self.question_full_discovery_enabled),
            self.question_full_discovery_enabled,
        )
        self.answer_trace_save_debug_json = _as_bool(
            _profile_get("answer_trace_save_debug_json", self.answer_trace_save_debug_json),
            self.answer_trace_save_debug_json,
        )
        self.debug_save_all_stages = _as_bool(
            _profile_get("debug_save_all_stages", self.debug_save_all_stages),
            self.debug_save_all_stages,
        )
        debug_stage_output_dir = _profile_get("debug_stage_output_dir", self.debug_stage_output_dir)
        if isinstance(debug_stage_output_dir, str) and debug_stage_output_dir.strip():
            self.debug_stage_output_dir = Path(debug_stage_output_dir.strip())
        self.blind_diagnosis_enabled = _as_bool(
            _profile_get("blind_diagnosis_enabled", self.blind_diagnosis_enabled),
            self.blind_diagnosis_enabled,
        )
        knowledge_mode = _profile_get("knowledge_tagging_mode", self.knowledge_tagging_mode)
        if isinstance(knowledge_mode, str) and knowledge_mode.strip().lower() in {"normal", "fast", "off"}:
            self.knowledge_tagging_mode = knowledge_mode.strip().lower()
        profile_mode = _profile_get("profile_mode", self.profile_mode)
        if isinstance(profile_mode, str) and profile_mode.strip().lower() in {"llm", "rule_first", "rule_only"}:
            self.profile_mode = profile_mode.strip().lower()

    def _resolve_harness_profile(
        self,
        spec: HarnessStageSpec,
        profile: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        if profile is not None:
            return profile
        if spec.profile_role == "text":
            return self.text_profile or self.profile
        return self.profile

    def _save_stage_artifact(
        self,
        spec: HarnessStageSpec,
        *,
        prompt: str,
        data_url_count: int,
        response: Any,
        elapsed_ms: float,
        success: bool,
        error: Optional[str] = None,
    ) -> None:
        if not self.debug_save_all_stages:
            return
        run_dir = self._debug_active_run_dir
        if run_dir is None:
            return
        import secrets
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        rand_suffix = secrets.token_hex(4)
        safe_stage = spec.name.replace("/", "_").replace("\\", "_")[:64]
        filename = f"{safe_stage}.{ts}.{rand_suffix}.json"
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            entry: Dict[str, Any] = {
                "stage": spec.name,
                "mode": spec.mode,
                "prompt": prompt,
                "image_count": data_url_count,
                "success": success,
                "elapsed_ms": round(elapsed_ms, 1),
            }
            if success:
                entry["response"] = response
            if error:
                entry["error"] = error
            (run_dir / filename).write_text(
                json.dumps(entry, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            pass

    def _run_harness_stage(
        self,
        spec: HarnessStageSpec,
        *,
        prompt: str,
        data_urls: List[str],
        profile: Optional[Dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
        expected_list_key: Optional[str] = None,
        thinking_override: Optional[str] = None,
        reasoning_effort_override: Optional[str] = None,
        detail_override: Optional[str] = None,
        image_pixel_limit_override: Optional[Dict[str, Any]] = None,
    ) -> Any:
        active_profile = self._resolve_harness_profile(spec, profile)
        if active_profile is None:
            raise ValueError("llm profile is not configured")
        _started = perf_counter()
        try:
            _result = self._agent_harness.run_stage(
                spec,
                profile=active_profile,
                prompt=prompt,
                data_urls=data_urls,
                max_tokens=max_tokens,
                expected_list_key=expected_list_key,
                thinking_override=thinking_override,
                reasoning_effort_override=reasoning_effort_override,
                detail_override=detail_override,
                image_pixel_limit_override=image_pixel_limit_override,
            )
            _elapsed = (perf_counter() - _started) * 1000
            self._save_stage_artifact(
                spec,
                prompt=prompt,
                data_url_count=len(data_urls),
                response=_result,
                elapsed_ms=_elapsed,
                success=True,
            )
            return _result
        except Exception as _exc:
            _elapsed = (perf_counter() - _started) * 1000
            self._save_stage_artifact(
                spec,
                prompt=prompt,
                data_url_count=len(data_urls),
                response=None,
                elapsed_ms=_elapsed,
                success=False,
                error=str(_exc),
            )
            raise

    def _call_json_with_profile(
        self,
        profile: Optional[Dict[str, Any]],
        *,
        prompt: str,
        data_urls: List[str],
        max_tokens: Optional[int] = None,
        expected_list_key: Optional[str] = None,
        thinking_override: Optional[str] = None,
        reasoning_effort_override: Optional[str] = None,
        detail_override: Optional[str] = None,
        image_pixel_limit_override: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self._run_harness_stage(
            HarnessStageSpec(name="legacy_json_call", mode="json"),
            prompt=prompt,
            data_urls=data_urls,
            profile=profile,
            max_tokens=max_tokens,
            expected_list_key=expected_list_key,
            thinking_override=thinking_override,
            reasoning_effort_override=reasoning_effort_override,
            detail_override=detail_override,
            image_pixel_limit_override=image_pixel_limit_override,
        )

    def _call_text_with_profile(
        self,
        profile: Optional[Dict[str, Any]],
        *,
        prompt: str,
        data_urls: List[str],
        max_tokens: Optional[int] = None,
        thinking_override: Optional[str] = None,
        reasoning_effort_override: Optional[str] = None,
        detail_override: Optional[str] = None,
        image_pixel_limit_override: Optional[Dict[str, Any]] = None,
    ) -> str:
        return self._run_harness_stage(
            HarnessStageSpec(name="legacy_text_call", mode="text"),
            prompt=prompt,
            data_urls=data_urls,
            profile=profile,
            max_tokens=max_tokens,
            thinking_override=thinking_override,
            reasoning_effort_override=reasoning_effort_override,
            detail_override=detail_override,
            image_pixel_limit_override=image_pixel_limit_override,
        )

    @staticmethod
    def _profile_runtime_name(profile: Dict[str, Any]) -> str:
        runtime = profile.get("runtime")
        if isinstance(runtime, str) and runtime.strip():
            return runtime.strip().lower()
        return "legacy"

    def _should_use_langchain_runtime(self, profile: Dict[str, Any]) -> bool:
        if self._profile_runtime_name(profile) != "langchain":
            return False
        provider = str(profile.get("provider", "openai_compatible")).strip().lower()
        return provider == "openai_compatible" and is_langchain_available()

    def _get_langchain_agent(self, profile: Dict[str, Any]) -> LangChainAgentRuntime:
        profile_name = profile.get("name") if isinstance(profile.get("name"), str) else profile.get("model")
        cache_key = str(profile_name or profile.get("model") or "default")
        runtime = self._langchain_agents.get(cache_key)
        if runtime is None:
            runtime = LangChainAgentRuntime(
                base_url=str(profile["base_url"]),
                api_key=str(profile["api_key"]),
                model=str(profile["model"]),
                timeout=int(profile.get("timeout_sec", self.timeout_sec)),
                max_retries=int(profile.get("max_retries", self.max_retries)),
                backoff_base_sec=float(profile.get("backoff_base_sec", self.backoff_base_sec)),
                min_interval_sec=float(profile.get("min_interval_sec", self.min_interval_sec)),
                use_responses_api=_as_bool(profile.get("use_responses_api", False), False),
                output_version=profile.get("output_version") if isinstance(profile.get("output_version"), str) else None,
            )
            self._langchain_agents[cache_key] = runtime
        return runtime

    def _sort_question_ids(self, question_ids: List[str]) -> List[str]:
        return sorted(
            [qid for qid in question_ids if isinstance(qid, str) and qid],
            key=lambda x: (0, int(x[1:])) if re.fullmatch(r"Q\d{1,3}", x) else (1, x),
        )

    def _resolve_answer_segment_weights_path(self) -> Path:
        candidate = self.answer_segment_weights
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate

    @staticmethod
    def _safe_path_token(value: str) -> str:
        text = value.strip() if isinstance(value, str) else ""
        if not text:
            return ""
        text = re.sub(r"[^\w.-]+", "_", text, flags=re.ASCII)
        return text.strip("._-")

    def _resolve_answer_segment_crop_root(self) -> Path:
        root = self.answer_segment_crop_output_dir
        if not root.is_absolute():
            root = (Path.cwd() / root).resolve()
        return root

    def _resolve_answer_trace_debug_root(self) -> Path:
        root = self.answer_trace_debug_output_dir
        if not root.is_absolute():
            root = (Path.cwd() / root).resolve()
        return root

    def _save_answer_trace_debug_json(
        self,
        *,
        output_root: Optional[Path],
        student_id: str,
        run_token: str,
        payload: Dict[str, Any],
        warnings: List[str],
        filename: str = "raw_vlm_outputs.json",
    ) -> Optional[str]:
        if not self.answer_trace_save_debug_json:
            return None
        try:
            if output_root is None:
                student_token = self._safe_path_token(student_id) or "unknown"
                run_token_safe = self._safe_path_token(run_token) or datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                output_root = self._resolve_answer_trace_debug_root() / student_token / run_token_safe
            output_root.mkdir(parents=True, exist_ok=True)
            safe_filename = filename.strip() if isinstance(filename, str) and filename.strip() else "raw_vlm_outputs.json"
            save_path = output_root / safe_filename
            save_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return str(save_path)
        except Exception as exc:
            warnings.append(f"answer_trace_debug_json save failed: {exc}")
            return None

    def _save_answer_segment_crop(
        self,
        *,
        crop: Any,
        output_root: Path,
        page_index: int,
        region_index: int,
        class_name: str,
        warnings: List[str],
    ) -> Optional[str]:
        class_token = self._safe_path_token(class_name) or "unknown"
        try:
            page_dir = output_root / f"page_{page_index + 1:02d}"
            page_dir.mkdir(parents=True, exist_ok=True)
            save_path = page_dir / f"{region_index:03d}_{class_token}.jpg"
            ok = cv2.imwrite(str(save_path), crop)
            if not ok:
                warnings.append(
                    f"answer_segmentation crop save failed at page={page_index + 1}, region={region_index}"
                )
                return None
            return str(save_path)
        except Exception as exc:
            warnings.append(
                f"answer_segmentation crop save error at page={page_index + 1}, region={region_index}: {exc}"
            )
            return None

    def _ensure_mineru_client(self) -> MinerUStandardClient:
        if self._mineru_client is not None:
            return self._mineru_client
        if self._mineru_client_init_error is not None:
            raise RuntimeError(self._mineru_client_init_error)
        try:
            self._mineru_client = MinerUStandardClient(self.config_path)
            return self._mineru_client
        except Exception as exc:  # noqa: BLE001
            self._mineru_client_init_error = str(exc)
            raise RuntimeError(self._mineru_client_init_error) from exc

    @staticmethod
    def _decode_page_image(page_url: str) -> tuple[str, bytes, Any]:
        if cv2 is None:
            raise RuntimeError(f"opencv unavailable: {_CV2_IMPORT_ERROR}")
        mime, image_bytes = _decode_image_data_url(page_url)
        with tempfile.TemporaryDirectory(prefix="page_decode_") as temp_dir:
            image_path = Path(temp_dir) / f"page{_image_suffix_from_mime(mime)}"
            image_path.write_bytes(image_bytes)
            image = cv2.imread(str(image_path))
        if image is None:
            raise RuntimeError("failed to decode page image")
        return mime, image_bytes, image

    @staticmethod
    def _crop_image_to_data_url(image: Any, bbox_xyxy: List[int]) -> str:
        x1, y1, x2, y2 = bbox_xyxy
        crop = image[y1:y2, x1:x2]
        if crop is None or getattr(crop, "size", 0) == 0:
            raise RuntimeError("crop is empty")
        ok, encoded = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ok:
            raise RuntimeError("failed to encode crop preview")
        return _image_bytes_to_data_url(encoded.tobytes(), "jpeg")

    def _prepare_student_trace_data_url(self, data_url: str, warnings: List[str], source: str) -> str:
        if self.review_mark_filter_mode != "red_mask":
            return data_url
        try:
            return _mask_red_review_marks_data_url(data_url)
        except Exception as exc:
            warnings.append(f"review_mark_filter failed for {source}: {exc}")
            return data_url

    def _make_answer_block_candidate(
        self,
        *,
        block_id: str,
        source: str,
        page_index: int,
        bbox_xyxy: List[int],
        class_name: str,
        confidence: float,
        page_image: Any,
    ) -> Dict[str, Any]:
        preview_url = self._crop_image_to_data_url(page_image, bbox_xyxy)
        return {
            "block_id": block_id,
            "source": source,
            "page_index": page_index,
            "bbox_xyxy": bbox_xyxy,
            "class_name": class_name,
            "confidence": round(max(0.0, min(1.0, float(confidence))), 4),
            "data_url_preview": preview_url,
            "sort_key": f"{page_index:04d}-{bbox_xyxy[1]:06d}-{bbox_xyxy[0]:06d}",
        }

    @staticmethod
    def _mineru_bbox_to_pixels(
        raw_bbox: Any,
        *,
        width: int,
        height: int,
        coordinate_mode: str,
    ) -> Optional[List[int]]:
        if not (isinstance(raw_bbox, list) and len(raw_bbox) == 4):
            return None
        try:
            values = [float(item) for item in raw_bbox]
        except Exception:
            return None
        if coordinate_mode == "unit":
            scaled = [values[0] * width, values[1] * height, values[2] * width, values[3] * height]
        elif coordinate_mode == "thousand":
            scaled = [values[0] * width / 1000.0, values[1] * height / 1000.0, values[2] * width / 1000.0, values[3] * height / 1000.0]
        else:
            scaled = values
        bbox_xyxy = _coerce_bbox_xyxy(scaled)
        if bbox_xyxy is None:
            return None
        return _clip_bbox_xyxy(bbox_xyxy, width, height)

    @staticmethod
    def _map_mineru_block_class(raw_type: Any) -> Optional[str]:
        text = str(raw_type or "").strip().lower()
        if not text:
            return "subjective_problem"
        if text in {"header", "footer", "page_number", "aside_text", "page_footnote", "seal"}:
            return None
        if text in {"equation", "inline_equation", "interline_equation", "formula"}:
            return "fillin_problem"
        return "subjective_problem"

    def _append_mineru_candidate_spec(
        self,
        output: List[Dict[str, Any]],
        *,
        raw_bbox: Any,
        width: int,
        height: int,
        coordinate_mode: str,
        raw_type: Any,
        confidence: Any,
    ) -> None:
        class_name = self._map_mineru_block_class(raw_type)
        if class_name is None:
            return
        bbox_xyxy = self._mineru_bbox_to_pixels(
            raw_bbox,
            width=width,
            height=height,
            coordinate_mode=coordinate_mode,
        )
        if bbox_xyxy is None:
            return
        if bbox_xyxy[2] - bbox_xyxy[0] < 12 or bbox_xyxy[3] - bbox_xyxy[1] < 12:
            return
        score = float(confidence) if isinstance(confidence, (int, float)) else 0.0
        output.append(
            {
                "bbox_xyxy": bbox_xyxy,
                "class_name": class_name,
                "confidence": score,
            }
        )

    def _extract_mineru_candidate_specs(
        self,
        bundle: Dict[str, Any],
        *,
        width: int,
        height: int,
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []

        content_list = bundle.get("content_list")
        if isinstance(content_list, list):
            for item in content_list:
                if not isinstance(item, dict):
                    continue
                self._append_mineru_candidate_spec(
                    results,
                    raw_bbox=item.get("bbox"),
                    width=width,
                    height=height,
                    coordinate_mode="thousand",
                    raw_type=item.get("type") or item.get("sub_type"),
                    confidence=item.get("score"),
                )

        def visit_content_list_v2(node: Any) -> None:
            if isinstance(node, dict):
                if "bbox" in node and ("type" in node or "content" in node):
                    self._append_mineru_candidate_spec(
                        results,
                        raw_bbox=node.get("bbox"),
                        width=width,
                        height=height,
                        coordinate_mode="thousand",
                        raw_type=node.get("type"),
                        confidence=node.get("score"),
                    )
                for child in node.values():
                    visit_content_list_v2(child)
                return
            if isinstance(node, list):
                for item in node:
                    visit_content_list_v2(item)

        if bundle.get("content_list_v2") is not None:
            visit_content_list_v2(bundle.get("content_list_v2"))

        middle = bundle.get("middle")
        if isinstance(middle, dict):
            pdf_info = middle.get("pdf_info")
            if isinstance(pdf_info, list):
                for page_info in pdf_info:
                    if not isinstance(page_info, dict):
                        continue

                    def visit_middle(node: Any) -> None:
                        if isinstance(node, dict):
                            if "bbox" in node and "type" in node:
                                self._append_mineru_candidate_spec(
                                    results,
                                    raw_bbox=node.get("bbox"),
                                    width=width,
                                    height=height,
                                    coordinate_mode="pixel",
                                    raw_type=node.get("type"),
                                    confidence=node.get("score"),
                                )
                            for child in node.values():
                                visit_middle(child)
                            return
                        if isinstance(node, list):
                            for item in node:
                                visit_middle(item)

                    visit_middle(page_info)

        model = bundle.get("model")
        if isinstance(model, list):
            page_blocks = model[0] if model and isinstance(model[0], list) else model
            if isinstance(page_blocks, list):
                for block in page_blocks:
                    if not isinstance(block, dict):
                        continue
                    bbox = block.get("bbox")
                    coordinate_mode = "pixel"
                    if isinstance(bbox, list) and len(bbox) == 4:
                        try:
                            bbox_values = [float(item) for item in bbox]
                        except Exception:
                            bbox_values = []
                        if bbox_values and max(abs(item) for item in bbox_values) <= 1.5:
                            coordinate_mode = "unit"
                        elif bbox_values and max(abs(item) for item in bbox_values) <= 1000 and (width > 1000 or height > 1000):
                            coordinate_mode = "thousand"
                    self._append_mineru_candidate_spec(
                        results,
                        raw_bbox=bbox,
                        width=width,
                        height=height,
                        coordinate_mode=coordinate_mode,
                        raw_type=block.get("type"),
                        confidence=block.get("score"),
                    )
        return results

    @staticmethod
    def _bbox_area(bbox_xyxy: List[int]) -> int:
        if len(bbox_xyxy) != 4:
            return 0
        return max(0, int(bbox_xyxy[2]) - int(bbox_xyxy[0])) * max(0, int(bbox_xyxy[3]) - int(bbox_xyxy[1]))

    def _dedupe_mineru_candidate_specs(
        self,
        specs: List[Dict[str, Any]],
        *,
        iou_threshold: float = 0.85,
    ) -> List[Dict[str, Any]]:
        if len(specs) < 2:
            return list(specs)
        ranked_specs = sorted(
            specs,
            key=lambda item: (
                float(item.get("confidence") or 0.0),
                self._bbox_area(item.get("bbox_xyxy") if isinstance(item.get("bbox_xyxy"), list) else []),
            ),
            reverse=True,
        )
        kept: List[Dict[str, Any]] = []
        for candidate in ranked_specs:
            bbox_xyxy = candidate.get("bbox_xyxy")
            class_name = str(candidate.get("class_name") or "unknown")
            if not isinstance(bbox_xyxy, list) or len(bbox_xyxy) != 4:
                continue
            duplicated = False
            for existing in kept:
                existing_bbox = existing.get("bbox_xyxy")
                if not isinstance(existing_bbox, list) or len(existing_bbox) != 4:
                    continue
                if str(existing.get("class_name") or "unknown") != class_name:
                    continue
                if _bbox_iou(bbox_xyxy, existing_bbox) >= iou_threshold:
                    duplicated = True
                    break
            if not duplicated:
                kept.append(candidate)
        kept.sort(
            key=lambda item: (
                int(item["bbox_xyxy"][1]),
                int(item["bbox_xyxy"][0]),
                str(item.get("class_name") or "unknown"),
            )
        )
        return kept

    def _build_mineru_candidates(self, answer_urls: List[str]) -> tuple[List[Dict[str, Any]], List[str]]:
        warnings: List[str] = []
        client = self._ensure_mineru_client()
        page_payloads: List[tuple[int, Dict[str, Any], int, int]] = []
        for page_index, page_url in enumerate(answer_urls):
            mime, image_bytes, page_image = self._decode_page_image(page_url)
            height, width = page_image.shape[:2]
            suffix = _image_suffix_from_mime(mime)
            bundle = client.run_bytes(
                filename=f"answer_page_{page_index + 1}{suffix}",
                content=image_bytes,
                suffix=suffix,
            )
            if not any(bundle.get(key) is not None for key in ("content_list", "content_list_v2", "middle", "model")):
                raise RuntimeError(f"mineru structured result missing at page {page_index + 1}")
            page_payloads.append((page_index, bundle, width, height))

        candidates: List[Dict[str, Any]] = []
        seen: set[tuple[int, int, int, int, int, str]] = set()
        decoded_pages: Dict[int, Any] = {}
        for page_index, page_url in enumerate(answer_urls):
            _, _, page_image = self._decode_page_image(page_url)
            decoded_pages[page_index] = page_image
        for page_index, bundle, width, height in page_payloads:
            rectangles = self._extract_mineru_candidate_specs(
                bundle,
                width=width,
                height=height,
            )
            raw_count = len(rectangles)
            rectangles = self._dedupe_mineru_candidate_specs(rectangles, iou_threshold=0.85)
            if not rectangles:
                warnings.append(f"mineru structured output produced no candidate blocks at page {page_index + 1}")
            elif raw_count > len(rectangles):
                warnings.append(
                    f"mineru deduplicated {raw_count - len(rectangles)} overlapping blocks at page {page_index + 1}"
                )
            serial = 0
            for item in rectangles:
                bbox_xyxy = _clip_bbox_xyxy(item["bbox_xyxy"], width, height)
                if bbox_xyxy is None:
                    continue
                key = (
                    page_index,
                    bbox_xyxy[0],
                    bbox_xyxy[1],
                    bbox_xyxy[2],
                    bbox_xyxy[3],
                    str(item.get("class_name") or "unknown"),
                )
                if key in seen:
                    continue
                seen.add(key)
                serial += 1
                candidates.append(
                    self._make_answer_block_candidate(
                        block_id=f"mineru_p{page_index + 1}_{serial:03d}",
                        source="mineru",
                        page_index=page_index,
                        bbox_xyxy=bbox_xyxy,
                        class_name=str(item.get("class_name") or "unknown"),
                        confidence=float(item.get("confidence") or 0.0),
                        page_image=decoded_pages[page_index],
                    )
                )
        candidates.sort(key=lambda item: str(item.get("sort_key") or ""))
        return candidates, warnings

    def _build_project_segmenter_candidates(self, answer_urls: List[str], warnings: List[str]) -> List[Dict[str, Any]]:
        segmenter = self._ensure_answer_segmenter(warnings)
        if segmenter is None:
            raise RuntimeError("project segmenter is unavailable")
        candidates: List[Dict[str, Any]] = []
        for page_index, page_url in enumerate(answer_urls):
            mime, image_bytes, page_image = self._decode_page_image(page_url)
            height, width = page_image.shape[:2]
            with tempfile.TemporaryDirectory(prefix="answer_seg_candidate_") as temp_dir:
                image_path = Path(temp_dir) / f"answer_page_{page_index + 1}{_image_suffix_from_mime(mime)}"
                image_path.write_bytes(image_bytes)
                try:
                    seg_payload = segmenter.segment_file(image_path)
                except Exception as exc:
                    warnings.append(f"project segmenter failed at page {page_index + 1}: {exc}")
                    continue
            detections = seg_payload.get("detections", [])
            if not isinstance(detections, list):
                continue
            for serial, detection in enumerate(detections, start=1):
                if not isinstance(detection, dict):
                    continue
                bbox_xyxy = _coerce_bbox_xyxy(detection.get("bbox_xyxy"))
                if bbox_xyxy is None:
                    continue
                bbox_xyxy = _clip_bbox_xyxy(bbox_xyxy, width, height)
                if bbox_xyxy is None:
                    continue
                candidates.append(
                    self._make_answer_block_candidate(
                        block_id=f"project_segmenter_p{page_index + 1}_{serial:03d}",
                        source="project_segmenter",
                        page_index=page_index,
                        bbox_xyxy=bbox_xyxy,
                        class_name=(
                            detection.get("class_name")
                            if isinstance(detection.get("class_name"), str)
                            else "unknown"
                        ),
                        confidence=float(detection.get("confidence") or 0.0),
                        page_image=page_image,
                    )
                )
        candidates.sort(key=lambda item: str(item.get("sort_key") or ""))
        return candidates

    @staticmethod
    def _group_candidates_by_page(candidates: List[Dict[str, Any]], page_count: int) -> List[Dict[str, Any]]:
        pages = [{"page_index": page_index, "candidates": []} for page_index in range(page_count)]
        for candidate in candidates:
            page_index = candidate.get("page_index")
            if isinstance(page_index, int) and 0 <= page_index < page_count:
                pages[page_index]["candidates"].append(candidate)
        return pages

    def _normalize_accepted_blocks(self, payload: Dict[str, Any], key: str = "accepted_blocks") -> List[Dict[str, Any]]:
        raw_blocks = payload.get(key)
        if raw_blocks is None:
            return []
        if not isinstance(raw_blocks, list):
            raise ValueError(f"{key} must be an array")
        blocks: List[Dict[str, Any]] = []
        seen: set[tuple[str, int, int, int, int, int]] = set()
        for raw in raw_blocks:
            normalized = _normalize_selected_answer_block_payload(raw) if isinstance(raw, dict) else None
            if normalized is None:
                raise ValueError(f"{key} contains invalid block")
            bbox_xyxy = normalized["bbox_xyxy"]
            dedupe_key = (
                normalized["source"],
                normalized["page_index"],
                bbox_xyxy[0],
                bbox_xyxy[1],
                bbox_xyxy[2],
                bbox_xyxy[3],
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            blocks.append(normalized)
        return blocks

    def _filter_overlapping_candidates(
        self,
        candidates: List[Dict[str, Any]],
        accepted_blocks: List[Dict[str, Any]],
        *,
        iou_threshold: float = 0.6,
    ) -> List[Dict[str, Any]]:
        if not accepted_blocks:
            return candidates
        accepted_by_page: Dict[int, List[List[int]]] = {}
        for block in accepted_blocks:
            page_index = block.get("page_index")
            bbox_xyxy = block.get("bbox_xyxy")
            if isinstance(page_index, int) and isinstance(bbox_xyxy, list) and len(bbox_xyxy) == 4:
                accepted_by_page.setdefault(page_index, []).append(bbox_xyxy)
        output: List[Dict[str, Any]] = []
        for candidate in candidates:
            page_index = candidate.get("page_index")
            bbox_xyxy = candidate.get("bbox_xyxy")
            if not isinstance(page_index, int) or not (isinstance(bbox_xyxy, list) and len(bbox_xyxy) == 4):
                continue
            overlaps = any(
                _bbox_iou(bbox_xyxy, accepted_box) >= iou_threshold
                for accepted_box in accepted_by_page.get(page_index, [])
            )
            if not overlaps:
                output.append(candidate)
        return output

    def build_mineru_segment_preview(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        _, _, _, answer_urls, _, _ = self._validate_input(payload)
        mineru_answer_urls = self._select_mineru_answer_urls(answer_urls)
        candidates, warnings = self._build_mineru_candidates(mineru_answer_urls)
        return {
            "pages": self._group_candidates_by_page(candidates, len(mineru_answer_urls)),
            "warnings": warnings,
        }

    def build_refine_segment_preview(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        _, _, _, answer_urls, _, _ = self._validate_input(payload)
        warnings: List[str] = []
        accepted_blocks = self._normalize_accepted_blocks(payload)
        candidates = self._build_project_segmenter_candidates(answer_urls, warnings)
        candidates = self._filter_overlapping_candidates(candidates, accepted_blocks, iou_threshold=0.6)
        return {
            "pages": self._group_candidates_by_page(candidates, len(answer_urls)),
            "warnings": warnings,
        }

    @staticmethod
    def _select_mineru_answer_urls(answer_urls: List[str]) -> List[str]:
        if not answer_urls:
            return []
        first = answer_urls[0]
        if isinstance(first, str) and first.strip():
            return [first]
        return []

    def _build_manual_answer_slice_plan(
        self,
        *,
        answer_urls: List[str],
        answer_contexts: List[Dict[str, Any]],
        selected_blocks: List[Dict[str, Any]],
        crop_output_root: Optional[Path],
        saved_crop_paths: List[str],
        warnings: List[str],
    ) -> List[Dict[str, Any]]:
        decoded_pages: Dict[int, Any] = {}
        raw_plan: List[Dict[str, Any]] = []
        for index, block in enumerate(sorted(selected_blocks, key=lambda item: str(item.get("sort_key") or "")), start=1):
            page_index = block["page_index"]
            if not 0 <= page_index < len(answer_urls):
                raise ValueError(f"selected_answer_blocks page_index out of range: {page_index}")
            if page_index not in decoded_pages:
                _, _, decoded_pages[page_index] = self._decode_page_image(answer_urls[page_index])
            page_image = decoded_pages[page_index]
            height, width = page_image.shape[:2]
            bbox_xyxy = _clip_bbox_xyxy(block["bbox_xyxy"], width, height)
            if bbox_xyxy is None:
                raise ValueError(f"selected_answer_blocks bbox invalid at page {page_index + 1}")
            x1, y1, x2, y2 = bbox_xyxy
            crop = page_image[y1:y2, x1:x2]
            if crop is None or getattr(crop, "size", 0) == 0:
                raise ValueError(f"selected_answer_blocks crop empty at page {page_index + 1}")
            ok, encoded = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if not ok:
                raise RuntimeError(f"selected_answer_blocks crop encode failed at page {page_index + 1}")
            class_name = block.get("class_name") if isinstance(block.get("class_name"), str) else "unknown"
            section_contexts = _select_manual_block_contexts(
                page_index=page_index,
                answer_contexts=answer_contexts,
            )
            saved_crop_path: Optional[str] = None
            if crop_output_root is not None:
                saved_crop_path = self._save_answer_segment_crop(
                    crop=crop,
                    output_root=crop_output_root,
                    page_index=page_index,
                    region_index=index,
                    class_name=class_name,
                    warnings=warnings,
                )
                if isinstance(saved_crop_path, str) and saved_crop_path:
                    saved_crop_paths.append(saved_crop_path)
            block_id = block.get("block_id") if isinstance(block.get("block_id"), str) else f"manual_{index:03d}"
            raw_plan.append(
                {
                    "source": f"manual_{block_id}",
                    "page_index": page_index,
                    "section_name": f"manual-{block_id}",
                    "data_url": _image_bytes_to_data_url(encoded.tobytes(), "jpeg"),
                    "contexts": section_contexts,
                    "segment_class_name": class_name,
                    "selected_block_class_name": class_name,
                    "segment_confidence": block.get("confidence"),
                    "segment_bbox_xyxy": bbox_xyxy,
                    "saved_crop_path": saved_crop_path,
                }
            )
        return raw_plan

    def _ensure_answer_segmenter(self, warnings: List[str]) -> Optional[Any]:
        if not self.answer_segmentation_enabled:
            return None
        if self._answer_segmenter is not None:
            return self._answer_segmenter
        if self._answer_segmenter_init_error is not None:
            return None
        if cv2 is None:
            self._answer_segmenter_init_error = f"opencv_unavailable: {_CV2_IMPORT_ERROR}"
            warnings.append(f"answer_segmentation unavailable, fallback to full-page recognition: {self._answer_segmenter_init_error}")
            return None
        if BigQuestionSegmenter is None:
            self._answer_segmenter_init_error = f"major_seg_tool_unavailable: {_MAJOR_SEG_IMPORT_ERROR}"
            warnings.append(f"answer_segmentation unavailable, fallback to full-page recognition: {self._answer_segmenter_init_error}")
            return None
        weights_path = self._resolve_answer_segment_weights_path()
        if not weights_path.exists():
            self._answer_segmenter_init_error = f"weights_not_found: {weights_path}"
            warnings.append(f"answer_segmentation unavailable, fallback to full-page recognition: {self._answer_segmenter_init_error}")
            return None
        try:
            self._answer_segmenter = BigQuestionSegmenter(
                weights=weights_path,
                imgsz=self.answer_segment_imgsz,
                conf=self.answer_segment_conf,
                iou=self.answer_segment_iou,
                device=self.answer_segment_device,
                include_student_id=self.answer_segment_include_student_id,
            )
            return self._answer_segmenter
        except Exception as exc:
            self._answer_segmenter_init_error = f"segmenter_init_failed: {exc}"
            warnings.append(f"answer_segmentation unavailable, fallback to full-page recognition: {self._answer_segmenter_init_error}")
            return None

    @staticmethod
    def _build_full_page_slice_spec(
        page_url: str,
        page_index: int,
        answer_contexts: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "source": f"page_{page_index + 1}_full",
            "page_index": page_index,
            "section_name": f"page-{page_index + 1}-full",
            "data_url": page_url,
            "contexts": answer_contexts,
            "segment_class_name": "full_page",
            "segment_confidence": 1.0,
        }

    def _build_answer_slice_plan_for_page(
        self,
        *,
        page_url: str,
        page_index: int,
        answer_contexts: List[Dict[str, Any]],
        crop_output_root: Optional[Path],
        saved_crop_paths: List[str],
        warnings: List[str],
    ) -> List[Dict[str, Any]]:
        fallback = [self._build_full_page_slice_spec(page_url, page_index, answer_contexts)]
        segmenter = self._ensure_answer_segmenter(warnings)
        if segmenter is None:
            return fallback

        try:
            mime, image_bytes = _decode_image_data_url(page_url)
        except Exception as exc:
            warnings.append(f"answer_segmentation decode failed at page={page_index + 1}: {exc}")
            return fallback

        margin = max(0, self.answer_segment_margin_px)
        with tempfile.TemporaryDirectory(prefix="answer_seg_") as temp_dir:
            image_path = Path(temp_dir) / f"answer_page_{page_index + 1}{_image_suffix_from_mime(mime)}"
            image_path.write_bytes(image_bytes)
            page_image = cv2.imread(str(image_path))
            if page_image is None:
                warnings.append(f"answer_segmentation cannot read decoded image at page={page_index + 1}")
                return fallback
            try:
                seg_payload = segmenter.segment_file(image_path)
            except Exception as exc:
                warnings.append(f"answer_segmentation model failed at page={page_index + 1}: {exc}")
                return fallback
            detections = seg_payload.get("detections", [])
            if not isinstance(detections, list) or not detections:
                warnings.append(f"answer_segmentation found no regions at page={page_index + 1}, fallback to full-page recognition")
                return fallback
            page_contexts = _select_answer_contexts_for_slice(
                page_index=page_index,
                primary_contexts=[],
                answer_contexts=answer_contexts,
            )

            height, width = page_image.shape[:2]
            slice_specs: List[Dict[str, Any]] = []
            for serial, detection in enumerate(detections, start=1):
                if not isinstance(detection, dict):
                    continue
                bbox = detection.get("bbox_xyxy")
                if not (isinstance(bbox, list) and len(bbox) == 4):
                    continue
                try:
                    raw_x1, raw_y1, raw_x2, raw_y2 = [int(round(float(v))) for v in bbox]
                except Exception:
                    continue
                x1 = max(0, raw_x1 - margin)
                y1 = max(0, raw_y1 - margin)
                x2 = min(width, raw_x2 + margin)
                y2 = min(height, raw_y2 + margin)
                if x2 <= x1 or y2 <= y1:
                    continue
                crop = page_image[y1:y2, x1:x2]
                if crop is None or getattr(crop, "size", 0) == 0:
                    continue
                ok, encoded = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if not ok:
                    continue
                class_name = detection.get("class_name") if isinstance(detection.get("class_name"), str) else "unknown"
                region_index = detection.get("index")
                if not isinstance(region_index, int) or region_index <= 0:
                    region_index = serial
                source = f"page_{page_index + 1}_seg_{region_index}_{class_name}"
                saved_crop_path: Optional[str] = None
                if crop_output_root is not None:
                    saved_crop_path = self._save_answer_segment_crop(
                        crop=crop,
                        output_root=crop_output_root,
                        page_index=page_index,
                        region_index=region_index,
                        class_name=class_name,
                        warnings=warnings,
                    )
                    if isinstance(saved_crop_path, str) and saved_crop_path:
                        saved_crop_paths.append(saved_crop_path)
                section_name = f"page-{page_index + 1}-segment-{region_index}-{class_name}"
                slice_specs.append(
                    {
                        "source": source,
                        "page_index": page_index,
                        "section_name": section_name,
                        "data_url": _image_bytes_to_data_url(encoded.tobytes(), "jpeg"),
                        "contexts": page_contexts,
                        "segment_class_name": class_name,
                        "segment_confidence": detection.get("confidence"),
                        "segment_bbox_xyxy": [x1, y1, x2, y2],
                        "saved_crop_path": saved_crop_path,
                    }
                )
            if slice_specs:
                if all(
                    str(item.get("segment_class_name") or "") == "subjective_problem"
                    for item in slice_specs
                    if isinstance(item, dict)
                ):
                    full_page_spec = self._build_full_page_slice_spec(page_url, page_index, answer_contexts)
                    full_page_spec["source"] = f"page_{page_index + 1}_full_supplement"
                    full_page_spec["section_name"] = f"page-{page_index + 1}-full-supplement"
                    slice_specs.append(full_page_spec)
                return slice_specs

        warnings.append(f"answer_segmentation generated no valid crop slices at page={page_index + 1}, fallback to full-page recognition")
        return fallback

    def _run_question_analysis_parallel(
        self,
        paper_urls: List[str],
        question_candidates: List[Dict[str, Any]],
        warnings: List[str],
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any], List[str], int, int]:
        question_by_id: Dict[str, Dict[str, Any]] = {}
        index_success = 0
        index_failed = 0
        question_pass_chunks = 0
        page_tasks = []
        max_workers = min(self.paper_concurrency, max(1, len(paper_urls)))
        self._log_progress(
            "question_analysis",
            "index_start",
            page_count=len(paper_urls),
            candidate_count=len(question_candidates),
            max_workers=max_workers,
        )
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for page_index, page_url in enumerate(paper_urls):
                page_tasks.append(
                    (
                        page_index,
                        perf_counter(),
                        executor.submit(
                            self._run_harness_stage,
                            HARNESS_STAGE_QUESTION_ANALYSIS,
                            prompt=_paper_prompt(question_candidates, mode="index"),
                            data_urls=[page_url],
                            profile=self.profile,
                        ),
                    )
                )
            for page_index, batch_started, future in page_tasks:
                try:
                    questions_data = future.result()
                    index_success += 1
                except Exception as exc:
                    index_failed += 1
                    warnings.append(f"question_index page={page_index + 1} failed: {exc}")
                    self._log_progress(
                        "question_analysis",
                        "index_failed",
                        page=page_index + 1,
                        elapsed_ms=round((perf_counter() - batch_started) * 1000, 1),
                    )
                    continue
                batch_questions = questions_data.get("questions", [])
                detected_count = len(batch_questions) if isinstance(batch_questions, list) else 0
                self._log_progress(
                    "question_analysis",
                    "index_done",
                    page=page_index + 1,
                    detected_count=detected_count,
                    elapsed_ms=round((perf_counter() - batch_started) * 1000, 1),
                )
                if not isinstance(batch_questions, list):
                    continue
                for item in batch_questions:
                    if not isinstance(item, dict):
                        continue
                    normalized_question = _normalize_question_item(item, page_index=page_index)
                    if normalized_question is None:
                        continue
                    qid = normalized_question["question_id"]
                    existing = question_by_id.get(qid)
                    question_by_id[qid] = normalized_question if existing is None else _merge_question_items(existing, normalized_question)

        if not question_by_id:
            fallback_started = perf_counter()
            self._log_progress(
                "question_analysis",
                "full_fallback_start",
                page_count=len(paper_urls),
            )
            try:
                fallback_data = self._call_json_with_profile(
                    self.profile,
                    prompt=_paper_prompt(question_candidates, mode="full"),
                    data_urls=paper_urls,
                    expected_list_key=expected_list_key("question_analysis"),
                )
                fallback_questions = fallback_data.get("questions", [])
                if isinstance(fallback_questions, list):
                    for item in fallback_questions:
                        if not isinstance(item, dict):
                            continue
                        normalized_question = _normalize_question_item(item)
                        if normalized_question is None:
                            continue
                        qid = normalized_question["question_id"]
                        existing = question_by_id.get(qid)
                        question_by_id[qid] = normalized_question if existing is None else _merge_question_items(existing, normalized_question)
                self._log_progress(
                    "question_analysis",
                    "full_fallback_done",
                    question_count=len(question_by_id),
                    elapsed_ms=round((perf_counter() - fallback_started) * 1000, 1),
                )
            except Exception as exc:
                warnings.append(f"question_full fallback failed: {exc}")
                self._log_progress(
                    "question_analysis",
                    "full_fallback_failed",
                    elapsed_ms=round((perf_counter() - fallback_started) * 1000, 1),
                )

        if self.question_full_discovery_enabled and paper_urls:
            discovery_tasks = []
            self._log_progress(
                "question_analysis",
                "full_discovery_start",
                page_count=len(paper_urls),
                max_workers=max_workers,
            )
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for page_index, page_url in enumerate(paper_urls):
                    question_pass_chunks += 1
                    discovery_tasks.append(
                        (
                            page_index,
                            perf_counter(),
                            executor.submit(
                                self._run_harness_stage,
                                HARNESS_STAGE_QUESTION_ANALYSIS,
                                prompt=_paper_prompt(question_candidates, mode="full"),
                                data_urls=[page_url],
                                profile=self.profile,
                            ),
                        )
                    )
                for page_index, task_started, future in discovery_tasks:
                    try:
                        discovery_data = future.result()
                    except Exception as exc:
                        warnings.append(f"question_full_discovery page={page_index + 1} failed: {exc}")
                        self._log_progress(
                            "question_analysis",
                            "full_discovery_failed",
                            page=page_index + 1,
                            elapsed_ms=round((perf_counter() - task_started) * 1000, 1),
                        )
                        continue
                    discovery_questions = discovery_data.get("questions", [])
                    self._log_progress(
                        "question_analysis",
                        "full_discovery_done",
                        page=page_index + 1,
                        returned_count=len(discovery_questions) if isinstance(discovery_questions, list) else 0,
                        elapsed_ms=round((perf_counter() - task_started) * 1000, 1),
                    )
                    if not isinstance(discovery_questions, list):
                        continue
                    for item in discovery_questions:
                        if not isinstance(item, dict):
                            continue
                        normalized_question = _normalize_question_item(item, page_index=page_index)
                        if normalized_question is None:
                            continue
                        qid = normalized_question["question_id"]
                        existing = question_by_id.get(qid)
                        question_by_id[qid] = normalized_question if existing is None else _merge_question_items(existing, normalized_question)

        questions = _attach_question_metadata(sorted(question_by_id.values(), key=_question_sort_key))
        repair_rounds = 0
        repaired_count = 0

        if questions:
            by_page: Dict[int, List[str]] = {}
            for question in questions:
                page_index = question.get("paper_page_index") if isinstance(question.get("paper_page_index"), int) else 0
                qid = question.get("question_id")
                if isinstance(qid, str) and qid:
                    by_page.setdefault(page_index, []).append(qid)
            full_tasks = []
            scheduled_chunks = 0
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for page_index, qids in sorted(by_page.items()):
                    for qid_chunk in _chunk_list(self._sort_question_ids(qids), self.question_chunk_size):
                        question_pass_chunks += 1
                        scheduled_chunks += 1
                        page_url = [paper_urls[page_index]] if 0 <= page_index < len(paper_urls) else paper_urls[:1]
                        full_tasks.append(
                            (
                        page_index,
                        qid_chunk,
                            perf_counter(),
                            executor.submit(
                            self._run_harness_stage,
                            HARNESS_STAGE_QUESTION_ANALYSIS,
                            prompt=_paper_prompt(question_candidates, mode="full", target_question_ids=qid_chunk),
                            data_urls=page_url,
                            profile=self.profile,
                                ),
                            )
                        )
                self._log_progress(
                    "question_analysis",
                    "full_chunk_start",
                    chunk_count=scheduled_chunks,
                    max_workers=max_workers,
                )
                for page_index, qid_chunk, chunk_started, future in full_tasks:
                    try:
                        full_data = future.result()
                    except Exception as exc:
                        warnings.append(f"question_full chunk failed page={page_index + 1} (targets={qid_chunk}): {exc}")
                        self._log_progress(
                            "question_analysis",
                            "full_chunk_failed",
                            page=page_index + 1,
                            target_count=len(qid_chunk),
                            elapsed_ms=round((perf_counter() - chunk_started) * 1000, 1),
                        )
                        continue
                    chunk_questions = full_data.get("questions", [])
                    self._log_progress(
                        "question_analysis",
                        "full_chunk_done",
                        page=page_index + 1,
                        target_count=len(qid_chunk),
                        returned_count=len(chunk_questions) if isinstance(chunk_questions, list) else 0,
                        elapsed_ms=round((perf_counter() - chunk_started) * 1000, 1),
                    )
                    if not isinstance(chunk_questions, list):
                        continue
                    for item in chunk_questions:
                        if not isinstance(item, dict):
                            continue
                        normalized_question = _normalize_question_item(item, page_index=page_index)
                        if normalized_question is None:
                            continue
                        qid = normalized_question["question_id"]
                        existing = question_by_id.get(qid)
                        question_by_id[qid] = normalized_question if existing is None else _merge_question_items(existing, normalized_question)
            questions = _attach_question_metadata(sorted(question_by_id.values(), key=_question_sort_key))

        empty_content_ids = sorted(
            q["question_id"] for q in questions
            if isinstance(q, dict)
            and isinstance(q.get("question_id"), str)
            and not q.get("problem_text", "").strip()
            and not q.get("problem_text_full", "").strip()
        )
        if empty_content_ids and paper_urls:
            self._log_progress(
                "question_analysis",
                "retry_empty_content_start",
                count=len(empty_content_ids),
                ids=empty_content_ids,
            )
            for page_index, page_url in enumerate(paper_urls):
                try:
                    retry_data = self._run_harness_stage(
                        HARNESS_STAGE_QUESTION_ANALYSIS,
                        prompt=_paper_prompt(question_candidates, mode="full", target_question_ids=empty_content_ids),
                        data_urls=[page_url],
                        profile=self.profile,
                    )
                    retry_questions = retry_data.get("questions", [])
                    if isinstance(retry_questions, list):
                        for item in retry_questions:
                            if not isinstance(item, dict):
                                continue
                            normalized = _normalize_question_item(item, page_index=page_index)
                            if normalized is None:
                                continue
                            qid = normalized["question_id"]
                            existing = question_by_id.get(qid)
                            question_by_id[qid] = normalized if existing is None else _merge_question_items(existing, normalized)
                            question_pass_chunks += 1
                except Exception as exc:
                    warnings.append(f"question_retry page={page_index + 1} (targets={empty_content_ids}): {exc}")
                    continue
            questions = _attach_question_metadata(sorted(question_by_id.values(), key=_question_sort_key))
            self._log_progress(
                "question_analysis",
                "retry_empty_content_done",
                count=len(empty_content_ids),
                after_count=sum(
                    1 for q in questions
                    if isinstance(q, dict) and isinstance(q.get("question_id"), str)
                    and (q.get("problem_text", "").strip() or q.get("problem_text_full", "").strip())
                    and q["question_id"] in empty_content_ids
                ),
            )

        missing_from_step1 = _build_missing_from_step1(questions)
        for _ in range(self.max_repair_rounds):
            if not missing_from_step1:
                break
            before_ids = {q.get("question_id") for q in questions if isinstance(q.get("question_id"), str)}
            repair_rounds += 1
            self._log_progress(
                "question_analysis",
                "repair_round_start",
                round=repair_rounds,
                missing_count=len(missing_from_step1),
            )
            for qid_chunk in _chunk_list(missing_from_step1, self.question_chunk_size):
                question_pass_chunks += 1
                repair_started = perf_counter()
                try:
                    repair_data = self._call_json_with_profile(
                        self.profile,
                        prompt=_paper_prompt(question_candidates, mode="full", target_question_ids=qid_chunk),
                        data_urls=paper_urls,
                        expected_list_key=expected_list_key("question_analysis"),
                    )
                except Exception as exc:
                    warnings.append(f"question_repair chunk failed (targets={qid_chunk}): {exc}")
                    self._log_progress(
                        "question_analysis",
                        "repair_chunk_failed",
                        round=repair_rounds,
                        target_count=len(qid_chunk),
                        elapsed_ms=round((perf_counter() - repair_started) * 1000, 1),
                    )
                    continue
                repair_questions = repair_data.get("questions", [])
                self._log_progress(
                    "question_analysis",
                    "repair_chunk_done",
                    round=repair_rounds,
                    target_count=len(qid_chunk),
                    returned_count=len(repair_questions) if isinstance(repair_questions, list) else 0,
                    elapsed_ms=round((perf_counter() - repair_started) * 1000, 1),
                )
                if not isinstance(repair_questions, list):
                    continue
                for item in repair_questions:
                    if not isinstance(item, dict):
                        continue
                    normalized_question = _normalize_question_item(item)
                    if normalized_question is None:
                        continue
                    qid = normalized_question["question_id"]
                    existing = question_by_id.get(qid)
                    question_by_id[qid] = normalized_question if existing is None else _merge_question_items(existing, normalized_question)
            questions = _attach_question_metadata(sorted(question_by_id.values(), key=_question_sort_key))
            after_ids = {q.get("question_id") for q in questions if isinstance(q.get("question_id"), str)}
            repaired_count += max(0, len(after_ids - before_ids))
            new_missing = _build_missing_from_step1(questions)
            self._log_progress(
                "question_analysis",
                "repair_round_done",
                round=repair_rounds,
                repaired_count=repaired_count,
                remaining_missing_count=len(new_missing),
            )
            if len(new_missing) >= len(missing_from_step1):
                missing_from_step1 = new_missing
                break
            missing_from_step1 = new_missing

        stats = {
            "index_batches_total": len(paper_urls),
            "index_batches_success": index_success,
            "index_batches_failed": index_failed,
            "question_pass_chunks": question_pass_chunks,
            "question_repair_rounds": repair_rounds,
            "repaired_questions_count": repaired_count,
            "paper_parallel_tasks": len(paper_urls),
        }
        return questions, stats, missing_from_step1, repair_rounds, repaired_count

    def _tag_questions_with_text_llm(
        self,
        questions: List[Dict[str, Any]],
        warnings: List[str],
    ) -> tuple[List[Dict[str, Any]], Dict[str, int]]:
        if not questions:
            return questions, {
                "question_count": 0,
                "tagged_question_count": 0,
                "group_count": 0,
                "group_pass_chunks": 0,
                "refine_pass_chunks": 0,
                "filtered_candidate_count_avg": 0,
            }
        if self.knowledge_tagging_mode == "off":
            tagged_count = sum(
                1
                for question in questions
                if isinstance(question, dict)
                and isinstance(question.get("skill_tags"), list)
                and any(isinstance(tag, str) and tag.strip() for tag in question.get("skill_tags", []))
            )
            return questions, {
                "question_count": len(questions),
                "tagged_question_count": tagged_count,
                "group_count": 0,
                "group_pass_chunks": 0,
                "refine_pass_chunks": 0,
                "filtered_candidate_count_avg": 0,
                "existing_tagged_count": tagged_count,
            }
        candidate_points = _extract_points_from_nodes(self.nodes)
        candidate_groups = _build_knowledge_groups(candidate_points)
        tagged_by_id: Dict[str, List[str]] = {}
        group_pass_chunks = 0
        refine_pass_chunks = 0
        filtered_candidate_count_total = 0
        filtered_candidate_count_samples = 0
        existing_tagged_count = 0
        questions_to_tag: List[Dict[str, Any]] = []
        for question in questions:
            tags = question.get("skill_tags") if isinstance(question, dict) and isinstance(question.get("skill_tags"), list) else []
            clean_tags = [tag for tag in tags if isinstance(tag, str) and tag.strip()]
            qid = question.get("question_id") if isinstance(question, dict) else None
            if clean_tags and isinstance(qid, str) and qid:
                tagged_by_id[qid] = clean_tags
                existing_tagged_count += 1
            else:
                questions_to_tag.append(question)
        question_chunks = [chunk for chunk in _chunk_list(questions_to_tag, self.question_chunk_size) if chunk]
        if question_chunks:
            max_workers = min(max(1, self.answer_concurrency), len(question_chunks))
            self._log_progress(
                "knowledge_tagging",
                "chunk_start",
                chunk_count=len(question_chunks),
                group_count=len(candidate_groups),
                candidate_count=len(candidate_points),
                max_workers=max_workers,
            )
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                tasks: List[tuple[int, float, Any]] = []
                for chunk_index, chunk in enumerate(question_chunks, start=1):
                    tasks.append(
                        (
                            chunk_index,
                            perf_counter(),
                            executor.submit(
                                self._run_knowledge_tag_chunk,
                                chunk_index,
                                chunk,
                                candidate_points,
                                candidate_groups,
                            ),
                        )
                    )
                for chunk_index, chunk_started, future in tasks:
                    try:
                        chunk_result = future.result()
                    except Exception as exc:
                        warnings.append(f"knowledge_tagging chunk={chunk_index} failed: {exc}")
                        self._log_progress(
                            "knowledge_tagging",
                            "chunk_failed",
                            chunk=chunk_index,
                            elapsed_ms=round((perf_counter() - chunk_started) * 1000, 1),
                        )
                        continue
                    chunk_warnings = chunk_result.get("warnings", [])
                    if isinstance(chunk_warnings, list):
                        warnings.extend([item for item in chunk_warnings if isinstance(item, str) and item.strip()])
                    group_pass_chunks += int(chunk_result.get("group_pass_chunks", 0) or 0)
                    refine_pass_chunks += int(chunk_result.get("refine_pass_chunks", 0) or 0)
                    filtered_candidate_count_total += int(chunk_result.get("filtered_candidate_count", 0) or 0)
                    filtered_candidate_count_samples += 1
                    tagged_items = chunk_result.get("tagged_by_id", {})
                    if isinstance(tagged_items, dict):
                        for qid, tags in tagged_items.items():
                            if isinstance(qid, str) and isinstance(tags, list):
                                tagged_by_id[qid] = [tag for tag in tags if isinstance(tag, str) and tag.strip()]
                    self._log_progress(
                        "knowledge_tagging",
                        "chunk_done",
                        chunk=chunk_index,
                        tagged_count=len(tagged_items) if isinstance(tagged_items, dict) else 0,
                        filtered_candidate_count=int(chunk_result.get("filtered_candidate_count", 0) or 0),
                        elapsed_ms=round((perf_counter() - chunk_started) * 1000, 1),
                    )
        tagged_questions: List[Dict[str, Any]] = []
        tagged_count = 0
        for question in questions:
            item = dict(question)
            qid = item.get("question_id")
            if isinstance(qid, str) and qid in tagged_by_id:
                item["skill_tags"] = tagged_by_id[qid]
                if item["skill_tags"]:
                    tagged_count += 1
            tagged_questions.append(item)
        return tagged_questions, {
            "question_count": len(questions),
            "tagged_question_count": tagged_count,
            "group_count": len(candidate_groups),
            "group_pass_chunks": group_pass_chunks,
            "refine_pass_chunks": refine_pass_chunks,
            "filtered_candidate_count_avg": round(
                filtered_candidate_count_total / max(1, filtered_candidate_count_samples)
            ),
            "existing_tagged_count": existing_tagged_count,
        }

    def _run_knowledge_tag_chunk(
        self,
        chunk_index: int,
        chunk: List[Dict[str, Any]],
        candidate_points: List[Dict[str, Any]],
        candidate_groups: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        knowledge_groups_by_question: List[Dict[str, Any]] = []
        chunk_warnings: List[str] = []
        group_pass_chunks = 0
        refine_pass_chunks = 0
        self._log_progress(
            "knowledge_tagging",
            "chunk_worker_start",
            chunk=chunk_index,
            question_count=len(chunk),
        )
        if candidate_groups and self.knowledge_tagging_mode != "fast":
            grouping_started = perf_counter()
            try:
                group_data = self._call_json_with_profile(
                    self.text_profile,
                    prompt=_knowledge_group_prompt(chunk, candidate_groups),
                    data_urls=[],
                    expected_list_key=expected_list_key("knowledge_grouping"),
                )
                knowledge_groups_by_question = _normalize_knowledge_groups_by_question(
                    chunk,
                    group_data.get("items", []),
                )
                group_pass_chunks = 1
                self._log_progress(
                    "knowledge_tagging",
                    "group_done",
                    chunk=chunk_index,
                    selected_group_count=sum(
                        len(item.get("knowledge_groups", []))
                        for item in knowledge_groups_by_question
                        if isinstance(item, dict) and isinstance(item.get("knowledge_groups"), list)
                    ),
                    elapsed_ms=round((perf_counter() - grouping_started) * 1000, 1),
                )
            except Exception as exc:
                chunk_warnings.append(f"knowledge_grouping chunk failed: {exc}")
                self._log_progress(
                    "knowledge_tagging",
                    "group_failed",
                    chunk=chunk_index,
                    elapsed_ms=round((perf_counter() - grouping_started) * 1000, 1),
                )
                knowledge_groups_by_question = []
        if self.knowledge_tagging_mode == "fast":
            filtered_candidate_points = candidate_points[: min(len(candidate_points), 32)]
        else:
            filtered_candidate_points = _filter_candidate_points_by_groups(
                candidate_points,
                knowledge_groups_by_question,
            )
        tagged_by_id: Dict[str, List[str]] = {}
        refine_started = perf_counter()
        try:
            data = self._call_json_with_profile(
                self.text_profile,
                prompt=_knowledge_tag_prompt(chunk, filtered_candidate_points, knowledge_groups_by_question),
                data_urls=[],
                expected_list_key=expected_list_key("knowledge_tagging"),
            )
            refine_pass_chunks = 1
        except Exception as exc:
            chunk_warnings.append(f"knowledge_tagging chunk failed: {exc}")
            self._log_progress(
                "knowledge_tagging",
                "refine_failed",
                chunk=chunk_index,
                filtered_candidate_count=len(filtered_candidate_points),
                elapsed_ms=round((perf_counter() - refine_started) * 1000, 1),
            )
            return {
                "tagged_by_id": tagged_by_id,
                "group_pass_chunks": group_pass_chunks,
                "refine_pass_chunks": 0,
                "filtered_candidate_count": len(filtered_candidate_points),
                "warnings": chunk_warnings,
            }
        items = data.get("items", [])
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                qid = _canonical_question_id(item.get("question_id"))
                if not isinstance(qid, str) or not qid:
                    continue
                tags = item.get("knowledge_points")
                if not isinstance(tags, list):
                    continue
                tagged_by_id[qid] = [tag for tag in tags if isinstance(tag, str) and tag.strip()]
        self._log_progress(
            "knowledge_tagging",
            "refine_done",
            chunk=chunk_index,
            tagged_count=len(tagged_by_id),
            filtered_candidate_count=len(filtered_candidate_points),
            elapsed_ms=round((perf_counter() - refine_started) * 1000, 1),
        )
        return {
            "tagged_by_id": tagged_by_id,
            "group_pass_chunks": group_pass_chunks,
            "refine_pass_chunks": refine_pass_chunks,
            "filtered_candidate_count": len(filtered_candidate_points),
            "warnings": chunk_warnings,
        }

    def _run_answer_raw_trace_parallel(
        self,
        answer_urls: List[str],
        warnings: List[str],
        *,
        student_id: str,
        run_token: str,
        selected_blocks: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        crop_output_root: Optional[Path] = None
        debug_output_root: Optional[Path] = None
        saved_crop_paths: List[str] = []
        raw_vlm_debug_records: List[Dict[str, Any]] = []
        plan_build_start = perf_counter()
        if self.answer_segment_save_crops:
            student_token = self._safe_path_token(student_id) or "unknown"
            run_token_safe = self._safe_path_token(run_token) or datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            crop_output_root = self._resolve_answer_segment_crop_root() / student_token / run_token_safe
        if self.answer_trace_save_debug_json:
            student_token = self._safe_path_token(student_id) or "unknown"
            run_token_safe = self._safe_path_token(run_token) or datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            debug_output_root = self._resolve_answer_trace_debug_root() / student_token / run_token_safe
        page_count = len(answer_urls)
        if page_count <= 0:
            return [], {
                "batches_total": 0,
                "batches_success": 0,
                "batches_failed": 0,
                "objective_pass_chunks": 0,
                "subjective_pass_chunks": 0,
                "answer_parallel_tasks": 0,
                "saved_crop_count": 0,
                "saved_crop_dir": None,
                "plan_build_ms": round((perf_counter() - plan_build_start) * 1000, 1),
                "raw_vlm_ms": 0.0,
                "structuring_ms": 0.0,
                "nonempty_raw_text_count": 0,
                "raw_plan_count": 0,
                "structured_answer_count": 0,
                "answer_trace_debug_dir": str(debug_output_root) if debug_output_root is not None else None,
                "raw_vlm_debug_json_path": None,
            }

        raw_plan: List[Dict[str, Any]] = []
        selected_items = selected_blocks if isinstance(selected_blocks, list) else []
        answer_block_mode = "manual_confirmed" if selected_items else "auto"
        if selected_items:
            raw_plan = self._build_manual_answer_slice_plan(
                answer_urls=answer_urls,
                answer_contexts=[],
                selected_blocks=selected_items,
                crop_output_root=crop_output_root,
                saved_crop_paths=saved_crop_paths,
                warnings=warnings,
            )
        else:
            for page_index, page_url in enumerate(answer_urls):
                if not isinstance(page_url, str) or not page_url.strip():
                    warnings.append(f"answer page {page_index + 1} missing data_url")
                    continue
                page_slices = self._build_answer_slice_plan_for_page(
                    page_url=page_url,
                    page_index=page_index,
                    answer_contexts=[],
                    crop_output_root=crop_output_root,
                    saved_crop_paths=saved_crop_paths,
                    warnings=warnings,
                )
                raw_plan.extend(page_slices)
        plan_build_ms = round((perf_counter() - plan_build_start) * 1000, 1)
        self._log_progress(
            "answer_trace",
            "plan_built",
            answer_block_mode=answer_block_mode,
            page_count=page_count,
            raw_plan_count=len(raw_plan),
            saved_crop_count=len(saved_crop_paths),
            elapsed_ms=plan_build_ms,
        )

        if not raw_plan:
            raw_vlm_debug_json_path = self._save_answer_trace_debug_json(
                output_root=debug_output_root,
                student_id=student_id,
                run_token=run_token,
                payload={
                    "student_id": student_id,
                    "run_token": run_token,
                    "answer_block_mode": answer_block_mode,
                    "raw_plan_count": 0,
                    "nonempty_raw_text_count": 0,
                    "records": [],
                },
                warnings=warnings,
            )
            return [], {
                "batches_total": 0,
                "batches_success": 0,
                "batches_failed": 0,
                "objective_pass_chunks": 0,
                "subjective_pass_chunks": 0,
                "answer_parallel_tasks": 0,
                "saved_crop_count": len(saved_crop_paths),
                "saved_crop_dir": str(crop_output_root) if crop_output_root and saved_crop_paths else None,
                "answer_block_mode": answer_block_mode,
                "plan_build_ms": plan_build_ms,
                "raw_vlm_ms": 0.0,
                "structuring_ms": 0.0,
                "nonempty_raw_text_count": 0,
                "raw_plan_count": 0,
                "structured_answer_count": 0,
                "answer_trace_debug_dir": str(debug_output_root) if debug_output_root is not None else None,
                "raw_vlm_debug_json_path": raw_vlm_debug_json_path,
            }

        task_ok: Dict[str, bool] = {item["source"]: False for item in raw_plan if isinstance(item, dict)}
        page_raw_items: List[Dict[str, Any]] = []
        raw_retry_limit = 1
        raw_submit_count = 0

        def _build_raw_item(spec: Dict[str, Any], raw_text: str) -> Dict[str, Any]:
            source = spec.get("source") if isinstance(spec.get("source"), str) else "unknown"
            page_index = spec.get("page_index") if isinstance(spec.get("page_index"), int) else 0
            section_name = spec.get("section_name") if isinstance(spec.get("section_name"), str) else None
            spec_contexts = spec.get("contexts") if isinstance(spec.get("contexts"), list) else []
            context_ids = [
                ctx.get("question_id")
                for ctx in spec_contexts
                if isinstance(ctx, dict) and isinstance(ctx.get("question_id"), str) and ctx.get("question_id")
            ]
            return {
                "source": source,
                "page_index": page_index,
                "section_name": section_name,
                "raw_text": f"[source={source} section={section_name} page={page_index}]\n{raw_text.strip()}",
                "context_question_ids": context_ids,
            }

        # Phase 1: each segmented block runs raw VLM recognition concurrently.
        # Phase 2: aggregate all recognized traces and hand them to LLM for final
        # classification + structuring, without using detector class names as type routing.
        raw_vlm_start = perf_counter()
        raw_max_workers = min(max(4, self.answer_concurrency), max(1, len(raw_plan)))
        self._log_progress(
            "answer_trace",
            "raw_vlm_start",
            task_count=len(raw_plan),
            max_workers=raw_max_workers,
        )
        with ThreadPoolExecutor(max_workers=raw_max_workers) as raw_executor:
            raw_future_map: Dict[Any, Dict[str, Any]] = {}

            for spec in raw_plan:
                page_index = spec["page_index"] if isinstance(spec.get("page_index"), int) else 0
                page_url = spec.get("data_url")
                page_contexts = spec.get("contexts") if isinstance(spec.get("contexts"), list) else []
                section_name = spec.get("section_name") if isinstance(spec.get("section_name"), str) else "answer-section"
                if not isinstance(page_url, str) or not page_url.strip():
                    continue
                prepared_page_url = self._prepare_student_trace_data_url(page_url, warnings, str(spec.get("source") or "unknown"))
                prompt_text = _answer_raw_section_prompt(
                    page_contexts,
                    page_index=page_index,
                    section_name=section_name,
                    segment_class_name=(
                        spec.get("segment_class_name")
                        if isinstance(spec.get("segment_class_name"), str)
                        else None
                    ),
                )
                future = raw_executor.submit(
                    self._run_harness_stage,
                    HARNESS_STAGE_ANSWER_RAW_TRACE,
                    prompt=prompt_text,
                    data_urls=[prepared_page_url],
                    profile=self.profile,
                )
                raw_submit_count += 1
                raw_future_map[future] = {
                    "spec": spec,
                    "prompt": prompt_text,
                    "attempt": 0,
                    "started_at": perf_counter(),
                }

            while raw_future_map:
                future = next(as_completed(list(raw_future_map.keys())))
                meta = raw_future_map.pop(future)
                spec = meta["spec"]
                prompt_text = meta["prompt"] if isinstance(meta.get("prompt"), str) else ""
                attempt = int(meta["attempt"])
                task_started = float(meta["started_at"])
                source = spec.get("source") if isinstance(spec.get("source"), str) else "unknown"
                page_index = spec.get("page_index") if isinstance(spec.get("page_index"), int) else 0
                spec_contexts = spec.get("contexts") if isinstance(spec.get("contexts"), list) else []
                context_question_ids = [
                    ctx.get("question_id")
                    for ctx in spec_contexts
                    if isinstance(ctx, dict) and isinstance(ctx.get("question_id"), str) and ctx.get("question_id")
                ]
                try:
                    raw_text = future.result()
                    if isinstance(raw_text, str) and raw_text.strip():
                        raw_item = _build_raw_item(spec, raw_text)
                        page_raw_items.append(raw_item)
                        task_ok[source] = True
                        raw_vlm_debug_records.append(
                            {
                                "source": source,
                                "page_index": page_index,
                                "section_name": spec.get("section_name"),
                                "segment_class_name": spec.get("segment_class_name"),
                                "segment_confidence": spec.get("segment_confidence"),
                                "context_question_ids": raw_item.get("context_question_ids"),
                                "saved_crop_path": spec.get("saved_crop_path"),
                                "attempt": attempt,
                                "status": "success",
                                "elapsed_ms": round((perf_counter() - task_started) * 1000, 1),
                                "prompt": prompt_text,
                                "raw_text": raw_text,
                            }
                        )
                        self._log_progress(
                            "answer_trace",
                            "raw_vlm_done",
                            source=source,
                            page=page_index + 1,
                            raw_text_length=len(raw_text.strip()),
                            elapsed_ms=round((perf_counter() - task_started) * 1000, 1),
                        )
                        continue
                    raise ValueError("empty raw text")
                except Exception as exc:
                    if attempt < raw_retry_limit:
                        page_url = spec.get("data_url")
                        page_contexts = spec.get("contexts") if isinstance(spec.get("contexts"), list) else []
                        section_name = spec.get("section_name") if isinstance(spec.get("section_name"), str) else "answer-section"
                        prepared_page_url = (
                            self._prepare_student_trace_data_url(page_url, warnings, source)
                            if isinstance(page_url, str) and page_url.strip()
                            else None
                        )
                        retry_prompt_text = _answer_raw_section_prompt(
                            page_contexts,
                            page_index=page_index,
                            section_name=section_name,
                            segment_class_name=(
                                spec.get("segment_class_name")
                                if isinstance(spec.get("segment_class_name"), str)
                                else None
                            ),
                        )
                        retry_future = raw_executor.submit(
                            self._run_harness_stage,
                            HARNESS_STAGE_ANSWER_RAW_TRACE,
                            prompt=retry_prompt_text,
                            data_urls=[prepared_page_url] if isinstance(prepared_page_url, str) and prepared_page_url.strip() else [],
                            profile=self.profile,
                        )
                        raw_future_map[retry_future] = {
                            "spec": spec,
                            "prompt": retry_prompt_text,
                            "attempt": attempt + 1,
                            "started_at": perf_counter(),
                        }
                        self._log_progress(
                            "answer_trace",
                            "raw_vlm_retry",
                            source=source,
                            page=page_index + 1,
                            attempt=attempt + 1,
                            elapsed_ms=round((perf_counter() - task_started) * 1000, 1),
                        )
                        continue
                    warnings.append(f"answer_raw_text {source} failed: {exc}")
                    raw_vlm_debug_records.append(
                        {
                            "source": source,
                            "page_index": page_index,
                            "section_name": spec.get("section_name"),
                            "segment_class_name": spec.get("segment_class_name"),
                            "segment_confidence": spec.get("segment_confidence"),
                            "context_question_ids": context_question_ids,
                            "saved_crop_path": spec.get("saved_crop_path"),
                            "attempt": attempt,
                            "status": "failed",
                            "elapsed_ms": round((perf_counter() - task_started) * 1000, 1),
                            "prompt": prompt_text,
                            "error": str(exc),
                        }
                    )
                    self._log_progress(
                        "answer_trace",
                        "raw_vlm_failed",
                        source=source,
                        page=page_index + 1,
                        elapsed_ms=round((perf_counter() - task_started) * 1000, 1),
                    )

            raw_vlm_ms = round((perf_counter() - raw_vlm_start) * 1000, 1)

        raw_vlm_debug_json_path = self._save_answer_trace_debug_json(
            output_root=debug_output_root,
            student_id=student_id,
            run_token=run_token,
            payload={
                "student_id": student_id,
                "run_token": run_token,
                "answer_block_mode": answer_block_mode,
                "raw_plan_count": len(raw_plan),
                "nonempty_raw_text_count": len(page_raw_items),
                "raw_vlm_ms": raw_vlm_ms,
                "raw_plan": [
                    {
                        "source": spec.get("source"),
                        "page_index": spec.get("page_index"),
                        "section_name": spec.get("section_name"),
                        "segment_class_name": spec.get("segment_class_name"),
                        "segment_confidence": spec.get("segment_confidence"),
                        "saved_crop_path": spec.get("saved_crop_path"),
                        "context_question_ids": [
                            ctx.get("question_id")
                            for ctx in (spec.get("contexts") if isinstance(spec.get("contexts"), list) else [])
                            if isinstance(ctx, dict) and isinstance(ctx.get("question_id"), str) and ctx.get("question_id")
                        ],
                    }
                    for spec in raw_plan
                    if isinstance(spec, dict)
                ],
                "records": raw_vlm_debug_records,
            },
            warnings=warnings,
        )

        objective_pass_chunks = 0
        subjective_pass_chunks = 0
        for spec in raw_plan:
            if not isinstance(spec, dict):
                continue
            segment_class_name = spec.get("segment_class_name") if isinstance(spec.get("segment_class_name"), str) else None
            if segment_class_name in {"objective_problem", "fillin_problem"}:
                objective_pass_chunks += 1
                continue
            if segment_class_name == "subjective_problem":
                subjective_pass_chunks += 1
                continue
            contexts = spec.get("contexts")
            context_items = contexts if isinstance(contexts, list) else []
            if context_items and all(_is_choice_or_blank(ctx.get("question_type")) for ctx in context_items if isinstance(ctx, dict)):
                objective_pass_chunks += 1
            else:
                subjective_pass_chunks += 1

        return page_raw_items, {
            "batches_total": len(raw_plan),
            "batches_success": sum(1 for ok in task_ok.values() if ok),
            "batches_failed": sum(1 for ok in task_ok.values() if not ok),
            "objective_pass_chunks": objective_pass_chunks,
            "subjective_pass_chunks": subjective_pass_chunks,
            "answer_parallel_tasks": raw_submit_count,
            "saved_crop_count": len(saved_crop_paths),
            "saved_crop_dir": str(crop_output_root) if crop_output_root and saved_crop_paths else None,
            "answer_block_mode": answer_block_mode,
            "plan_build_ms": plan_build_ms,
            "raw_vlm_ms": raw_vlm_ms,
            "structuring_ms": 0.0,
            "nonempty_raw_text_count": len(page_raw_items),
            "raw_plan_count": len(raw_plan),
            "structured_answer_count": 0,
            "answer_trace_debug_dir": str(debug_output_root) if debug_output_root is not None else None,
            "raw_vlm_debug_json_path": raw_vlm_debug_json_path,
        }

    def _run_answer_trace_postprocess(
        self,
        questions: List[Dict[str, Any]],
        page_raw_items: List[Dict[str, Any]],
        warnings: List[str],
        *,
        raw_stage_stats: Dict[str, Any],
        answer_urls: Optional[List[str]] = None,
        student_id: Optional[str] = None,
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
        answer_contexts = _build_answer_contexts(questions)
        answer_context_map = _build_answer_context_map(answer_contexts)
        raw_answers: List[Dict[str, Any]] = []
        unmatched_answer_traces: List[Dict[str, Any]] = []
        struct_retry_limit = 1
        structuring_started_at: Optional[float] = None
        structuring_finished_at: Optional[float] = None
        structuring_debug_json_path: Optional[str] = None
        alignment_debug_json_path: Optional[str] = None
        alignment_ms = 0.0
        structuring_prompt = _answer_struct_and_align_prompt(answer_contexts, page_raw_items) if page_raw_items else ""
        structuring_debug_root: Optional[Path] = None
        if isinstance(raw_stage_stats.get("answer_trace_debug_dir"), str) and str(raw_stage_stats.get("answer_trace_debug_dir")).strip():
            structuring_debug_root = Path(str(raw_stage_stats.get("answer_trace_debug_dir")))

        def _save_structuring_debug(
            *,
            status: str,
            prompt: str,
            llm_response: Optional[Dict[str, Any]],
            elapsed_ms: float,
            reason: str = "",
            error: str = "",
        ) -> Optional[str]:
            payload: Dict[str, Any] = {
                "status": status,
                "raw_item_count": len(page_raw_items),
                "page_raw_items": page_raw_items,
                "prompt": prompt,
                "llm_response": llm_response,
                "normalized_answers": raw_answers,
                "unmatched_traces": unmatched_answer_traces,
            }
            if reason:
                payload["reason"] = reason
            if error:
                payload["error"] = error
            if elapsed_ms >= 0:
                payload["elapsed_ms"] = elapsed_ms
            return self._save_answer_trace_debug_json(
                output_root=structuring_debug_root,
                student_id="unknown",
                run_token="unknown",
                payload=payload,
                warnings=warnings,
                filename="structuring_outputs.json",
            )

        def _save_alignment_debug(
            *,
            status: str,
            prompt: str,
            preliminary_answers: List[Dict[str, Any]],
            llm_response: Optional[Dict[str, Any]],
            elapsed_ms: float,
            reason: str = "",
            error: str = "",
        ) -> Optional[str]:
            payload: Dict[str, Any] = {
                "status": status,
                "raw_item_count": len(page_raw_items),
                "page_raw_items": page_raw_items,
                "prompt": prompt,
                "preliminary_answers": preliminary_answers,
                "llm_response": llm_response,
                "normalized_answers": raw_answers,
                "unmatched_traces": unmatched_answer_traces,
                "elapsed_ms": elapsed_ms,
            }
            if reason:
                payload["reason"] = reason
            if error:
                payload["error"] = error
            return self._save_answer_trace_debug_json(
                output_root=structuring_debug_root,
                student_id="unknown",
                run_token="unknown",
                payload=payload,
                warnings=warnings,
                filename="alignment_outputs.json",
            )

        if not page_raw_items:
            warnings.append("answer_struct aggregate skipped: no non-empty VLM raw text")
            structuring_debug_json_path = _save_structuring_debug(
                status="skipped",
                reason="no_nonempty_vlm_raw_text",
                prompt=structuring_prompt,
                llm_response=None,
                elapsed_ms=-1.0,
            )
            alignment_debug_json_path = _save_alignment_debug(
                status="skipped",
                reason="no_nonempty_vlm_raw_text",
                prompt="",
                preliminary_answers=[],
                llm_response=None,
                elapsed_ms=0.0,
            )
        else:
            structuring_started_at = perf_counter()
            raw_item_chunks = _chunk_raw_answer_items(page_raw_items, self.answer_structuring_chunk_size)
            if not raw_item_chunks:
                raw_item_chunks = [page_raw_items]
            max_workers = min(max(1, self.answer_concurrency), len(raw_item_chunks))
            self._log_progress(
                "answer_trace",
                "structuring_start",
                raw_item_count=len(page_raw_items),
                chunk_count=len(raw_item_chunks),
                max_workers=max_workers,
            )
            structuring_response_data: Optional[Dict[str, Any]] = None
            alignment_response_data: Optional[Dict[str, Any]] = None
            all_preliminary_answers: List[Dict[str, Any]] = []

            def _normalize_answer_batch(items: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
                normalized_items: List[Dict[str, Any]] = []
                unmatched_items: List[Dict[str, Any]] = []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    model_page_index = item.get("page_index") if isinstance(item.get("page_index"), int) else None
                    normalized = _normalize_answer_item(
                        item,
                        answer_context_map,
                        source_stage="answer_struct",
                        page_index=model_page_index,
                    )
                    if normalized is not None:
                        normalized_items.append(normalized)
                    else:
                        unmatched_items.append(
                            {
                                "question_id": item.get("question_id"),
                                "sub_question_id": item.get("sub_question_id"),
                                "reason": "question_id_not_in_step1_or_invalid",
                            }
                        )
                return normalized_items, unmatched_items

            def _run_structuring_chunk(chunk_index: int, raw_chunk: List[Dict[str, Any]]) -> Dict[str, Any]:
                chunk_started = perf_counter()
                chunk_contexts = _select_answer_contexts_for_raw_items(answer_contexts, raw_chunk)
                prompt = _answer_struct_and_align_prompt(chunk_contexts, raw_chunk)
                attempt = 0
                last_exc: Optional[Exception] = None
                while attempt <= struct_retry_limit:
                    try:
                        data = self._run_harness_stage(
                            HARNESS_STAGE_ANSWER_STRUCT_AND_ALIGN,
                            prompt=prompt,
                            data_urls=[],
                            profile=self.text_profile,
                        )
                        batch_answers = data.get("answers", []) if isinstance(data, dict) else []
                        if not isinstance(batch_answers, list):
                            batch_answers = []
                        normalized_items, unmatched_items = _normalize_answer_batch(batch_answers)
                        if not normalized_items:
                            raise ValueError("combined answer struct/alignment returned no normalized answers")
                        self._log_progress(
                            "answer_trace",
                            "structuring_chunk_done",
                            chunk=chunk_index,
                            raw_item_count=len(raw_chunk),
                            context_count=len(chunk_contexts),
                            answer_count=len(normalized_items),
                            mode="combined",
                            elapsed_ms=round((perf_counter() - chunk_started) * 1000, 1),
                        )
                        return {
                            "status": "success",
                            "prompt": prompt,
                            "llm_response": data if isinstance(data, dict) else None,
                            "preliminary_answers": batch_answers,
                            "normalized": normalized_items,
                            "unmatched": unmatched_items,
                            "elapsed_ms": round((perf_counter() - chunk_started) * 1000, 1),
                        }
                    except Exception as exc:
                        last_exc = exc
                        if attempt < struct_retry_limit:
                            attempt += 1
                            self._log_progress(
                                "answer_trace",
                                "structuring_retry",
                                chunk=chunk_index,
                                raw_item_count=len(raw_chunk),
                                attempt=attempt,
                                elapsed_ms=round((perf_counter() - chunk_started) * 1000, 1),
                            )
                            continue
                        break
                legacy_started = perf_counter()
                legacy_prompt = _answer_struct_from_raw_texts_prompt(chunk_contexts, raw_chunk)
                legacy_alignment_prompt = ""
                legacy_response: Optional[Dict[str, Any]] = None
                legacy_alignment_response: Optional[Dict[str, Any]] = None
                legacy_preliminary_answers: List[Dict[str, Any]] = []
                try:
                    legacy_data = self._run_harness_stage(
                        HARNESS_STAGE_ANSWER_STRUCTURING,
                        prompt=legacy_prompt,
                        data_urls=[],
                        profile=self.text_profile,
                    )
                    legacy_response = legacy_data if isinstance(legacy_data, dict) else None
                    legacy_preliminary = legacy_data.get("answers", []) if isinstance(legacy_data, dict) else []
                    legacy_preliminary_answers = legacy_preliminary if isinstance(legacy_preliminary, list) else []
                    legacy_aligned_answers = legacy_preliminary_answers
                    legacy_alignment_prompt = _answer_alignment_prompt(chunk_contexts, legacy_preliminary_answers, raw_chunk)
                    alignment_started = perf_counter()
                    try:
                        legacy_alignment_data = self._run_harness_stage(
                            HARNESS_STAGE_ANSWER_ALIGNMENT,
                            prompt=legacy_alignment_prompt,
                            data_urls=[],
                            profile=self.text_profile,
                        )
                        legacy_alignment_response = legacy_alignment_data if isinstance(legacy_alignment_data, dict) else None
                        candidate_answers = legacy_alignment_data.get("answers", []) if isinstance(legacy_alignment_data, dict) else []
                        if isinstance(candidate_answers, list) and candidate_answers:
                            legacy_aligned_answers = candidate_answers
                    except Exception as alignment_exc:
                        warnings.append(f"answer_alignment fallback chunk={chunk_index} failed: {alignment_exc}")
                    normalized_items, unmatched_items = _normalize_answer_batch(legacy_aligned_answers)
                    if not normalized_items:
                        raise ValueError("legacy answer struct/alignment returned no normalized answers")
                    return {
                        "status": "legacy_fallback_success",
                        "prompt": legacy_prompt,
                        "llm_response": legacy_response,
                        "alignment_prompt": legacy_alignment_prompt,
                        "alignment_response": legacy_alignment_response,
                        "preliminary_answers": legacy_preliminary_answers,
                        "normalized": normalized_items,
                        "unmatched": unmatched_items,
                        "alignment_ms": round((perf_counter() - alignment_started) * 1000, 1),
                        "elapsed_ms": round((perf_counter() - legacy_started) * 1000, 1),
                        "reason": str(last_exc) if last_exc is not None else "",
                    }
                except Exception as legacy_exc:
                    return {
                        "status": "failed",
                        "prompt": prompt,
                        "llm_response": None,
                        "preliminary_answers": [],
                        "normalized": [],
                        "unmatched": [],
                        "elapsed_ms": round((perf_counter() - chunk_started) * 1000, 1),
                        "error": f"{last_exc}; legacy fallback failed: {legacy_exc}",
                    }

            chunk_results: List[Dict[str, Any]] = []
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [
                    executor.submit(_run_structuring_chunk, chunk_index, raw_chunk)
                    for chunk_index, raw_chunk in enumerate(raw_item_chunks, start=1)
                ]
                for future in as_completed(futures):
                    chunk_results.append(future.result())

            chunk_results.sort(key=lambda item: str(item.get("prompt") or ""))
            for result in chunk_results:
                if result.get("status") == "failed":
                    warnings.append(f"answer_struct chunk failed: {result.get('error')}")
                    continue
                normalized = result.get("normalized") if isinstance(result.get("normalized"), list) else []
                unmatched = result.get("unmatched") if isinstance(result.get("unmatched"), list) else []
                raw_answers.extend([item for item in normalized if isinstance(item, dict)])
                unmatched_answer_traces.extend([item for item in unmatched if isinstance(item, dict)])
                preliminary = result.get("preliminary_answers") if isinstance(result.get("preliminary_answers"), list) else []
                all_preliminary_answers.extend([item for item in preliminary if isinstance(item, dict)])
                if structuring_response_data is None and isinstance(result.get("llm_response"), dict):
                    structuring_response_data = result.get("llm_response")
                if alignment_response_data is None and isinstance(result.get("alignment_response"), dict):
                    alignment_response_data = result.get("alignment_response")
                if isinstance(result.get("alignment_ms"), (int, float)):
                    alignment_ms += float(result.get("alignment_ms"))

            structuring_finished_at = perf_counter()
            structuring_debug_json_path = _save_structuring_debug(
                status="success" if raw_answers else "failed",
                prompt=structuring_prompt,
                llm_response=structuring_response_data,
                elapsed_ms=round((structuring_finished_at - structuring_started_at) * 1000, 1),
                reason=f"chunk_count={len(raw_item_chunks)}",
            )
            alignment_debug_json_path = _save_alignment_debug(
                status="fallback_to_preliminary",
                prompt="",
                preliminary_answers=all_preliminary_answers,
                llm_response=alignment_response_data,
                elapsed_ms=round(alignment_ms, 1),
                reason="alignment merged into chunked structuring stage",
            )
        raw_answers.extend(
            self._build_raw_text_fallback_answers(
                page_raw_items=page_raw_items,
                answer_context_map=answer_context_map,
            )
        )
        if structuring_started_at is not None:
            structuring_end = structuring_finished_at if structuring_finished_at is not None else perf_counter()
            structuring_ms = round((structuring_end - structuring_started_at) * 1000, 1)
        else:
            structuring_ms = 0.0
        self._log_progress(
            "answer_trace",
            "structuring_complete",
            raw_answer_count=len(raw_answers),
            unmatched_count=len(unmatched_answer_traces),
            elapsed_ms=structuring_ms,
        )
        # 局部高精选择题识别流程集成
        choice_raw_answers = self._extract_cropped_choice_answers(
            questions=questions,
            answer_urls=answer_urls or [],
            student_id=student_id,
            answer_context_map=answer_context_map,
            warnings=warnings,
            structuring_debug_root=structuring_debug_root,
        )
        if choice_raw_answers:
            choice_map = {item["question_id"]: item for item in choice_raw_answers if item.get("question_id")}
            filtered_raw_answers = [item for item in raw_answers if item.get("question_id") not in choice_map]
            filtered_raw_answers.extend(choice_raw_answers)
            raw_answers = filtered_raw_answers
            warnings.append(f"merged {len(choice_raw_answers)} choice answers from high-precision cropped VLM recognition.")

        answer_stats = dict(raw_stage_stats)
        answer_stats["structuring_ms"] = structuring_ms
        answer_stats["alignment_ms"] = alignment_ms
        answer_stats["structured_answer_count"] = len(raw_answers)
        answer_stats["answer_structuring_chunk_count"] = len(_chunk_raw_answer_items(page_raw_items, self.answer_structuring_chunk_size)) if page_raw_items else 0
        answer_stats["structuring_debug_json_path"] = structuring_debug_json_path
        answer_stats["alignment_debug_json_path"] = alignment_debug_json_path
        return raw_answers, unmatched_answer_traces, answer_stats

    def _extract_cropped_choice_answers(
        self,
        questions: List[Dict[str, Any]],
        answer_urls: List[str],
        student_id: Optional[str],
        answer_context_map: Dict[str, Dict[str, Any]],
        warnings: List[str],
        structuring_debug_root: Optional[Path],
    ) -> List[Dict[str, Any]]:
        if cv2 is None or np is None:
            warnings.append("choice crop skipped: cv2 or numpy is not available")
            return []

        choice_questions = [
            q for q in questions
            if _is_choice_question_type(q.get("question_type"))
        ]
        if not choice_questions:
            return []

        choice_raw_answers = []
        for page_index, page_url in enumerate(answer_urls):
            try:
                prepared_page_url = self._prepare_student_trace_data_url(page_url, warnings, f"page_{page_index+1}_choice_loc")
                loc_prompt = (
                    "帮我定位图片中选择题的区域，使用bbox坐标指出。如果不存在选择题区域，请返回空列表。"
                    "输出格式必须为 JSON 对象，包含 'box_2d' 和 'label'，例如: "
                    "{'box_2d': [ymin, xmin, ymax, xmax], 'label': '选择题涂卡区域'}"
                )
                loc_res = self._call_json_with_profile(
                    self.profile,
                    prompt=loc_prompt,
                    data_urls=[prepared_page_url]
                )
                
                box_2d = loc_res.get("box_2d")
                if isinstance(box_2d, list) and len(box_2d) > 0:
                    if isinstance(box_2d[0], list):
                        box_2d = box_2d[0]
                    if len(box_2d) == 4:
                        ymin, xmin, ymax, xmax = box_2d
                        
                        mime, image_bytes = _decode_image_data_url(page_url)
                        page_image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
                        if page_image is not None:
                            height, width = page_image.shape[:2]
                            ymin_px = int(ymin * height / 1000.0)
                            xmin_px = int(xmin * width / 1000.0)
                            ymax_px = int(ymax * height / 1000.0)
                            xmax_px = int(xmax * width / 1000.0)
                            
                            left = max(0, min(xmin_px, width))
                            upper = max(0, min(ymin_px, height))
                            right = max(0, min(xmax_px, width))
                            lower = max(0, min(ymax_px, height))
                            
                            if right > left and lower > upper:
                                crop = page_image[upper:lower, left:right]
                                ok, encoded = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
                                if ok:
                                    crop_data_url = _image_bytes_to_data_url(encoded.tobytes(), "jpeg")
                                    
                                    saved_crop_path = None
                                    if self.answer_segment_save_crops and structuring_debug_root is not None:
                                        crop_name = f"choice_crop_page_{page_index+1}.jpg"
                                        crop_save_path = structuring_debug_root / crop_name
                                        try:
                                            structuring_debug_root.mkdir(parents=True, exist_ok=True)
                                            cv2.imwrite(str(crop_save_path), crop)
                                            saved_crop_path = str(crop_save_path)
                                        except Exception as write_err:
                                            warnings.append(f"failed to save choice crop: {write_err}")
                                    
                                    choice_candidates = [
                                        {
                                            "question_id": q.get("question_id"),
                                            "question_type": "choice",
                                            "knowledge_points": q.get("knowledge_points") or []
                                        }
                                        for q in choice_questions
                                    ]
                                    choice_prompt = PromptStore.vlm_answer_parser_prompt(choice_candidates)
                                    choice_vlm_res = self._call_json_with_profile(
                                        self.profile,
                                        prompt=choice_prompt,
                                        data_urls=[crop_data_url]
                                    )
                                    
                                    vlm_answers = choice_vlm_res.get("answers", [])
                                    if isinstance(vlm_answers, list):
                                        for raw_ans in vlm_answers:
                                            if not isinstance(raw_ans, dict):
                                                continue
                                            normalized = _normalize_answer_item(
                                                raw_ans,
                                                answer_context_map,
                                                source_stage="choice_crop_vlm",
                                                page_index=page_index
                                            )
                                            if normalized is not None:
                                                normalized["choice_crop_extracted"] = True
                                                if saved_crop_path:
                                                    normalized["trace"]["crop_path"] = saved_crop_path
                                                choice_raw_answers.append(normalized)
            except Exception as ex:
                warnings.append(f"choice crop and recognition failed at page={page_index+1}: {ex}")
        return choice_raw_answers

    def _run_answer_score_recognition(
        self,
        answer_urls: List[str],
        answer_contexts: List[Dict[str, Any]],
        answer_candidates: List[Dict[str, Any]],
        warnings: List[str],
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        from demo.stages.score_recognition import run_score_recognition_stage

        result = run_score_recognition_stage(
            answer_urls=answer_urls,
            answer_contexts=answer_contexts,
            answer_candidates=answer_candidates,
            profile=self.profile,
            harness_stage_answer_score=HARNESS_STAGE_ANSWER_SCORE,
            run_harness_stage=self._run_harness_stage,
            log_progress=self._log_progress,
            answer_score_sheet_prompt_fn=_answer_score_sheet_prompt,
            build_candidate_summaries_fn=_build_candidate_summaries,
            build_answer_context_map_fn=_build_answer_context_map,
            normalize_answer_item_fn=_normalize_answer_item,
            warnings_out=warnings,
        )
        stats = result.output.get("stats", {})
        return result.output.get("score_answers", []), stats

    def _run_reference_answer_common(
        self,
        *,
        stage_spec: HarnessStageSpec,
        prompt: str,
        data_urls: List[str],
        profile: Optional[Dict[str, Any]],
        answer_contexts: List[Dict[str, Any]],
        warnings: List[str],
        warning_prefix: str,
        failed_event: str,
        success_event: str,
        progress_count_key: str,
        progress_count_value: int,
        source_label: str,
    ) -> List[Dict[str, Any]]:
        started = perf_counter()
        try:
            data = self._run_harness_stage(
                stage_spec,
                prompt=prompt,
                data_urls=data_urls,
                profile=profile,
            )
        except Exception as exc:
            warnings.append(f"{warning_prefix} failed: {exc}")
            self._log_progress(
                "reference_answer",
                failed_event,
                **{
                    progress_count_key: progress_count_value,
                    "elapsed_ms": round((perf_counter() - started) * 1000, 1),
                },
            )
            return []
        context_map = _build_answer_context_map(answer_contexts)
        raw_items = data.get("reference_answers", []) if isinstance(data, dict) else []
        normalized: List[Dict[str, Any]] = []
        if isinstance(raw_items, list):
            for item in raw_items:
                parsed = _normalize_reference_answer_item(item, context_map)
                if parsed is not None:
                    parsed["source"] = source_label
                    normalized.append(parsed)
        self._log_progress(
            "reference_answer",
            success_event,
            **{
                progress_count_key: progress_count_value,
                "answer_count": len(normalized),
                "elapsed_ms": round((perf_counter() - started) * 1000, 1),
            },
        )
        return normalized

    @staticmethod
    def _extract_mineru_text_blocks(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract (bbox, text) pairs from MinerU content_list_v2 recursively."""
        blocks: List[Dict[str, Any]] = []

        def _visit(node: Any, depth: int = 0) -> None:
            if isinstance(node, dict):
                has_bbox = "bbox" in node
                text = str(node.get("content") or node.get("text") or "").strip()
                if has_bbox and text:
                    blocks.append({
                        "bbox": node["bbox"],
                        "text": text,
                        "type": str(node.get("type", "")),
                        "depth": depth,
                    })
                for child in node.values():
                    _visit(child, depth + 1)
            elif isinstance(node, list):
                for item in node:
                    _visit(item, depth + 1)

        _visit(bundle.get("content_list_v2"))
        # Also check content_list (v1)
        cl1 = bundle.get("content_list")
        if isinstance(cl1, list):
            for item in cl1:
                if isinstance(item, dict) and item.get("bbox") and item.get("text"):
                    text = str(item.get("text", "")).strip()
                    if text:
                        blocks.append({
                            "bbox": item["bbox"],
                            "text": text,
                            "type": str(item.get("type", "")),
                            "depth": 0,
                        })
        return blocks

    def _run_reference_answer_extract_via_mineru(
        self,
        *,
        answer_key_urls: List[str],
        answer_contexts: List[Dict[str, Any]],
        warnings: List[str],
    ) -> List[Dict[str, Any]]:
        """Extract reference answers via MinerU + VLM alignment.

        1. Run answer key pages through MinerU → structured text blocks with positions
        2. Group questions by their paper page index
        3. For each page, send VLM: question texts + MinerU text blocks + page image
        4. VLM aligns and extracts reference answers per question
        """
        started = perf_counter()
        if not answer_key_urls or not answer_contexts:
            return []

        # 1. Run MinerU on answer key pages
        client = self._ensure_mineru_client()
        page_data: Dict[int, Dict[str, Any]] = {}
        for page_index, url in enumerate(answer_key_urls):
            mime, image_bytes, page_image = self._decode_page_image(url)
            height, width = page_image.shape[:2]
            suffix = _image_suffix_from_mime(mime)
            bundle = client.run_bytes(
                filename=f"answer_key_page_{page_index + 1}{suffix}",
                content=image_bytes,
                suffix=suffix,
            )
            text_blocks = self._extract_mineru_text_blocks(bundle)
            combined_text = "\n".join(
                f"[{b['type']}] {b['text']}" for b in text_blocks
            ) if text_blocks else ""
            page_data[page_index] = {
                "data_url": url,
                "image": page_image,
                "width": width,
                "height": height,
                "text": combined_text,
                "blocks": text_blocks,
            }
            self._log_progress(
                "reference_answer",
                "mineru_page_done",
                page=page_index + 1,
                block_count=len(text_blocks),
                text_len=len(combined_text),
                elapsed_ms=round((perf_counter() - started) * 1000, 1),
            )

        # 2. Group contexts by answer key page (fallback to distributing evenly)
        by_page: Dict[int, List[Dict[str, Any]]] = {}
        for ctx in answer_contexts:
            page_hint = ctx.get("answer_page_hint")
            if isinstance(page_hint, int) and page_hint in page_data:
                by_page.setdefault(page_hint, []).append(ctx)
            else:
                by_page.setdefault(0, []).append(ctx)

        if not any(by_page.values()):
            by_page = {0: list(answer_contexts)}

        # 3. Build prompt and call VLM per page
        context_map = _build_answer_context_map(answer_contexts)

        def _normalize_mineru_items(raw_items: List[Any]) -> List[Dict[str, Any]]:
            normalized: List[Dict[str, Any]] = []
            if isinstance(raw_items, list):
                for item in raw_items:
                    parsed = _normalize_reference_answer_item(item, context_map)
                    if parsed is not None:
                        parsed["source"] = "uploaded"
                        normalized.append(parsed)
            return normalized

        all_answers: List[Dict[str, Any]] = []
        for page_idx in sorted(by_page.keys()):
            page = page_data.get(page_idx)
            if page is None:
                continue
            contexts = by_page[page_idx]
            mineru_text = page["text"] or "（当前页未识别到文本内容）"

            # Compact question contexts for the prompt
            compact = _compact_question_contexts(contexts, full_text_limit=1200)
            prompt_text = (
                "你正在分析一份标准答案文件。\n\n"
                "以下是该页上待提取答案的题目：\n"
                f"{json.dumps(compact, ensure_ascii=False)}\n\n"
                "以下是 MinerU 从标准答案文件该页中识别出的文本块（含位置类型）：\n"
                f"{mineru_text}\n\n"
                "请结合上面的标准答案页图片，从该页中定位每道题的答案，并提取标准答案。"
                "只返回 JSON。格式：\n"
                f"{response_contract('reference_answer_extract')}"
            )
            try:
                result = self._run_harness_stage(
                    HARNESS_STAGE_REFERENCE_ANSWER_EXTRACT,
                    prompt=prompt_text,
                    data_urls=[page["data_url"]],
                    profile=self.profile,
                )
                raw_items = result.get("reference_answers", []) if isinstance(result, dict) else []
                normalized = _normalize_mineru_items(raw_items)
                all_answers.extend(normalized)
            except Exception as exc:
                warnings.append(f"reference_answer_extract page={page_idx + 1} failed: {exc}")

        elapsed = round((perf_counter() - started) * 1000, 1)
        self._log_progress(
            "reference_answer",
            "mineru_extract_done",
            answer_count=len(all_answers),
            elapsed_ms=elapsed,
        )
        return all_answers

    def _run_reference_answer_extract(
        self,
        *,
        answer_key_urls: List[str],
        answer_contexts: List[Dict[str, Any]],
        warnings: List[str],
    ) -> List[Dict[str, Any]]:
        if not answer_key_urls:
            return []
        return self._run_reference_answer_common(
            stage_spec=HARNESS_STAGE_REFERENCE_ANSWER_EXTRACT,
            prompt=_reference_answer_extract_prompt(answer_contexts),
            data_urls=answer_key_urls,
            profile=self.profile,
            answer_contexts=answer_contexts,
            warnings=warnings,
            warning_prefix="reference_answer_extract",
            failed_event="extract_failed",
            success_event="extract_done",
            progress_count_key="page_count",
            progress_count_value=len(answer_key_urls),
            source_label="uploaded",
        )

    @staticmethod
    def _context_question_image_urls(context: Dict[str, Any], paper_urls: List[str]) -> List[str]:
        urls: List[str] = []
        raw_urls = context.get("question_image_urls")
        if isinstance(raw_urls, list):
            urls.extend(url.strip() for url in raw_urls if isinstance(url, str) and url.strip().startswith("data:image/"))

        if not urls and DemoService._context_mentions_image(context):
            page_index = context.get("paper_page_index")
            if isinstance(page_index, int) and 0 <= page_index < len(paper_urls):
                page_url = paper_urls[page_index]
                if isinstance(page_url, str) and page_url.strip():
                    urls.append(page_url.strip())

        seen: set[str] = set()
        deduped: List[str] = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                deduped.append(url)
        return deduped

    @staticmethod
    def _context_mentions_image(context: Dict[str, Any]) -> bool:
        image_refs = context.get("image_refs")
        if isinstance(image_refs, list) and any(isinstance(ref, str) and ref.strip() for ref in image_refs):
            return True
        text_parts = [
            context.get("problem_text") if isinstance(context.get("problem_text"), str) else "",
            context.get("problem_text_full") if isinstance(context.get("problem_text_full"), str) else "",
            context.get("question_anchor_text") if isinstance(context.get("question_anchor_text"), str) else "",
        ]
        return any(marker in text for text in text_parts for marker in ("![", "[image", "如图", "图中", "配图"))

    def _reference_generate_chunks(
        self,
        answer_contexts: List[Dict[str, Any]],
        paper_urls: List[str],
        chunk_size: int,
    ) -> List[Dict[str, Any]]:
        text_contexts: List[Dict[str, Any]] = []
        visual_contexts: List[Dict[str, Any]] = []
        visual_urls_by_qid: Dict[str, List[str]] = {}

        for context in answer_contexts:
            image_urls = self._context_question_image_urls(context, paper_urls)
            qid = context.get("question_id")
            if image_urls and isinstance(qid, str):
                visual_contexts.append(context)
                visual_urls_by_qid[qid] = image_urls
            else:
                text_contexts.append(context)

        chunks: List[Dict[str, Any]] = []
        for chunk in _chunk_list(text_contexts, chunk_size):
            if chunk:
                chunks.append({"mode": "text", "contexts": chunk, "data_urls": []})
        for chunk in _chunk_list(visual_contexts, chunk_size):
            if not chunk:
                continue
            data_urls: List[str] = []
            seen: set[str] = set()
            for context in chunk:
                qid = context.get("question_id")
                for url in visual_urls_by_qid.get(qid, []) if isinstance(qid, str) else []:
                    if url not in seen:
                        seen.add(url)
                        data_urls.append(url)
            chunks.append({"mode": "vision", "contexts": chunk, "data_urls": data_urls})
        return chunks

    def _run_reference_answer_generate(
        self,
        *,
        answer_contexts: List[Dict[str, Any]],
        paper_urls: Optional[List[str]] = None,
        warnings: List[str],
    ) -> List[Dict[str, Any]]:
        if not answer_contexts:
            self._last_reference_generate_stats = {
                "chunk_count": 0,
                "chunk_size": 0,
                "generated_question_count": 0,
                "skipped_question_count": 0,
            }
            return []
        configured_chunk_size = min(max(1, int(self.reference_answer_chunk_size)), max(1, int(self.question_chunk_size)))
        chunk_size = 1
        source_paper_urls = [url for url in (paper_urls or []) if isinstance(url, str) and url.strip()]
        chunks = self._reference_generate_chunks(answer_contexts, source_paper_urls, chunk_size)
        outputs: Dict[tuple[str, Optional[str]], Dict[str, Any]] = {}
        max_workers = min(max(1, self.answer_concurrency), len(chunks))
        text_chunk_count = len([chunk for chunk in chunks if chunk.get("mode") == "text"])
        vision_chunk_count = len([chunk for chunk in chunks if chunk.get("mode") == "vision"])
        self._log_progress(
            "reference_answer",
            "generate_chunk_start",
            question_count=len(answer_contexts),
            chunk_count=len(chunks),
            text_chunk_count=text_chunk_count,
            vision_chunk_count=vision_chunk_count,
            max_workers=max_workers,
        )

        def _store_reference_answers(items: List[Dict[str, Any]]) -> None:
            for item in items:
                if not isinstance(item, dict):
                    continue
                qid = item.get("question_id")
                if not isinstance(qid, str) or not qid:
                    continue
                sub_qid = item.get("sub_question_id") if isinstance(item.get("sub_question_id"), str) else None
                key = (qid, sub_qid)
                existing = outputs.get(key)
                new_conf = item.get("confidence") if isinstance(item.get("confidence"), (int, float)) else -1.0
                old_conf = existing.get("confidence") if isinstance(existing, dict) and isinstance(existing.get("confidence"), (int, float)) else -1.0
                if existing is None or new_conf >= old_conf:
                    outputs[key] = item

        def _run_generate_chunk(chunk_index: int, chunk_spec: Dict[str, Any]) -> List[Dict[str, Any]]:
            chunk = [item for item in chunk_spec.get("contexts", []) if isinstance(item, dict)]
            mode = "vision" if chunk_spec.get("mode") == "vision" else "text"
            chunk_data_urls = [
                url for url in (chunk_spec.get("data_urls") if isinstance(chunk_spec.get("data_urls"), list) else [])
                if isinstance(url, str) and url.strip()
            ]
            chunk_profile = self.profile if mode == "vision" else (self.text_profile or self.profile)
            question_ids = [item.get("question_id") for item in chunk if isinstance(item.get("question_id"), str)]
            self._log_progress(
                "reference_answer",
                "generate_chunk_llm_start",
                chunk=f"{chunk_index}/{len(chunks)}",
                mode=mode,
                question_count=len(chunk),
                question_ids=",".join(question_ids) if len(question_ids) <= 6 else ",".join(question_ids[:6]) + f"... (+{len(question_ids) - 6})",
            )
            chunk_answers = self._run_reference_answer_common(
                stage_spec=HARNESS_STAGE_REFERENCE_ANSWER_GENERATE,
                prompt=_reference_answer_generate_prompt(_compact_question_contexts(chunk, full_text_limit=900)),
                data_urls=chunk_data_urls,
                profile=chunk_profile,
                answer_contexts=chunk,
                warnings=warnings,
                warning_prefix=f"reference_answer_generate {mode} chunk={chunk_index}",
                failed_event="generate_chunk_failed",
                success_event="generate_chunk_done",
                progress_count_key="question_count",
                progress_count_value=len(chunk),
                source_label="generated",
            )
            generated_ids = {
                item.get("question_id")
                for item in chunk_answers
                if isinstance(item, dict) and isinstance(item.get("question_id"), str)
            }
            if len(chunk) <= 1 and generated_ids:
                return chunk_answers
            missing_contexts = [
                item
                for item in chunk
                if isinstance(item, dict)
                and isinstance(item.get("question_id"), str)
                and item.get("question_id") not in generated_ids
            ]
            if not missing_contexts:
                return chunk_answers
            self._log_progress(
                "reference_answer",
                "generate_chunk_retry",
                chunk=f"{chunk_index}/{len(chunks)}",
                mode=mode,
                missing_count=len(missing_contexts),
                missing_qids=",".join([item.get("question_id") for item in missing_contexts if isinstance(item.get("question_id"), str)]),
            )
            retry_answers = list(chunk_answers)
            for single_index, single_context in enumerate(missing_contexts, start=1):
                single_qid = single_context.get("question_id")
                single_data_urls = (
                    self._context_question_image_urls(single_context, source_paper_urls)
                    if mode == "vision"
                    else []
                )
                single_answers = self._run_reference_answer_common(
                    stage_spec=HARNESS_STAGE_REFERENCE_ANSWER_GENERATE,
                    prompt=_reference_answer_generate_prompt(_compact_question_contexts([single_context], full_text_limit=1200)),
                    data_urls=single_data_urls,
                    profile=chunk_profile,
                    answer_contexts=[single_context],
                    warnings=warnings,
                    warning_prefix=f"reference_answer_generate {mode} chunk={chunk_index} retry={single_index} target={single_qid}",
                    failed_event="generate_chunk_failed",
                    success_event="generate_chunk_done",
                    progress_count_key="question_count",
                    progress_count_value=1,
                    source_label="generated",
                )
                retry_answers.extend(single_answers)
            return retry_answers

        total_question_count = len(answer_contexts)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            tasks: List[tuple[int, int, float, Any]] = []
            for chunk_index, chunk_spec in enumerate(chunks, start=1):
                chunk = [item for item in chunk_spec.get("contexts", []) if isinstance(item, dict)]
                tasks.append(
                    (
                        chunk_index,
                        len(chunk),
                        perf_counter(),
                        executor.submit(_run_generate_chunk, chunk_index, chunk_spec),
                    )
                )
            accumulated = 0
            for chunk_index, chunk_size, started, future in tasks:
                try:
                    chunk_answers = future.result()
                except Exception as exc:
                    warnings.append(f"reference_answer_generate chunk={chunk_index} failed: {exc}")
                    self._log_progress(
                        "reference_answer",
                        "generate_chunk_failed",
                        chunk=chunk_index,
                        question_count=chunk_size,
                        elapsed_ms=round((perf_counter() - started) * 1000, 1),
                    )
                    continue
                _store_reference_answers(chunk_answers)
                accumulated += len({item.get("question_id") for item in chunk_answers if isinstance(item, dict) and isinstance(item.get("question_id"), str)})
                chunk_elapsed_ms = round((perf_counter() - started) * 1000, 1)
                self._log_progress(
                    "reference_answer",
                    "generate_chunk_completed",
                    chunk=f"{chunk_index}/{len(chunks)}",
                    chunk_question_count=chunk_size,
                    completed=f"{accumulated}/{total_question_count}",
                    elapsed_ms=chunk_elapsed_ms,
                )
        generated = list(outputs.values())
        self._last_reference_generate_stats = {
            "chunk_count": len(chunks),
            "chunk_size": chunk_size,
            "configured_chunk_size": configured_chunk_size,
            "text_chunk_count": text_chunk_count,
            "vision_chunk_count": vision_chunk_count,
            "generated_question_count": len({item.get("question_id") for item in generated if isinstance(item.get("question_id"), str)}),
            "skipped_question_count": max(0, len(answer_contexts) - len({item.get("question_id") for item in generated if isinstance(item.get("question_id"), str)})),
        }
        self._log_progress(
            "reference_answer",
            "generate_done",
            question_count=len(answer_contexts),
            answer_count=len(generated),
            chunk_count=len(chunks),
        )
        return generated

    def _prepare_reference_answers(
        self,
        *,
        answer_key_urls: List[str],
        answer_contexts: List[Dict[str, Any]],
        paper_urls: Optional[List[str]] = None,
        preferred_source: str,
        warnings: List[str],
    ) -> tuple[List[Dict[str, Any]], str]:
        self._last_reference_generate_stats = {
            "chunk_count": 0,
            "chunk_size": 0,
            "generated_question_count": 0,
            "skipped_question_count": 0,
        }
        source = preferred_source if preferred_source in {"uploaded", "generated"} else "generated"
        if source == "uploaded":
            # Use MinerU + VLM for answer key extraction
            extracted = self._run_reference_answer_extract_via_mineru(
                answer_key_urls=answer_key_urls,
                answer_contexts=answer_contexts,
                warnings=warnings,
            )
            if extracted:
                return extracted, "uploaded"
            warnings.append("reference answers minerv extract produced no results, falling back to generation")
            generated = self._run_reference_answer_generate(
                answer_contexts=answer_contexts,
                paper_urls=paper_urls,
                warnings=warnings,
            )
            if generated:
                return generated, "generated"
            return [], "none"
        generated = self._run_reference_answer_generate(
            answer_contexts=answer_contexts,
            paper_urls=paper_urls,
            warnings=warnings,
        )
        if generated:
            return generated, "generated"
        return [], "none"

    def _run_answer_key_correctness(
        self,
        *,
        answer_contexts: List[Dict[str, Any]],
        structured_questions_full: List[Dict[str, Any]],
        reference_answers: List[Dict[str, Any]],
        answer_key_source: str,
        teacher_review_by_id: Dict[str, Dict[str, Any]],
        warnings: List[str],
    ) -> List[Dict[str, Any]]:
        from demo.stages.correctness import run_answer_key_correctness_stage

        result = run_answer_key_correctness_stage(
            answer_contexts=answer_contexts,
            structured_questions_full=structured_questions_full,
            reference_answers=reference_answers,
            answer_key_source=answer_key_source,
            teacher_review_by_id=teacher_review_by_id,
            text_profile=self.text_profile,
            question_chunk_size=self.question_chunk_size,
            answer_concurrency=self.answer_concurrency,
            harness_stage_correctness=HARNESS_STAGE_ANSWER_KEY_CORRECTNESS,
            run_harness_stage=self._run_harness_stage,
            log_progress=self._log_progress,
            correctness_prompt_fn=_answer_key_correctness_prompt,
            build_items_fn=_build_answer_key_correctness_items,
            build_context_map_fn=_build_answer_context_map,
            normalize_item_fn=_normalize_answer_key_correctness_item,
            warnings_out=warnings,
        )
        return result.output.get("items", [])

    def _run_blind_diagnosis(
        self,
        questions: List[Dict[str, Any]],
        answers: List[Dict[str, Any]],
        warnings: List[str],
    ) -> tuple[Dict[str, Dict[str, Any]], int]:
        from demo.stages.blind_diagnosis import run_blind_diagnosis_stage

        result = run_blind_diagnosis_stage(
            questions=questions,
            answers=answers,
            text_profile=self.text_profile,
            answer_concurrency=self.answer_concurrency,
            question_chunk_size=self.question_chunk_size,
            blind_diagnosis_max_items=self.blind_diagnosis_max_items,
            harness_stage_blind_diagnosis=HARNESS_STAGE_BLIND_DIAGNOSIS,
            run_harness_stage=self._run_harness_stage,
            log_progress=self._log_progress,
            blind_diagnosis_prompt_fn=_blind_diagnosis_prompt,
            should_run_fn=_should_run_blind_diagnosis_for_answer,
            build_item_fn=_build_blind_diagnosis_item,
            diagnosis_priority_fn=_diagnosis_priority_score,
            normalize_payload_fn=_normalize_blind_diagnosis_payload,
            warnings_out=warnings,
        )
        self._last_blind_diagnosis_target_count = result.output.get("target_count", 0)
        self._last_blind_diagnosis_skipped_count = result.output.get("skipped_count", 0)
        return result.output.get("diagnosis_by_id", {}), result.output.get("diagnosis_count", 0)

    def _run_answer_repair_round_parallel(
        self,
        *,
        repair_targets: List[str],
        questions: List[Dict[str, Any]],
        answer_urls: List[str],
        raw_answers: List[Dict[str, Any]],
        answer_context_map: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        def _resolve_repair_max_tokens(target_count: int) -> int:
            base_limit = self.max_tokens if isinstance(self.max_tokens, int) and self.max_tokens > 0 else 600
            scaled_limit = 512 + max(1, int(target_count)) * 320
            return min(3200, max(base_limit, scaled_limit))

        if not repair_targets:
            return {
                "raw_answers": [],
                "unmatched_traces": [],
                "warnings": [],
                "pass_chunks": 0,
            }
        task_specs: List[Dict[str, Any]] = []
        for qid_chunk in _chunk_list(repair_targets, self.score_chunk_size):
            selected_questions = _pick_questions_by_ids(questions, qid_chunk)
            if not selected_questions:
                continue
            selected_contexts = _build_answer_contexts(selected_questions)
            candidate_summaries = _build_candidate_summaries(
                raw_answers,
                [ctx.get("question_id") for ctx in selected_contexts if isinstance(ctx.get("question_id"), str)],
            )
            by_page: Dict[int, List[Dict[str, Any]]] = {}
            for ctx in selected_contexts:
                page_hint = ctx.get("answer_page_hint") if isinstance(ctx.get("answer_page_hint"), int) else 0
                by_page.setdefault(page_hint, []).append(ctx)
            for page_index, page_contexts in sorted(by_page.items()):
                target_ids = [ctx.get("question_id") for ctx in page_contexts if isinstance(ctx.get("question_id"), str)]
                page_summaries = [item for item in candidate_summaries if item.get("question_id") in target_ids]
                task_specs.append(
                    {
                        "page_index": page_index,
                        "page_contexts": page_contexts,
                        "page_summaries": page_summaries,
                        "target_ids": target_ids,
                    }
                )
        if not task_specs:
            return {
                "raw_answers": [],
                "unmatched_traces": [],
                "warnings": [],
                "pass_chunks": 0,
            }

        new_raw_answers: List[Dict[str, Any]] = []
        unmatched_traces: List[Dict[str, Any]] = []
        round_warnings: List[str] = []
        max_workers = min(max(1, self.answer_concurrency), len(task_specs))
        self._log_progress(
            "answer_trace",
            "repair_round_start",
            task_count=len(task_specs),
            target_count=len(repair_targets),
            max_workers=max_workers,
        )
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures: List[tuple[Dict[str, Any], float, Any]] = []
            for spec in task_specs:
                page_index = spec["page_index"]
                data_urls = [answer_urls[page_index]] if 0 <= page_index < len(answer_urls) else answer_urls[:1]
                target_ids = spec["target_ids"] if isinstance(spec.get("target_ids"), list) else []
                futures.append(
                    (
                        spec,
                        perf_counter(),
                        executor.submit(
                            self._call_json_with_profile,
                            self.profile,
                            prompt=_score_repair_prompt(
                                spec["page_contexts"],
                                spec["page_summaries"],
                                spec["target_ids"],
                            ),
                            data_urls=data_urls,
                            expected_list_key=expected_list_key("score_repair"),
                            max_tokens=_resolve_repair_max_tokens(len(target_ids)),
                        ),
                    )
                )

            def _append_repair_answers(page_idx: int, repair_answers: Any) -> None:
                if not isinstance(repair_answers, list):
                    return
                for item in repair_answers:
                    if not isinstance(item, dict):
                        continue
                    normalized = _normalize_answer_item(
                        item,
                        answer_context_map,
                        source_stage="repair",
                        page_index=page_idx,
                    )
                    if normalized is not None:
                        new_raw_answers.append(normalized)
                    else:
                        unmatched_traces.append(
                            {
                                "question_id": item.get("question_id"),
                                "sub_question_id": item.get("sub_question_id"),
                                "reason": "question_id_not_in_step1_or_invalid",
                            }
                        )

            def _filter_contexts_by_target_ids(
                contexts: List[Dict[str, Any]],
                summaries: List[Dict[str, Any]],
                target_ids: List[str],
            ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
                canonical_targets = {
                    _canonical_question_id(item) or item
                    for item in target_ids
                    if isinstance(item, str) and item.strip()
                }
                selected_contexts: List[Dict[str, Any]] = []
                selected_summaries: List[Dict[str, Any]] = []
                for item in contexts:
                    qid = item.get("question_id")
                    if not isinstance(qid, str):
                        continue
                    canonical_qid = _canonical_question_id(qid) or qid
                    if canonical_qid in canonical_targets:
                        selected_contexts.append(item)
                for item in summaries:
                    qid = item.get("question_id")
                    if not isinstance(qid, str):
                        continue
                    canonical_qid = _canonical_question_id(qid) or qid
                    if canonical_qid in canonical_targets:
                        selected_summaries.append(item)
                return selected_contexts, selected_summaries

            for spec, task_started, future in futures:
                page_index = spec["page_index"]
                target_ids = spec["target_ids"]
                try:
                    answers_data = future.result()
                except Exception as exc:
                    round_warnings.append(f"answer_repair failed (targets={target_ids}): {exc}")
                    self._log_progress(
                        "answer_trace",
                        "repair_task_failed",
                        page=page_index + 1,
                        target_count=len(target_ids),
                        elapsed_ms=round((perf_counter() - task_started) * 1000, 1),
                    )
                    if _is_llm_json_payload_error(exc) and len(target_ids) > 1:
                        self._log_progress(
                            "answer_trace",
                            "repair_task_retry_single_target_start",
                            page=page_index + 1,
                            target_count=len(target_ids),
                        )
                        for qid in target_ids:
                            retry_contexts, retry_summaries = _filter_contexts_by_target_ids(
                                spec["page_contexts"],
                                spec["page_summaries"],
                                [qid],
                            )
                            if not retry_contexts:
                                continue
                            retry_started = perf_counter()
                            try:
                                retry_data = self._call_json_with_profile(
                                    self.profile,
                                    prompt=_score_repair_prompt(
                                        retry_contexts,
                                        retry_summaries,
                                        [qid],
                                    ),
                                    data_urls=[answer_urls[page_index]] if 0 <= page_index < len(answer_urls) else answer_urls[:1],
                                    expected_list_key=expected_list_key("score_repair"),
                                    max_tokens=_resolve_repair_max_tokens(1),
                                )
                            except Exception as retry_exc:
                                round_warnings.append(f"answer_repair retry failed (target={qid}): {retry_exc}")
                                self._log_progress(
                                    "answer_trace",
                                    "repair_task_retry_single_target_failed",
                                    page=page_index + 1,
                                    target=qid,
                                    elapsed_ms=round((perf_counter() - retry_started) * 1000, 1),
                                )
                                continue
                            retry_answers = retry_data.get("answers", [])
                            self._log_progress(
                                "answer_trace",
                                "repair_task_retry_single_target_done",
                                page=page_index + 1,
                                target=qid,
                                answer_count=len(retry_answers) if isinstance(retry_answers, list) else 0,
                                elapsed_ms=round((perf_counter() - retry_started) * 1000, 1),
                            )
                            _append_repair_answers(page_index, retry_answers)
                    continue
                repair_answers = answers_data.get("answers", [])
                self._log_progress(
                    "answer_trace",
                    "repair_task_done",
                    page=page_index + 1,
                    target_count=len(target_ids),
                    answer_count=len(repair_answers) if isinstance(repair_answers, list) else 0,
                    elapsed_ms=round((perf_counter() - task_started) * 1000, 1),
                )
                _append_repair_answers(page_index, repair_answers)
        return {
            "raw_answers": new_raw_answers,
            "unmatched_traces": unmatched_traces,
            "warnings": round_warnings,
            "pass_chunks": len(task_specs),
        }

    def _build_raw_text_fallback_answers(
        self,
        *,
        page_raw_items: List[Dict[str, Any]],
        answer_context_map: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        fallback_answers: List[Dict[str, Any]] = []
        for item in page_raw_items:
            if not isinstance(item, dict):
                continue
            context_question_ids = item.get("context_question_ids") if isinstance(item.get("context_question_ids"), list) else []
            unique_qids = [qid for qid in context_question_ids if isinstance(qid, str) and qid in answer_context_map]
            unique_qids = list(dict.fromkeys(unique_qids))
            if len(unique_qids) != 1:
                continue
            qid = unique_qids[0]
            raw_text = _strip_raw_text_source_header(item.get("raw_text"))
            if not _is_useful_raw_text_fallback(raw_text):
                continue
            inferred_steps = _infer_steps_from_answer_text(raw_text, raw_text)
            normalized = _normalize_answer_item(
                {
                    "question_id": qid,
                    "status": "answered" if inferred_steps else "unclear",
                    "student_answer_text": raw_text,
                    "answer_text": raw_text,
                    "steps": inferred_steps,
                    "confidence": 0.45,
                    "trace": {
                        "confidence": 0.45,
                        "notes": "inferred from raw VLM text fallback",
                    },
                },
                answer_context_map,
                source_stage="raw_text_fallback",
                page_index=item.get("page_index") if isinstance(item.get("page_index"), int) else None,
            )
            if normalized is not None:
                fallback_answers.append(normalized)
        return fallback_answers

    def _ensure_new_points(self, questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        from demo.stages.new_knowledge_points import run_new_knowledge_points_stage

        result = run_new_knowledge_points_stage(
            questions=questions,
            known_map=self._known_map(),
            all_nodes=self.nodes,
            profile=self.profile,
            mock_mode=self.mock_mode,
            call_json_with_profile=self._call_json_with_profile,
            log_progress=self._log_progress,
        )
        if result.output.get("new_nodes"):
            self._save_graph()
            self._log_progress(
                "new_knowledge_points",
                "graph_saved",
                added_count=len(result.output["new_nodes"]),
            )
        return result.output.get("new_nodes", [])

    def _normalize_payload_files(
        self,
        payload: Dict[str, Any],
        key: str,
        *,
        required: bool,
    ) -> List[Dict[str, str]]:
        input_mode = str(payload.get("input_mode") or "?")
        raw_files = payload.get(key)
        if raw_files is None:
            if required:
                raise ValueError(f"{key} is required (input_mode={input_mode})")
            return []
        if not isinstance(raw_files, list):
            raise ValueError(f"{key} must be a list (input_mode={input_mode})")
        if required and not raw_files:
            raise ValueError(f"{key} is required (input_mode={input_mode})")
        normalized: List[Dict[str, str]] = []
        for index, item in enumerate(raw_files):
            if not isinstance(item, dict):
                raise ValueError(f"{key}[{index}] must be object")
            data_url = item.get("data_url")
            if not isinstance(data_url, str) or not data_url.strip():
                raise ValueError(f"{key}[{index}].data_url is required")
            name = item.get("name")
            normalized.append(
                {
                    "name": name.strip() if isinstance(name, str) and name.strip() else f"{key}_{index + 1}",
                    "data_url": data_url.strip(),
                }
            )
        return normalized

    def _expand_payload_files_to_image_urls(
        self,
        files: List[Dict[str, str]],
        *,
        field_name: str,
    ) -> List[str]:
        output: List[str] = []
        for index, item in enumerate(files):
            data_url = item.get("data_url")
            if not isinstance(data_url, str):
                continue
            mime, binary = _decode_data_url_payload(data_url)
            if mime.startswith("image/"):
                output.append(data_url)
                continue
            if mime == "application/pdf":
                pages = _pdf_bytes_to_image_data_urls(
                    binary,
                    dpi=self.pdf_render_dpi,
                    max_pages=self.pdf_max_pages,
                )
                if not pages:
                    raise ValueError(f"{field_name}[{index}] pdf contains no pages")
                output.extend(pages)
                continue
            raise ValueError(f"{field_name}[{index}] unsupported mime: {mime}")
        if not output:
            if files and not any(isinstance(f, dict) and isinstance(f.get("data_url"), str) for f in files):
                raise ValueError(f"{field_name} contains no valid image/pdf data_url")
            # Empty file list is valid (e.g. paper extraction without answer sheets)
            return []
        return output

    def _validate_input(
        self, payload: Dict[str, Any]
    ) -> tuple[str, str, List[str], List[str], List[str], str]:
        student_id = str(payload.get("student_id") or "").strip()
        input_mode = str(payload.get("input_mode") or "").strip()
        if input_mode not in {"paper_answer_with_key", "paper_answer_auto_key", "paper_same_page", "pre_split_questions"}:
            raise ValueError(
                "input_mode must be paper_answer_with_key | paper_answer_auto_key | paper_same_page | pre_split_questions"
            )
        if not student_id:
            raise ValueError("student_id is required")

        paper_files = self._normalize_payload_files(
            payload,
            "paper_files",
            required=input_mode in {"paper_answer_with_key", "paper_answer_auto_key"},
        )
        _is_paper_extraction_run = bool(payload.get("_paper_project_id"))
        answer_sheet_files = self._normalize_payload_files(
            payload,
            "answer_sheet_files",
            required=(input_mode in {"paper_answer_with_key", "paper_answer_auto_key", "pre_split_questions"})
                     and not _is_paper_extraction_run,
        )
        combined_files = self._normalize_payload_files(
            payload,
            "combined_files",
            required=input_mode == "paper_same_page",
        )
        answer_key_files = self._normalize_payload_files(
            payload,
            "answer_key_files",
            required=input_mode == "paper_answer_with_key",
        )

        if input_mode == "paper_same_page" and (paper_files or answer_sheet_files):
            raise ValueError("paper_same_page mode must use only combined_files (+ optional answer_key_files)")
        if input_mode in {"paper_answer_with_key", "paper_answer_auto_key"} and combined_files:
            raise ValueError("combined_files is only allowed in paper_same_page mode")
        if input_mode == "paper_answer_auto_key" and answer_key_files:
            raise ValueError("paper_answer_auto_key mode does not accept answer_key_files")
        if input_mode == "pre_split_questions":
            raw_pre_split = payload.get("pre_split_questions")
            if not isinstance(raw_pre_split, list) or not raw_pre_split:
                raise ValueError("pre_split_questions mode requires non-empty pre_split_questions")
            if paper_files or combined_files:
                raise ValueError("pre_split_questions mode only accepts answer_sheet_files (+ optional answer_key_files)")

        if input_mode == "paper_same_page":
            combined_urls = self._expand_payload_files_to_image_urls(combined_files, field_name="combined_files")
            answer_key_urls = (
                self._expand_payload_files_to_image_urls(answer_key_files, field_name="answer_key_files")
                if answer_key_files
                else []
            )
            answer_key_source = "uploaded" if answer_key_urls else "generated"
            return student_id, input_mode, combined_urls, list(combined_urls), answer_key_urls, answer_key_source

        if input_mode == "pre_split_questions":
            answer_urls = self._expand_payload_files_to_image_urls(answer_sheet_files, field_name="answer_sheet_files")
            answer_key_urls = (
                self._expand_payload_files_to_image_urls(answer_key_files, field_name="answer_key_files")
                if answer_key_files
                else []
            )
            answer_key_source = "uploaded" if answer_key_urls else "generated"
            return student_id, input_mode, [], answer_urls, answer_key_urls, answer_key_source

        paper_urls = self._expand_payload_files_to_image_urls(paper_files, field_name="paper_files")
        answer_urls = self._expand_payload_files_to_image_urls(answer_sheet_files, field_name="answer_sheet_files")
        if input_mode == "paper_answer_with_key":
            answer_key_urls = self._expand_payload_files_to_image_urls(answer_key_files, field_name="answer_key_files")
            answer_key_source = "uploaded"
        else:
            answer_key_urls = []
            answer_key_source = "generated"
        return student_id, input_mode, paper_urls, answer_urls, answer_key_urls, answer_key_source

    def _normalize_pre_split_questions_payload(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        raw_items = payload.get("pre_split_questions")
        if not isinstance(raw_items, list) or not raw_items:
            raise ValueError("pre_split_questions is required and must be a non-empty list")
        question_by_id: Dict[str, Dict[str, Any]] = {}
        for index, item in enumerate(raw_items):
            if not isinstance(item, dict):
                raise ValueError(f"pre_split_questions[{index}] must be object")
            normalized_question = _normalize_question_item(item)
            if normalized_question is None:
                raise ValueError(f"pre_split_questions[{index}] has invalid question_id")
            qid = normalized_question["question_id"]
            existing = question_by_id.get(qid)
            question_by_id[qid] = (
                normalized_question if existing is None else _merge_question_items(existing, normalized_question)
            )
        questions = sorted(question_by_id.values(), key=_question_sort_key)
        if not questions:
            raise ValueError("pre_split_questions contains no valid question")
        return _attach_question_metadata(questions)

    def _score_ratio(self, answer: Dict[str, Any]) -> Optional[float]:
        score = answer.get("score")
        max_score = answer.get("max_score")
        if isinstance(score, (int, float)) and isinstance(max_score, (int, float)) and max_score > 0:
            ratio = float(score) / float(max_score)
            return max(0.0, min(1.0, ratio))
        is_correct = answer.get("is_correct")
        if isinstance(is_correct, bool):
            return 1.0 if is_correct else 0.0
        return None

    def _build_profile_fallback(
        self,
        student_id: str,
        questions: List[Dict[str, Any]],
        answers: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        question_by_id: Dict[str, Dict[str, Any]] = {}
        for q in questions:
            qid = q.get("question_id")
            if isinstance(qid, str) and qid:
                question_by_id[qid] = q

        answer_by_id: Dict[str, Dict[str, Any]] = {}
        for a in answers:
            qid = a.get("question_id")
            if isinstance(qid, str) and qid:
                answer_by_id[qid] = a

        error_profile = {"concept": 0, "calculation": 0, "reading": 0, "strategy": 0, "unknown": 0}
        skill_ratios: Dict[str, List[float]] = {}
        skill_evidence: Dict[str, List[str]] = {}
        all_ratios: List[float] = []

        for qid, q in question_by_id.items():
            tags = q.get("skill_tags")
            skill_tags = [x for x in tags if isinstance(x, str)] if isinstance(tags, list) else []
            ans = answer_by_id.get(qid, {})
            ratio = self._score_ratio(ans) if isinstance(ans, dict) else None
            if ratio is None:
                ratio = 0.5
                error_profile["unknown"] += 1
            all_ratios.append(ratio)

            trace = ans.get("trace") if isinstance(ans, dict) and isinstance(ans.get("trace"), dict) else {}
            readability = trace.get("readability") if isinstance(trace.get("readability"), (int, float)) else None
            steps = ans.get("steps") if isinstance(ans, dict) and isinstance(ans.get("steps"), list) else []
            is_correct = ans.get("is_correct") if isinstance(ans, dict) else None

            if ratio < 0.35:
                if isinstance(readability, (int, float)) and readability < 0.6:
                    error_profile["reading"] += 1
                elif isinstance(steps, list) and len(steps) >= 2:
                    error_profile["calculation"] += 1
                elif isinstance(is_correct, bool) and not is_correct:
                    error_profile["concept"] += 1
                else:
                    error_profile["strategy"] += 1

            if not skill_tags:
                error_profile["unknown"] += 1
                continue

            for skill_id in skill_tags:
                skill_ratios.setdefault(skill_id, []).append(ratio)
                skill_evidence.setdefault(skill_id, []).append(qid)

        mastery: List[Dict[str, Any]] = []
        for skill_id, ratios in skill_ratios.items():
            value = round(sum(ratios) / max(len(ratios), 1), 2)
            if value >= 0.75:
                reason = "high score rate on related questions"
            elif value >= 0.5:
                reason = "medium score rate on related questions"
            else:
                reason = "low score rate on related questions"
            mastery.append({"skill_id": skill_id, "value": value, "reason": reason})
        mastery.sort(key=lambda x: x["value"])

        weaknesses: List[Dict[str, Any]] = []
        for item in mastery:
            if item["value"] >= 0.6:
                continue
            sid = item["skill_id"]
            evidence = skill_evidence.get(sid, [])[:3]
            analysis_reason = ""
            analysis_evidence = ""
            analysis_suggestion = ""
            for qid in evidence:
                answer_item = answer_by_id.get(qid, {})
                error_analysis = (
                    answer_item.get("error_analysis")
                    if isinstance(answer_item, dict) and isinstance(answer_item.get("error_analysis"), dict)
                    else {}
                )
                if isinstance(error_analysis.get("reason"), str) and error_analysis.get("reason").strip():
                    analysis_reason = error_analysis.get("reason").strip()
                if isinstance(error_analysis.get("evidence"), str) and error_analysis.get("evidence").strip():
                    analysis_evidence = error_analysis.get("evidence").strip()
                if isinstance(error_analysis.get("suggestion"), str) and error_analysis.get("suggestion").strip():
                    analysis_suggestion = error_analysis.get("suggestion").strip()
                if analysis_reason or analysis_evidence or analysis_suggestion:
                    break
            weaknesses.append(
                {
                    "skill_id": sid,
                    "evidence": evidence,
                    "priority": "high" if item["value"] < 0.4 else "medium",
                    "symptom": analysis_reason or "low score rate and unstable answers on this skill",
                    "cause": "concept and key-step understanding are not stable enough",
                    "improvement_steps": [
                        "review the wrong answers and identify where points were lost",
                        "practice 2-3 basic questions for this skill",
                        "practice 1-2 variants and review the reasoning",
                    ],
                    "practice_plan": "3 days, 15-20 minutes per day",
                    "success_criteria": "accuracy and stability improve together",
                    "suggestion": analysis_suggestion or "do basics first, then 1-2 variants with error review",
                }
            )

        avg_ratio = round(sum(all_ratios) / max(len(all_ratios), 1), 2) if all_ratios else 0.0
        analysis_reasons = []
        for answer in answers:
            error_analysis = answer.get("error_analysis") if isinstance(answer.get("error_analysis"), dict) else {}
            reason = error_analysis.get("reason") if isinstance(error_analysis.get("reason"), str) else ""
            if reason.strip():
                analysis_reasons.append(reason.strip())
        if not mastery:
            summary = "insufficient signal for detailed profile; returned baseline summary"
        elif analysis_reasons:
            summary = "；".join(analysis_reasons[:3])
        elif avg_ratio >= 0.75:
            summary = "overall mastery is good; keep current practice and do light reinforcement"
        elif avg_ratio >= 0.5:
            summary = "overall mastery is moderate; reinforce lower-skill points first"
        else:
            summary = "overall mastery is weak; rebuild fundamentals and core methods first"

        return {
            "student_id": student_id,
            "mastery": mastery,
            "error_profile": error_profile,
            "literacy": (
                _build_rule_based_literacy_profile(questions, answers, self.literacy_mapping)
                or _build_profile_literacy_fallback(
                    questions=questions,
                    answers=answers,
                    avg_ratio=avg_ratio,
                )
            ),
            "weaknesses": weaknesses,
            "summary": summary,
        }

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        run_started_at = _now_iso()
        answer_run_token = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        stage_logs: List[Dict[str, Any]] = []
        request_student_id = str(payload.get("student_id") or "").strip() or "unknown"
        request_input_mode = str(payload.get("input_mode") or "").strip()
        model_selection = self._apply_request_model_selection(payload)

        def record_stage(stage: str, status: str, **extra: Any) -> None:
            entry: Dict[str, Any] = {"stage": stage, "status": status}
            entry.update(extra)
            stage_logs.append(entry)
            extra_parts = []
            for key, value in extra.items():
                if value is None:
                    continue
                extra_parts.append(f"{key}={value}")
            suffix = f" | {' '.join(extra_parts)}" if extra_parts else ""
            _terminal_log(
                f"[demo.run] student_id={request_student_id} input_mode={request_input_mode} "
                f"stage={stage} status={status}{suffix}"
            )

        debug_run_dir: Optional[Path] = None
        if self.debug_save_all_stages:
            try:
                student_token = self._safe_path_token(request_student_id) or "unknown"
                run_token_safe = self._safe_path_token(answer_run_token) or answer_run_token
                debug_run_dir = self.debug_stage_output_dir / student_token / run_token_safe
                debug_run_dir.mkdir(parents=True, exist_ok=True)
                self._debug_active_run_dir = debug_run_dir
            except Exception as exc:
                _terminal_log(f"[demo.run] stage_debug dir setup failed: {exc}")
                self._debug_active_run_dir = None

        validate_start = perf_counter()
        student_id, input_mode, paper_urls, answer_urls, answer_key_urls, answer_key_source = self._validate_input(payload)
        pre_split_questions: List[Dict[str, Any]] = []
        if input_mode == "pre_split_questions":
            pre_split_questions = self._normalize_pre_split_questions_payload(payload)
        selected_answer_blocks: List[Dict[str, Any]] = []
        raw_blocks = payload.get("selected_answer_blocks")
        if raw_blocks is not None and isinstance(raw_blocks, list) and len(raw_blocks) > 0:
            selected_answer_blocks = self._normalize_accepted_blocks(payload, key="selected_answer_blocks")
            if not selected_answer_blocks:
                raise ValueError("请至少选择一个题块后再识别")
        selected_block_source_counts = _count_blocks_by_source(selected_answer_blocks)
        record_stage(
            "validate_input",
            "ok",
            input_mode=input_mode,
            vision_profile=model_selection.get("vision_profile"),
            text_profile=model_selection.get("text_profile"),
            paper_page_count=len(paper_urls),
            answer_page_count=len(answer_urls),
            answer_key_page_count=len(answer_key_urls),
            answer_key_source=answer_key_source,
            pre_split_question_count=len(pre_split_questions),
            selected_answer_block_count=len(selected_answer_blocks),
            elapsed_ms=round((perf_counter() - validate_start) * 1000, 1),
        )

        warnings: List[str] = []
        skill_alias_map = self._build_skill_alias_map()

        # Inject pre-extracted data from paper project (skip extraction/reference gen)
        pre_injected_questions = payload.get("_paper_questions") or payload.get("_pre_injected_questions")
        pre_injected_reference_answers = payload.get("_pre_injected_reference_answers")
        if pre_injected_questions and isinstance(pre_injected_questions, list) and pre_injected_questions:
            # Use full question dicts (with skill_tags) so knowledge_tagging skips them
            if not pre_split_questions:
                normalized = list(pre_injected_questions)  # keep full dicts including skill_tags
                pre_split_questions = normalized
            pre_injected_questions_flag = True
        else:
            pre_injected_questions_flag = False

        if self.mock_mode:
            question_stage_start = perf_counter()
            if pre_split_questions:
                questions = list(pre_split_questions)
                mock_answer_meta: Dict[str, Dict[str, Any]] = {}
            else:
                requested_count = payload.get("mock_question_count", payload.get("question_count", 27))
                try:
                    mock_question_count = int(requested_count)
                except (TypeError, ValueError):
                    mock_question_count = 27
                mock_question_count = max(8, min(40, mock_question_count))
                skill_candidates = [sid for sid in skill_alias_map.keys() if isinstance(sid, str) and sid.strip()]
                questions, mock_answer_meta = _build_mock_exam_questions(skill_candidates, mock_question_count)
            record_stage(
                "question_analysis",
                "ok",
                mode="mock_pre_split" if pre_split_questions else "mock",
                question_count=len(questions),
                elapsed_ms=round((perf_counter() - question_stage_start) * 1000, 1),
            )

            new_points_stage_start = perf_counter()
            new_nodes = self._ensure_new_points(questions)
            skill_alias_map = self._build_skill_alias_map()
            record_stage(
                "new_knowledge_points",
                "ok",
                mode="mock",
                added_count=len(new_nodes),
                elapsed_ms=round((perf_counter() - new_points_stage_start) * 1000, 1),
            )

            answer_stage_start = perf_counter()
            answers: List[Dict[str, Any]] = []
            reference_answers: List[Dict[str, Any]] = []
            for idx, question in enumerate(questions):
                qid = question.get("question_id") if isinstance(question.get("question_id"), str) else f"Q{idx + 1}"
                qtype = question.get("question_type") if isinstance(question.get("question_type"), str) else "solution"
                skill_tags = question.get("skill_tags") if isinstance(question.get("skill_tags"), list) else []
                meta = mock_answer_meta.get(qid, {})
                ref_final_answer = (
                    meta.get("reference_final_answer")
                    if isinstance(meta.get("reference_final_answer"), str)
                    else "标准答案（模拟）"
                )
                ref_steps = (
                    meta.get("reference_steps")
                    if isinstance(meta.get("reference_steps"), list)
                    else ["关键步骤1", "关键步骤2", "关键步骤3"]
                )
                if not ref_steps:
                    ref_steps = ["关键步骤1", "关键步骤2", "关键步骤3"]
                if qtype == "choice":
                    max_score = 20
                elif qtype == "fill":
                    max_score = 24
                else:
                    max_score = 28

                band = idx % 7
                if band in {0, 1}:
                    ratio = 1.0
                elif band in {2, 3}:
                    ratio = 0.75
                elif band in {4, 5}:
                    ratio = 0.55
                else:
                    ratio = 0.3
                score = int(round(max_score * ratio))
                if score > max_score:
                    score = max_score
                if score < 0:
                    score = 0

                is_correct = True if ratio >= 0.95 else (False if ratio <= 0.4 else None)
                if ratio >= 0.95:
                    error_type = "unknown"
                    reason = "作答正确，关键步骤完整"
                    suggestion = "保持稳定，继续巩固同类题"
                elif ratio >= 0.7:
                    error_type = "strategy"
                    reason = "主要思路正确，但步骤组织不够完整导致过程分损失"
                    suggestion = "先列关键关系，再按步骤作答"
                elif ratio >= 0.45:
                    error_type = "calculation"
                    reason = "计算/化简细节有偏差，导致结果不完整"
                    suggestion = "分步计算并在关键符号处复核"
                else:
                    error_type = "concept"
                    reason = "核心概念理解不稳，模型建立出现偏差"
                    suggestion = "先回顾定义与基本模型，再做2-3道基础题"
                if idx % 11 == 10 and ratio < 0.7:
                    error_type = "reading"
                    reason = "审题时遗漏约束条件，导致答案覆盖不全"
                    suggestion = "圈画条件关键词，建立检查清单"

                if qtype == "choice":
                    correct_option = meta.get("correct_option") if isinstance(meta.get("correct_option"), str) else "A"
                    wrong_option = meta.get("wrong_option") if isinstance(meta.get("wrong_option"), str) else "C"
                    student_answer_text = correct_option if ratio >= 0.7 else wrong_option
                    answer_text = student_answer_text
                    steps = []
                    selected_option = student_answer_text
                    filled_value = None
                elif qtype == "fill":
                    wrong_final_answer = (
                        meta.get("wrong_final_answer")
                        if isinstance(meta.get("wrong_final_answer"), str)
                        else "未化简到最简结果"
                    )
                    student_answer_text = ref_final_answer if ratio >= 0.7 else wrong_final_answer
                    answer_text = student_answer_text
                    steps = []
                    selected_option = None
                    filled_value = student_answer_text
                else:
                    if ratio >= 0.95:
                        steps = [str(item) for item in ref_steps]
                    elif ratio >= 0.55:
                        steps = [str(item) for item in ref_steps[:2]]
                        steps.append("步骤3：结论已给出但论证略简")
                    else:
                        steps = [str(item) for item in ref_steps[:1]]
                        steps.append("步骤2：中间关系建立不完整")
                    student_answer_text = "；".join(steps)
                    answer_text = student_answer_text
                    selected_option = None
                    filled_value = None

                answers.append(
                    {
                        "question_id": qid,
                        "question_type": qtype,
                        "skill_tags": skill_tags,
                        "status": "answered",
                        "score": score,
                        "max_score": max_score,
                        "is_correct": is_correct,
                        "selected_option": selected_option,
                        "filled_value": filled_value,
                        "student_answer_text": student_answer_text,
                        "answer_text": answer_text,
                        "steps": steps,
                        "skill_observations": [
                            {
                                "skill_id": skill_tags[0] if skill_tags and isinstance(skill_tags[0], str) else "unknown.skill",
                                "mastery_hint": "strong" if ratio >= 0.8 else ("medium" if ratio >= 0.55 else "weak"),
                                "evidence": f"{qid} 得分{score}/{max_score}",
                            }
                        ],
                        "trace": {
                            "scratchwork": True,
                            "corrections": ratio < 0.95,
                            "readability": 0.85 if error_type != "reading" else 0.52,
                            "confidence": round(0.62 + ratio * 0.33, 2),
                            "notes": "mock paper with concrete question and answer",
                        },
                        "teacher_review": {
                            "score": score,
                            "max_score": max_score,
                            "is_correct": bool(score == max_score),
                            "score_source_confidence": 0.86,
                        },
                        "correctness": {
                            "by_answer_key": bool(score == max_score),
                            "source": "answer_key",
                            "confidence": round(0.75 + ratio * 0.2, 2),
                            "reason": "依据模拟标准答案比对",
                            "conflict_with_teacher": False,
                        },
                        "error_analysis": {
                            "error_type": error_type,
                            "reason": reason,
                            "evidence": f"{qid} 学生作答：{student_answer_text}；得分{score}/{max_score}",
                            "suggestion": suggestion,
                        },
                    }
                )
                reference_answers.append(
                    {
                        "question_id": qid,
                        "sub_question_id": None,
                        "reference_answer_text": "；".join([str(item) for item in ref_steps]),
                        "reference_final_answer": ref_final_answer,
                        "reference_steps": [str(item) for item in ref_steps],
                        "confidence": 0.9,
                        "reason": "mock",
                    }
                )
            record_stage(
                "answer_trace",
                "ok",
                mode="mock",
                answer_count=len(answers),
                elapsed_ms=round((perf_counter() - answer_stage_start) * 1000, 1),
            )

            profile_stage_start = perf_counter()
            profile_data = self._build_profile_fallback(student_id, questions, answers)
            profile_data = _normalize_profile_payload(student_id, profile_data)
            record_stage(
                "student_profile",
                "ok",
                mode="mock",
                used_fallback=True,
                elapsed_ms=round((perf_counter() - profile_stage_start) * 1000, 1),
            )

            missing_from_step1 = _build_missing_from_step1(questions)
            structured_questions_full, mapping_report = _build_structured_questions_and_mapping_report(
                questions=questions,
                merged_answers=answers,
                answer_candidates=answers,
                unmatched_traces=[],
                missing_from_step1=missing_from_step1,
            )
            questions_with_trace = structured_questions_full
            answer_trace_display = _build_answer_trace_display(structured_questions_full)
            visible_main_qids = _collect_frontend_visible_main_question_ids(questions_with_trace, answer_trace_display)
            profile_data = _filter_profile_literacy_evidence_by_visible_questions(profile_data, visible_main_qids)
            _mock_localize_skill_payload(
                question_analysis=questions_with_trace,
                structured_questions_full=structured_questions_full,
                answer_trace=answers,
                answer_trace_display=answer_trace_display,
                student_profile=profile_data,
                skill_alias_map=skill_alias_map,
            )
            mapping_report["answer_block_mode"] = "manual_confirmed" if selected_answer_blocks else "auto"
            mapping_report["manual_block_count"] = len(selected_answer_blocks)
            mapping_report["mineru_selected_count"] = selected_block_source_counts.get("mineru", 0)
            mapping_report["refine_selected_count"] = selected_block_source_counts.get("project_segmenter", 0)
            run_finished_at = _now_iso()
            self._debug_active_run_dir = None
            return {
                "student_id": student_id,
                "input_mode": input_mode,
                "answer_key_source": "generated",
                "model_selection": model_selection,
                "reference_answers": reference_answers,
                "question_analysis": questions_with_trace,
                "structured_questions_full": structured_questions_full,
                "answer_trace": answers,
                "answer_trace_display": answer_trace_display,
                "mapping_report": mapping_report,
                "student_profile": profile_data,
                "new_knowledge_points": new_nodes,
                "skill_alias_map": skill_alias_map,
                "selected_answer_blocks_summary": {
                    "count": len(selected_answer_blocks),
                    "source_counts": selected_block_source_counts,
                },
                "warnings": warnings,
                "analysis_process": {
                    "started_at": run_started_at,
                    "finished_at": run_finished_at,
                    "mock_mode": True,
                    "stages": stage_logs,
                },
                "stage_debug_dir": str(debug_run_dir) if debug_run_dir else None,
            }

        assert self.profile is not None
        question_candidates = _extract_points_from_nodes(self.nodes)
        question_warnings: List[str] = []
        raw_trace_warnings: List[str] = []
        question_stage_start = perf_counter()
        bootstrap_executor = ThreadPoolExecutor(max_workers=2)
        question_future = None
        if not pre_split_questions:
            question_future = bootstrap_executor.submit(
                self._run_question_analysis_parallel,
                paper_urls,
                question_candidates,
                question_warnings,
            )
        raw_trace_future = bootstrap_executor.submit(
            self._run_answer_raw_trace_parallel,
            answer_urls,
            raw_trace_warnings,
            student_id=student_id,
            run_token=answer_run_token,
            selected_blocks=selected_answer_blocks,
        )
        if question_future is None:
            questions = list(pre_split_questions)
            missing_from_step1 = _build_missing_from_step1(questions)
            question_repair_rounds = 0
            repaired_question_count_step1 = 0
            question_stats = {
                "index_batches_total": 0,
                "index_batches_success": 0,
                "index_batches_failed": 0,
                "question_pass_chunks": 0,
                "question_repair_rounds": 0,
                "repaired_questions_count": 0,
                "paper_parallel_tasks": 0,
            }
            if missing_from_step1:
                warnings.append(
                    "question_analysis incomplete: missing question ids in detected range: "
                    + ", ".join(missing_from_step1)
                )
            record_stage(
                "question_analysis",
                "ok" if questions else "failed",
                mode="pre_split_payload",
                index_batches_total=question_stats["index_batches_total"],
                index_batches_success=question_stats["index_batches_success"],
                index_batches_failed=question_stats["index_batches_failed"],
                question_pass_chunks=question_stats["question_pass_chunks"],
                question_repair_rounds=question_repair_rounds,
                repaired_questions_count=repaired_question_count_step1,
                paper_parallel_tasks=question_stats["paper_parallel_tasks"],
                question_count=len(questions),
                missing_question_count=len(missing_from_step1),
                elapsed_ms=round((perf_counter() - question_stage_start) * 1000, 1),
            )
        else:
            questions, question_stats, missing_from_step1, question_repair_rounds, repaired_question_count_step1 = (
                question_future.result()
            )
            warnings.extend([item for item in question_warnings if isinstance(item, str) and item.strip()])
            if missing_from_step1:
                warnings.append(
                    "question_analysis incomplete: missing question ids in detected range: "
                    + ", ".join(missing_from_step1)
                )
            question_stage_status = "ok"
            if not questions:
                question_stage_status = "failed"
            elif question_stats["index_batches_failed"] > 0 or missing_from_step1:
                question_stage_status = "partial"
            record_stage(
                "question_analysis",
                question_stage_status,
                index_batches_total=question_stats["index_batches_total"],
                index_batches_success=question_stats["index_batches_success"],
                index_batches_failed=question_stats["index_batches_failed"],
                question_pass_chunks=question_stats["question_pass_chunks"],
                question_repair_rounds=question_repair_rounds,
                repaired_questions_count=repaired_question_count_step1,
                paper_parallel_tasks=question_stats["paper_parallel_tasks"],
                question_count=len(questions),
                missing_question_count=len(missing_from_step1),
                elapsed_ms=round((perf_counter() - question_stage_start) * 1000, 1),
            )

        knowledge_stage_start = perf_counter()
        knowledge_warnings: List[str] = []
        base_questions_for_parallel = questions
        self._log_progress(
            "demo.run",
            "parallel_stage_start",
            question_count=len(base_questions_for_parallel),
            answer_page_count=len(answer_urls),
        )
        try:
            questions, knowledge_stats = self._tag_questions_with_text_llm(
                base_questions_for_parallel,
                knowledge_warnings,
            )
        except Exception as exc:
            warnings.append(f"knowledge_tagging failed: {exc}")
            questions = base_questions_for_parallel
            knowledge_stats = {
                "question_count": len(base_questions_for_parallel),
                "tagged_question_count": 0,
                "group_count": 0,
                "group_pass_chunks": 0,
                "refine_pass_chunks": 0,
                "filtered_candidate_count_avg": 0,
            }
        warnings.extend([item for item in knowledge_warnings if isinstance(item, str) and item.strip()])

        record_stage(
            "knowledge_tagging",
            "ok" if knowledge_stats["tagged_question_count"] > 0 or not questions else "partial",
            question_count=knowledge_stats["question_count"],
            tagged_question_count=knowledge_stats["tagged_question_count"],
            knowledge_group_count=knowledge_stats.get("group_count", 0),
            knowledge_group_pass_chunks=knowledge_stats.get("group_pass_chunks", 0),
            knowledge_refine_pass_chunks=knowledge_stats.get("refine_pass_chunks", 0),
            filtered_candidate_count_avg=knowledge_stats.get("filtered_candidate_count_avg", 0),
            knowledge_tagging_mode=self.knowledge_tagging_mode,
            existing_tagged_count=knowledge_stats.get("existing_tagged_count", 0),
            elapsed_ms=round((perf_counter() - knowledge_stage_start) * 1000, 1),
        )

        answer_contexts = _build_answer_contexts(questions)
        answer_context_map = _build_answer_context_map(answer_contexts)
        post_question_executor = ThreadPoolExecutor(max_workers=2)
        reference_stage_start = perf_counter()
        pre_injected_ref_answers = payload.get("_pre_injected_reference_answers")
        if pre_injected_ref_answers and isinstance(pre_injected_ref_answers, list) and pre_injected_ref_answers:
            reference_answers = list(pre_injected_ref_answers)
            answer_key_source = "paper_project"
            reference_future = None
            record_stage(
                "reference_answer",
                "ok",
                answer_key_source=answer_key_source,
                reference_answer_count=len(reference_answers),
                answer_key_page_count=0,
                source="pre_injected",
                elapsed_ms=0.1,
            )
        else:
            reference_future = post_question_executor.submit(
                self._prepare_reference_answers,
                answer_key_urls=answer_key_urls,
                answer_contexts=answer_contexts,
                paper_urls=paper_urls,
                preferred_source=answer_key_source,
                warnings=warnings,
            )
        new_points_stage_start = perf_counter()
        def _ensure_new_points_timed() -> tuple[List[Dict[str, Any]], float]:
            started = perf_counter()
            return self._ensure_new_points(questions), round((perf_counter() - started) * 1000, 1)

        new_points_future = post_question_executor.submit(
            _ensure_new_points_timed,
        )
        route_pass_chunks = 0
        route_hinted_count = 0
        record_stage(
            "answer_route",
            "skipped",
            batches_total=0,
            batches_success=0,
            batches_failed=0,
            route_pass_chunks=route_pass_chunks,
            route_hinted_count=route_hinted_count,
            answer_parallel_tasks=0,
            skipped_reason="route stage disabled; final alignment relies on aggregated raw traces plus original questions",
            elapsed_ms=0.0,
        )

        answer_stage_start = perf_counter()
        try:
            page_raw_items, raw_stage_stats = raw_trace_future.result() if raw_trace_future is not None else ([], {})
        except Exception as exc:
            warnings.append(f"answer_raw_trace failed: {exc}")
            page_raw_items, raw_stage_stats = [], {
                "batches_total": 0,
                "batches_success": 0,
                "batches_failed": 0,
                "objective_pass_chunks": 0,
                "subjective_pass_chunks": 0,
                "answer_parallel_tasks": 0,
                "saved_crop_count": 0,
                "saved_crop_dir": None,
                "answer_block_mode": "manual_confirmed" if selected_answer_blocks else "auto",
                "plan_build_ms": 0.0,
                "raw_vlm_ms": 0.0,
                "structuring_ms": 0.0,
                "nonempty_raw_text_count": 0,
                "raw_plan_count": 0,
                "structured_answer_count": 0,
            }
        finally:
            bootstrap_executor.shutdown(wait=False)
        warnings.extend([item for item in raw_trace_warnings if isinstance(item, str) and item.strip()])
        raw_answers, unmatched_answer_traces, answer_stats = self._run_answer_trace_postprocess(
            questions,
            page_raw_items,
            warnings,
            raw_stage_stats=raw_stage_stats,
            answer_urls=answer_urls,
            student_id=student_id,
        )
        answer_batches_success = answer_stats["batches_success"]
        answer_batches_failed = answer_stats["batches_failed"]
        answer_batches_total = answer_stats["batches_total"]
        objective_pass_chunks = answer_stats["objective_pass_chunks"]
        subjective_pass_chunks = answer_stats["subjective_pass_chunks"]
        answer_pass_chunks = objective_pass_chunks + subjective_pass_chunks
        answer_repair_rounds = 0
        repaired_questions_count = repaired_question_count_step1
        mapping_refresh_ms_total = 0.0
        answer_repair_ms_total = 0.0
        repair_target_count_total = 0
        default_empty_reason_code = (
            "no_nonempty_raw_text"
            if int(answer_stats.get("nonempty_raw_text_count", 0) or 0) <= 0
            else "no_answer_candidate_mapped"
        )
        score_stage_start = perf_counter()
        score_answers, score_stats = self._run_answer_score_recognition(
            answer_urls,
            answer_contexts,
            raw_answers,
            warnings,
        )
        teacher_review_by_id = _build_teacher_review_map(answer_contexts, score_answers)
        if score_answers:
            raw_answers.extend(score_answers)
        record_stage(
            "answer_score",
            "ok" if score_stats.get("score_answer_count", 0) > 0 else "partial",
            score_answer_count=score_stats.get("score_answer_count", 0),
            score_page_count=score_stats.get("score_page_count", 0),
            elapsed_ms=round((perf_counter() - score_stage_start) * 1000, 1),
        )

        reference_generate_stats: Dict[str, Any] = {}
        if reference_future is not None:
            try:
                reference_answers, answer_key_source = reference_future.result()
                reference_generate_stats = getattr(self, "_last_reference_generate_stats", {})
                if not isinstance(reference_generate_stats, dict):
                    reference_generate_stats = {}
                record_stage(
                    "reference_answer",
                    "ok" if reference_answers else ("partial" if answer_key_source != "none" else "skipped"),
                    answer_key_source=answer_key_source,
                    reference_answer_count=len(reference_answers),
                    answer_key_page_count=len(answer_key_urls),
                    parallel_group="post_question",
                    input_item_count=len(answer_contexts),
                    chunk_count=reference_generate_stats.get("chunk_count", 0),
                    chunk_size=reference_generate_stats.get("chunk_size", 0),
                    generated_question_count=reference_generate_stats.get("generated_question_count", 0),
                    skipped_question_count=reference_generate_stats.get("skipped_question_count", 0),
                    elapsed_ms=round((perf_counter() - reference_stage_start) * 1000, 1),
                )
            except Exception as exc:
                warnings.append(f"reference_answer failed: {exc}")
                reference_answers, answer_key_source = [], "none"
                record_stage(
                    "reference_answer",
                    "failed",
                    answer_key_source=answer_key_source,
                    reference_answer_count=0,
                    answer_key_page_count=len(answer_key_urls),
                    parallel_group="post_question",
                input_item_count=len(answer_contexts),
                elapsed_ms=round((perf_counter() - reference_stage_start) * 1000, 1),
                error=str(exc),
            )

        try:
            new_nodes, new_points_actual_ms = new_points_future.result()
            skill_alias_map = self._build_skill_alias_map()
            record_stage(
                "new_knowledge_points",
                "ok",
                added_count=len(new_nodes),
                parallel_group="post_question",
                input_item_count=len(questions),
                actual_elapsed_ms=new_points_actual_ms,
                wait_elapsed_ms=round((perf_counter() - new_points_stage_start) * 1000, 1),
                elapsed_ms=round((perf_counter() - new_points_stage_start) * 1000, 1),
            )
        except Exception as exc:
            warnings.append(f"new_knowledge_points failed: {exc}")
            new_nodes = []
            record_stage(
                "new_knowledge_points",
                "failed",
                added_count=0,
                parallel_group="post_question",
                input_item_count=len(questions),
                elapsed_ms=round((perf_counter() - new_points_stage_start) * 1000, 1),
                error=str(exc),
            )
        finally:
            post_question_executor.shutdown(wait=False)

        def refresh_answer_mapping(
            *,
            repair_rounds_used: int,
            repaired_questions_count_value: int,
            log_start_done: bool = False,
        ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
            nonlocal mapping_refresh_ms_total
            if log_start_done:
                self._log_progress(
                    "answer_trace",
                    "mapping_refresh_start",
                    raw_answer_count=len(raw_answers),
                    unmatched_count=len(unmatched_answer_traces),
                )
            refresh_started = perf_counter()
            refreshed_answers, refreshed_structured, refreshed_report = _refresh_answer_mapping(
                questions=questions,
                answer_contexts=answer_contexts,
                raw_answers=raw_answers,
                unmatched_answer_traces=unmatched_answer_traces,
                missing_from_step1=missing_from_step1,
                default_empty_reason_code=default_empty_reason_code,
                question_pass_chunks=question_stats["question_pass_chunks"],
                answer_pass_chunks=answer_pass_chunks,
                route_pass_chunks=route_pass_chunks,
                repair_rounds_used=repair_rounds_used,
                repaired_questions_count=repaired_questions_count_value,
                route_hinted_count=route_hinted_count,
            )
            mapping_refresh_ms_total += (perf_counter() - refresh_started) * 1000
            if log_start_done:
                self._log_progress(
                    "answer_trace",
                    "mapping_refresh_done",
                    mapped_questions=refreshed_report.get("mapped_questions", 0),
                    unmatched_count=len(refreshed_report.get("unmatched_traces", [])) if isinstance(refreshed_report.get("unmatched_traces"), list) else 0,
                    elapsed_ms=round(mapping_refresh_ms_total, 1),
                )
            return refreshed_answers, refreshed_structured, refreshed_report

        answers, structured_questions_full, mapping_report = refresh_answer_mapping(
            repair_rounds_used=question_repair_rounds,
            repaired_questions_count_value=repaired_questions_count,
            log_start_done=True,
        )
        prev_mapped_questions = int(mapping_report.get("mapped_questions") or 0)
        prev_conflict_count = int(mapping_report.get("score_conflict_count") or 0)

        for _ in range(self.max_repair_rounds):
            repair_targets = _collect_answer_repair_targets(
                structured_questions_full,
                mapping_report,
                trigger_unseen=self.repair_trigger_unseen,
                trigger_unmatched=self.repair_trigger_unmatched,
                min_answer_confidence_for_skip_repair=self.min_answer_confidence_for_skip_repair,
            )
            if not repair_targets:
                break
            repair_target_count_total += len(repair_targets)
            answer_repair_rounds += 1
            self._log_progress(
                "answer_trace",
                "repair_round_selected",
                round=answer_repair_rounds,
                target_count=len(repair_targets),
            )
            repair_round_start = perf_counter()
            repair_round_result = self._run_answer_repair_round_parallel(
                repair_targets=repair_targets,
                questions=questions,
                answer_urls=answer_urls,
                raw_answers=raw_answers,
                answer_context_map=answer_context_map,
            )
            answer_pass_chunks += int(repair_round_result.get("pass_chunks", 0) or 0)
            raw_answers.extend(repair_round_result.get("raw_answers", []))
            unmatched_answer_traces.extend(repair_round_result.get("unmatched_traces", []))
            round_warnings = repair_round_result.get("warnings", [])
            if isinstance(round_warnings, list):
                warnings.extend([item for item in round_warnings if isinstance(item, str) and item.strip()])
            answer_repair_ms_total += (perf_counter() - repair_round_start) * 1000
            answers, structured_questions_full, mapping_report = refresh_answer_mapping(
                repair_rounds_used=question_repair_rounds + answer_repair_rounds,
                repaired_questions_count_value=repaired_questions_count,
            )
            mapped_after = int(mapping_report.get("mapped_questions") or 0)
            conflict_after = int(mapping_report.get("score_conflict_count") or 0)
            self._log_progress(
                "answer_trace",
                "repair_round_done",
                round=answer_repair_rounds,
                mapped_questions=mapped_after,
                score_conflict_count=conflict_after,
                elapsed_ms=round((perf_counter() - repair_round_start) * 1000, 1),
            )
            if mapped_after > prev_mapped_questions:
                repaired_questions_count += mapped_after - prev_mapped_questions
            if mapped_after <= prev_mapped_questions and conflict_after >= prev_conflict_count:
                break
            prev_mapped_questions = mapped_after
            prev_conflict_count = conflict_after

        mapping_report = _sync_mapping_report_pipeline_counters(
            mapping_report,
            question_pass_chunks=question_stats["question_pass_chunks"],
            answer_pass_chunks=answer_pass_chunks,
            route_pass_chunks=route_pass_chunks,
            repair_rounds_used=question_repair_rounds + answer_repair_rounds,
            repaired_questions_count=repaired_questions_count,
            route_hinted_count=route_hinted_count,
        )

        blind_stage_start = perf_counter()
        correctness_stage_start = perf_counter()
        self._last_blind_diagnosis_target_count = 0
        self._last_blind_diagnosis_skipped_count = 0
        self._log_progress(
            "blind_step_analysis",
            "start",
            answer_count=len(answers),
        )
        diagnosis_correctness_executor = ThreadPoolExecutor(max_workers=2)
        if self.blind_diagnosis_enabled:
            blind_future = diagnosis_correctness_executor.submit(
                self._run_blind_diagnosis,
                questions,
                answers,
                warnings,
            )
        else:
            blind_future = None
        correctness_future = diagnosis_correctness_executor.submit(
            self._run_answer_key_correctness,
            answer_contexts=answer_contexts,
            structured_questions_full=structured_questions_full,
            reference_answers=reference_answers,
            answer_key_source=answer_key_source,
            teacher_review_by_id=teacher_review_by_id,
            warnings=warnings,
        )
        if blind_future is not None:
            try:
                blind_by_id, blind_diagnosis_count = blind_future.result()
            except Exception as exc:
                warnings.append(f"blind_step_analysis failed: {exc}")
                blind_by_id, blind_diagnosis_count = {}, 0
        else:
            blind_by_id, blind_diagnosis_count = {}, 0
        _apply_diagnosis_fields_to_answers(
            answers,
            structured_questions_full,
            blind_by_id,
            teacher_review_by_id,
        )
        record_stage(
            "blind_step_analysis",
            "ok" if blind_diagnosis_count > 0 else ("skipped" if not self.blind_diagnosis_enabled else "partial"),
            blind_diagnosis_count=blind_diagnosis_count,
            diagnosis_target_count=getattr(self, "_last_blind_diagnosis_target_count", 0),
            skipped_diagnosis_count=getattr(self, "_last_blind_diagnosis_skipped_count", 0),
            teacher_signal_usage=self.teacher_signal_usage,
            review_mark_filter_mode=self.review_mark_filter_mode,
            parallel_group="diagnosis_correctness",
            input_item_count=len(answers),
            skipped_reason=None if self.blind_diagnosis_enabled else "blind diagnosis disabled by profile",
            elapsed_ms=round((perf_counter() - blind_stage_start) * 1000, 1),
        )

        try:
            correctness_items = correctness_future.result()
        except Exception as exc:
            warnings.append(f"answer_key_correctness failed: {exc}")
            correctness_items = []
        finally:
            diagnosis_correctness_executor.shutdown(wait=False)
        answer_key_verdict_count = _apply_answer_key_correctness_policy(
            answers=answers,
            structured_questions_full=structured_questions_full,
            correctness_items=correctness_items,
            teacher_review_by_id=teacher_review_by_id,
            answer_key_source=answer_key_source,
            reference_answers=reference_answers,
        )
        record_stage(
            "answer_key_correctness",
            "ok" if answer_key_verdict_count > 0 else ("partial" if reference_answers else "skipped"),
            answer_key_source=answer_key_source,
            reference_answer_count=len(reference_answers),
            judged_count=answer_key_verdict_count,
            parallel_group="diagnosis_correctness",
            input_item_count=len(reference_answers),
            elapsed_ms=round((perf_counter() - correctness_stage_start) * 1000, 1),
        )

        error_stage_start = perf_counter()
        self._log_progress(
            "error_analysis",
            "start",
            answer_count=len(answers),
        )
        error_analysis_count = sum(
            1
            for answer in answers
            if isinstance(answer.get("error_analysis"), dict)
        )
        record_stage(
            "error_analysis",
            "ok" if error_analysis_count > 0 else "partial",
            error_analysis_count=error_analysis_count,
            elapsed_ms=round((perf_counter() - error_stage_start) * 1000, 1),
        )

        questions_with_trace = structured_questions_full
        public_answers = [_public_answer_item(answer) for answer in answers]
        answer_trace_display = _build_answer_trace_display(structured_questions_full)
        mapping_report["knowledge_tagging_count"] = knowledge_stats["tagged_question_count"]
        mapping_report["objective_pass_chunks"] = objective_pass_chunks
        mapping_report["subjective_pass_chunks"] = subjective_pass_chunks
        mapping_report["matching_repair_rounds"] = answer_repair_rounds
        mapping_report["blind_diagnosis_count"] = blind_diagnosis_count
        mapping_report["blind_diagnosis_target_count"] = getattr(self, "_last_blind_diagnosis_target_count", 0)
        mapping_report["error_analysis_count"] = error_analysis_count
        mapping_report["paper_parallel_tasks"] = question_stats["paper_parallel_tasks"]
        mapping_report["answer_parallel_tasks"] = answer_stats["answer_parallel_tasks"]
        mapping_report["answer_segment_saved_crop_count"] = int(answer_stats.get("saved_crop_count", 0))
        if isinstance(answer_stats.get("saved_crop_dir"), str) and answer_stats.get("saved_crop_dir"):
            mapping_report["answer_segment_saved_crop_dir"] = answer_stats["saved_crop_dir"]
        if isinstance(answer_stats.get("raw_vlm_debug_json_path"), str) and answer_stats.get("raw_vlm_debug_json_path"):
            mapping_report["answer_raw_vlm_debug_json_path"] = answer_stats["raw_vlm_debug_json_path"]
        if isinstance(answer_stats.get("structuring_debug_json_path"), str) and answer_stats.get("structuring_debug_json_path"):
            mapping_report["answer_structuring_debug_json_path"] = answer_stats["structuring_debug_json_path"]
        if isinstance(answer_stats.get("alignment_debug_json_path"), str) and answer_stats.get("alignment_debug_json_path"):
            mapping_report["answer_alignment_debug_json_path"] = answer_stats["alignment_debug_json_path"]
        mapping_report["answer_plan_build_ms"] = answer_stats.get("plan_build_ms", 0.0)
        mapping_report["answer_raw_vlm_ms"] = answer_stats.get("raw_vlm_ms", 0.0)
        mapping_report["answer_structuring_ms"] = answer_stats.get("structuring_ms", 0.0)
        mapping_report["answer_alignment_ms"] = answer_stats.get("alignment_ms", 0.0)
        mapping_report["answer_structuring_chunk_count"] = int(answer_stats.get("answer_structuring_chunk_count", 0) or 0)
        mapping_report["answer_score_scan_ms"] = score_stats.get("score_scan_ms", 0.0)
        mapping_report["answer_score_answer_count"] = int(score_stats.get("score_answer_count", 0) or 0)
        mapping_report["answer_mapping_refresh_ms"] = round(mapping_refresh_ms_total, 1)
        mapping_report["answer_repair_ms"] = round(answer_repair_ms_total, 1)
        mapping_report["answer_raw_plan_count"] = int(answer_stats.get("raw_plan_count", 0) or 0)
        mapping_report["answer_nonempty_raw_text_count"] = int(answer_stats.get("nonempty_raw_text_count", 0) or 0)
        mapping_report["answer_structured_answer_count"] = int(answer_stats.get("structured_answer_count", 0) or 0)
        mapping_report["answer_repair_target_count"] = repair_target_count_total
        mapping_report["teacher_signal_usage"] = self.teacher_signal_usage
        mapping_report["review_mark_filter_mode"] = self.review_mark_filter_mode
        mapping_report["answer_key_source"] = answer_key_source
        mapping_report["reference_answer_count"] = len(reference_answers)
        mapping_report["reference_generate_chunk_count"] = int(reference_generate_stats.get("chunk_count", 0) or 0)
        mapping_report["reference_generate_chunk_size"] = int(reference_generate_stats.get("chunk_size", 0) or 0)
        mapping_report["reference_generate_skipped_count"] = int(reference_generate_stats.get("skipped_question_count", 0) or 0)
        mapping_report["answer_key_judged_count"] = answer_key_verdict_count
        mapping_report["profile_mode"] = self.profile_mode
        mapping_report["vision_profile"] = model_selection.get("vision_profile")
        mapping_report["text_profile"] = model_selection.get("text_profile")
        mapping_report["vision_model"] = model_selection.get("vision_model")
        mapping_report["text_model"] = model_selection.get("text_model")
        mapping_report["answer_block_mode"] = (
            str(answer_stats.get("answer_block_mode"))
            if isinstance(answer_stats.get("answer_block_mode"), str)
            else ("manual_confirmed" if selected_answer_blocks else "auto")
        )
        mapping_report["manual_block_count"] = len(selected_answer_blocks)
        mapping_report["mineru_selected_count"] = selected_block_source_counts.get("mineru", 0)
        mapping_report["refine_selected_count"] = selected_block_source_counts.get("project_segmenter", 0)
        if mapping_report["unmatched_traces"]:
            warnings.append(f"answer_trace has unmatched items: {len(mapping_report['unmatched_traces'])}")
        record_stage(
            "answer_trace",
            "ok" if answer_batches_failed == 0 else ("partial" if answer_batches_success > 0 else "failed"),
            batches_total=answer_batches_total,
            batches_success=answer_batches_success,
            batches_failed=answer_batches_failed,
            answer_count=len(public_answers),
            mapped_question_count=mapping_report["mapped_questions"],
            unmatched_trace_count=len(mapping_report["unmatched_traces"]),
            answer_pass_chunks=answer_pass_chunks,
            objective_pass_chunks=objective_pass_chunks,
            subjective_pass_chunks=subjective_pass_chunks,
            answer_repair_rounds=answer_repair_rounds,
            repaired_questions_count=repaired_questions_count,
            score_conflict_count=mapping_report.get("score_conflict_count", 0),
            answer_parallel_tasks=answer_stats["answer_parallel_tasks"],
            saved_crop_count=answer_stats.get("saved_crop_count", 0),
            saved_crop_dir=answer_stats.get("saved_crop_dir"),
            raw_vlm_debug_json_path=answer_stats.get("raw_vlm_debug_json_path"),
            structuring_debug_json_path=answer_stats.get("structuring_debug_json_path"),
            alignment_debug_json_path=answer_stats.get("alignment_debug_json_path"),
            answer_block_mode=mapping_report["answer_block_mode"],
            manual_block_count=len(selected_answer_blocks),
            raw_plan_count=answer_stats.get("raw_plan_count", 0),
            nonempty_raw_text_count=answer_stats.get("nonempty_raw_text_count", 0),
            structured_answer_count=answer_stats.get("structured_answer_count", 0),
            plan_build_ms=answer_stats.get("plan_build_ms", 0.0),
            raw_vlm_ms=answer_stats.get("raw_vlm_ms", 0.0),
            structuring_ms=answer_stats.get("structuring_ms", 0.0),
            alignment_ms=answer_stats.get("alignment_ms", 0.0),
            answer_structuring_chunk_count=answer_stats.get("answer_structuring_chunk_count", 0),
            score_scan_ms=score_stats.get("score_scan_ms", 0.0),
            score_answer_count=score_stats.get("score_answer_count", 0),
            answer_key_source=answer_key_source,
            reference_answer_count=len(reference_answers),
            answer_key_judged_count=answer_key_verdict_count,
            mapping_refresh_ms=round(mapping_refresh_ms_total, 1),
            answer_repair_ms=round(answer_repair_ms_total, 1),
            answer_repair_target_count=repair_target_count_total,
            elapsed_ms=round((perf_counter() - answer_stage_start) * 1000, 1),
        )

        profile_stage_start = perf_counter()
        profile_used_fallback = False
        rule_based_literacy = _build_rule_based_literacy_profile(questions, public_answers, self.literacy_mapping)
        self._log_progress(
            "student_profile",
            "start",
            answer_count=len(public_answers),
            mastery_signal_count=len([item for item in public_answers if _has_answer_signal(item)]),
            rule_literacy_count=len(rule_based_literacy),
            profile_mode=self.profile_mode,
        )
        if self.profile_mode in {"rule_first", "rule_only"}:
            profile_data = self._build_profile_fallback(student_id, questions, public_answers)
            profile_used_fallback = True
            self._log_progress(
                "student_profile",
                "rule_profile_done",
                elapsed_ms=round((perf_counter() - profile_stage_start) * 1000, 1),
            )
        else:
            try:
                profile_data = self._run_harness_stage(
                    HARNESS_STAGE_PROFILE,
                    prompt=_profile_prompt(
                        student_id,
                        questions,
                        public_answers,
                        self.graph,
                        rule_based_literacy,
                    ),
                    data_urls=[],
                    profile=self.text_profile,
                )
                self._log_progress(
                    "student_profile",
                    "llm_done",
                    elapsed_ms=round((perf_counter() - profile_stage_start) * 1000, 1),
                )
            except Exception as exc:
                warnings.append(f"student_profile failed: {exc}")
                profile_data = self._build_profile_fallback(student_id, questions, public_answers)
                profile_used_fallback = True
                self._log_progress(
                    "student_profile",
                    "fallback_done",
                    elapsed_ms=round((perf_counter() - profile_stage_start) * 1000, 1),
                )
        profile_data = _normalize_profile_payload(student_id, profile_data)
        visible_main_qids = _collect_frontend_visible_main_question_ids(questions_with_trace, answer_trace_display)
        profile_data = _filter_profile_literacy_evidence_by_visible_questions(profile_data, visible_main_qids)
        record_stage(
            "student_profile",
            "ok" if not profile_used_fallback else "fallback",
            used_fallback=profile_used_fallback,
            profile_mode=self.profile_mode,
            elapsed_ms=round((perf_counter() - profile_stage_start) * 1000, 1),
        )

        run_finished_at = _now_iso()
        self._debug_active_run_dir = None
        return {
            "student_id": student_id,
            "input_mode": input_mode,
            "answer_key_source": answer_key_source,
            "model_selection": model_selection,
            "reference_answers": reference_answers,
            "question_analysis": questions_with_trace,
            "structured_questions_full": structured_questions_full,
            "answer_trace": public_answers,
            "answer_trace_display": answer_trace_display,
            "mapping_report": mapping_report,
            "student_profile": profile_data,
            "new_knowledge_points": new_nodes,
            "skill_alias_map": skill_alias_map,
            "selected_answer_blocks_summary": {
                "count": len(selected_answer_blocks),
                "source_counts": selected_block_source_counts,
            },
            "warnings": warnings,
            "analysis_process": {
                "started_at": run_started_at,
                "finished_at": run_finished_at,
                "mock_mode": False,
                "stages": stage_logs,
            },
            "stage_debug_dir": str(debug_run_dir) if debug_run_dir else None,
        }

