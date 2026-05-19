from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional


def _as_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off"}:
            return False
    return default



def _coerce_optional_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "y", "on", "correct", "right", "对", "正确", "是"}:
            return True
        if text in {"0", "false", "no", "n", "off", "incorrect", "wrong", "错", "错误", "否"}:
            return False
    return None



def _first_present(raw: Dict[str, Any], keys: List[str]) -> Any:
    for key in keys:
        if key in raw and raw.get(key) is not None:
            return raw.get(key)
    return None



def _coerce_confidence(value: Any) -> Optional[float]:
    numeric = _coerce_optional_number(value)
    if not isinstance(numeric, (int, float)):
        return None
    return round(max(0.0, min(1.0, float(numeric))), 2)



def _coerce_optional_number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        # Extract first numeric token from strings like "扣2分" / "-1.5"
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        if not match:
            return None
        try:
            return float(match.group(0))
        except Exception:
            return None
    return None



def _build_chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if re.search(r"/api/v\d+$", normalized):
        return normalized + "/chat/completions"
    if normalized.endswith("/v1"):
        return normalized + "/chat/completions"
    return normalized + "/v1/chat/completions"



def _is_choice_or_blank(question_type: Any) -> bool:
    qtype = _normalize_question_type(question_type)
    return qtype in {"choice", "blank"}



def _strip_ellipsis_text(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    # Avoid returning abbreviated traces with ellipsis placeholders.
    if "..." in text or "…" in text:
        text = text.replace("...", "(truncated)").replace("…", "(truncated)")
        text = re.sub(r"\(truncated\)+", "(truncated)", text)
        text = re.sub(r"\s+", " ", text).strip()
    return text or None



def _normalize_question_type(value: Any) -> str:
    if not isinstance(value, str):
        return "unknown"
    text = value.strip().lower()
    if text in {"choice", "mcq", "multiple_choice", "select", "single_choice", "选择", "选择题", "单选"}:
        return "choice"
    if text in {"blank", "fill", "fill_blank", "fill_in_blank", "填空", "填空题"}:
        return "blank"
    if text in {"application", "word_problem", "应用", "应用题"}:
        return "application"
    if text in {"solution", "subjective", "solve", "解答", "解答题", "计算", "证明", "证明题"}:
        return "solution"
    return "unknown"



def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")



def _extract_file_names(files: Any) -> List[str]:
    if not isinstance(files, list):
        return []
    names: List[str] = []
    for item in files:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names



def _skill_group_id(skill_id: Any) -> Optional[str]:
    if not isinstance(skill_id, str):
        return None
    parts = [part.strip() for part in skill_id.strip().split(".") if part.strip()]
    if not parts:
        return None
    return ".".join(parts[:2]) if len(parts) >= 2 else parts[0]



def _chunk_list(items: List[Any], chunk_size: int) -> List[List[Any]]:
    if chunk_size <= 0:
        chunk_size = len(items) if items else 1
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]



def _compact_text(value: Any, limit: int = 500) -> str:
    if not isinstance(value, str):
        return ""
    text = re.sub(r"\s+", " ", value.strip())
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."



def _compact_steps(raw_steps: Any, *, limit: int = 8, text_limit: int = 220) -> List[str]:
    if not isinstance(raw_steps, list):
        return []
    steps: List[str] = []
    for raw_step in raw_steps[:limit]:
        if isinstance(raw_step, str) and raw_step.strip():
            steps.append(_compact_text(raw_step, text_limit))
        elif isinstance(raw_step, dict):
            content = raw_step.get("content") if isinstance(raw_step.get("content"), str) else raw_step.get("step")
            if isinstance(content, str) and content.strip():
                steps.append(_compact_text(content, text_limit))
    return steps



def _extract_main_and_sub_ids(value: Any) -> tuple[Optional[str], Optional[str]]:
    if not isinstance(value, str):
        return None, None
    text = value.strip()
    if not text:
        return None, None
    compact = re.sub(r"\s+", "", text)
    compact = (
        compact.replace("（", "(")
        .replace("）", ")")
        .replace("．", ".")
        .replace("。", ".")
        .replace("、", ".")
    )

    def _chinese_numeral_to_int(token: str) -> Optional[int]:
        if not isinstance(token, str):
            return None
        stripped = token.strip()
        if not stripped:
            return None
        digit_map = {
            "零": 0,
            "〇": 0,
            "一": 1,
            "二": 2,
            "两": 2,
            "三": 3,
            "四": 4,
            "五": 5,
            "六": 6,
            "七": 7,
            "八": 8,
            "九": 9,
        }
        unit_map = {"十": 10, "百": 100, "千": 1000}
        if stripped.isdigit():
            value_int = int(stripped)
            return value_int if 0 < value_int <= 999 else None
        current = 0
        number = 0
        has_valid = False
        for ch in stripped:
            if ch in digit_map:
                number = digit_map[ch]
                has_valid = True
                continue
            if ch in unit_map:
                has_valid = True
                unit = unit_map[ch]
                if number == 0:
                    number = 1
                current += number * unit
                number = 0
                continue
            return None
        if not has_valid:
            return None
        value_int = current + number
        if value_int <= 0 or value_int > 999:
            return None
        return value_int

    match_main = re.match(r"^(?:第)?[Qq]?0*(\d{1,3})(?:题)?", compact)
    if not match_main:
        match_main_cn = re.match(r"^(?:第)?([零〇一二两三四五六七八九十百千]{1,8})(?:题)?", compact)
        if match_main_cn:
            parsed = _chinese_numeral_to_int(match_main_cn.group(1))
            if isinstance(parsed, int) and parsed > 0:
                main_id = f"Q{parsed}"
                rest = compact[match_main_cn.end() :]
            else:
                return None, None
        else:
            return None, None
    else:
        main_id = f"Q{int(match_main.group(1))}"
        rest = compact[match_main.end() :]
    if not rest:
        return main_id, None
    rest = rest.lstrip(".-_:：")
    rest = rest.lstrip("([")
    rest = rest.rstrip(")]")
    if re.fullmatch(r"[0-9A-Za-z]+", rest):
        return main_id, rest.upper()
    if re.fullmatch(r"[零〇一二两三四五六七八九十百千]+", rest):
        parsed_sub = _chinese_numeral_to_int(rest)
        if isinstance(parsed_sub, int) and parsed_sub > 0:
            return main_id, str(parsed_sub)
    return main_id, None



def _canonical_question_id(value: Any) -> Optional[str]:
    main_id, _ = _extract_main_and_sub_ids(value)
    if isinstance(main_id, str) and main_id:
        return main_id
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None



def _canonical_sub_question_id(main_qid: str, value: Any) -> Optional[str]:
    if not isinstance(main_qid, str) or not main_qid:
        return None
    _, sub_id = _extract_main_and_sub_ids(value)
    if isinstance(sub_id, str) and sub_id:
        return f"{main_qid}({sub_id})"
    if isinstance(value, str):
        token = re.sub(r"\s+", "", value.strip())
        token = token.strip(".,;:!?()[]锛堬級銆愩€慱")
        if re.fullmatch(r"[0-9A-Za-z一二三四五六七八九十]+", token):
            return f"{main_qid}({token.upper()})"
    return None



def _mapping_pattern_matches(pattern: str, value: str) -> bool:
    normalized_pattern = pattern.strip().lower()
    normalized_value = value.strip().lower()
    if not normalized_pattern or not normalized_value:
        return False
    if normalized_pattern.endswith("*"):
        return normalized_value.startswith(normalized_pattern[:-1])
    return normalized_value == normalized_pattern or normalized_value.startswith(normalized_pattern)



def _question_literacy_signal(status: Any, ratio: Optional[float]) -> float:
    if isinstance(ratio, (int, float)):
        return max(-1.0, min(1.0, (float(ratio) - 0.5) * 2.0))
    if isinstance(status, str):
        token = status.strip().lower()
        if token == "answered":
            return 0.1
        if token == "unclear":
            return -0.2
        if token == "unseen":
            return -0.35
    return 0.0



def _is_choice_question_type(question_type: Any) -> bool:
    return isinstance(question_type, str) and question_type.strip().lower() == "choice"



def _answer_confidence(answer: Dict[str, Any]) -> float:
    trace = answer.get("trace")
    if isinstance(trace, dict) and isinstance(trace.get("confidence"), (int, float)):
        return max(0.0, min(1.0, float(trace["confidence"])))
    return 0.0



def _has_answer_signal(answer: Dict[str, Any]) -> bool:
    status = answer.get("status")
    if status in {"answered", "unclear"}:
        return True
    return any(
        (
            isinstance(answer.get("score"), (int, float)),
            isinstance(answer.get("deducted_score"), (int, float)),
            isinstance(answer.get("is_correct"), bool),
            isinstance(answer.get("student_answer_text"), str) and answer["student_answer_text"].strip(),
            isinstance(answer.get("selected_option"), str) and answer["selected_option"].strip(),
            isinstance(answer.get("filled_value"), str) and answer["filled_value"].strip(),
        )
    )




def _normalize_merge_text(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = _strip_ellipsis_text(value)
    if not isinstance(text, str):
        return None
    text = text.strip()
    return text or None


def _count_blocks_by_source(blocks: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for block in blocks:
        source = block.get("source")
        if isinstance(source, str) and source.strip():
            counts[source] = counts.get(source, 0) + 1
    return counts



def _compact_question_contexts(
    question_contexts: List[Dict[str, Any]],
    *,
    full_text_limit: int = 700,
) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    for item in question_contexts:
        if not isinstance(item, dict):
            continue
        qid = item.get("question_id")
        if not isinstance(qid, str) or not qid.strip():
            continue
        problem_text = item.get("problem_text") if isinstance(item.get("problem_text"), str) else ""
        problem_text_full = item.get("problem_text_full") if isinstance(item.get("problem_text_full"), str) else ""
        compact: Dict[str, Any] = {
            "question_id": qid.strip(),
            "question_type": _normalize_question_type(item.get("question_type")),
            "problem_text": _compact_text(problem_text or problem_text_full, 320),
            "sub_questions": _compact_sub_questions(item.get("sub_questions")),
            "skill_tags": [
                tag
                for tag in (item.get("skill_tags") if isinstance(item.get("skill_tags"), list) else [])
                if isinstance(tag, str) and tag.strip()
            ][:8],
        }
        if full_text_limit > 0 and problem_text_full:
            compact["problem_text_full"] = _compact_text(problem_text_full, full_text_limit)
        for key in (
            "max_score",
            "paper_page_index",
            "answer_page_hint",
            "question_order_index",
            "question_anchor_text",
            "neighbor_question_ids",
            "image_refs",
        ):
            value = item.get(key)
            if value is not None:
                compact[key] = value
        image_urls = item.get("question_image_urls")
        if isinstance(image_urls, list) and any(isinstance(url, str) and url.strip() for url in image_urls):
            compact["has_question_images"] = True
            compact["question_image_count"] = len([url for url in image_urls if isinstance(url, str) and url.strip()])
        output.append(compact)
    return output



def _compact_profile_answers(answers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    for answer in answers:
        if not isinstance(answer, dict):
            continue
        compact: Dict[str, Any] = {}
        for key in ("question_id", "sub_question_id", "status", "score", "max_score", "lost_score", "deducted_score", "is_correct"):
            value = answer.get(key)
            if value is not None:
                compact[key] = value
        skill_tags = answer.get("skill_tags")
        if isinstance(skill_tags, list):
            compact["skill_tags"] = [tag for tag in skill_tags if isinstance(tag, str) and tag.strip()][:8]
        for key in ("student_answer_text", "answer_text"):
            value = answer.get(key)
            if isinstance(value, str) and value.strip():
                compact[key] = _compact_text(value, 320)
        error_analysis = answer.get("error_analysis")
        if isinstance(error_analysis, dict):
            compact["error_analysis"] = {
                key: _compact_text(value, 240) if isinstance(value, str) else value
                for key, value in error_analysis.items()
                if key in {"error_type", "wrong_step", "step_reason", "reason", "evidence", "suggestion"}
            }
        correctness = answer.get("correctness")
        if isinstance(correctness, dict):
            compact["correctness"] = {
                key: value
                for key, value in correctness.items()
                if key in {"by_answer_key", "source", "confidence", "conflict_with_teacher"}
            }
        teacher_review = answer.get("teacher_review")
        if isinstance(teacher_review, dict):
            compact["teacher_review"] = {
                key: value
                for key, value in teacher_review.items()
                if key in {"score", "max_score", "deducted_score", "is_correct", "score_source_confidence"}
            }
        output.append(compact)
    return output



def _compact_skill_graph(
    graph: Dict[str, Any],
    compact_questions: List[Dict[str, Any]],
    compact_answers: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if not isinstance(graph, dict):
        return {"nodes": []}
    used_skill_ids: set[str] = set()
    for item in compact_questions + compact_answers:
        tags = item.get("skill_tags") if isinstance(item, dict) and isinstance(item.get("skill_tags"), list) else []
        used_skill_ids.update(tag for tag in tags if isinstance(tag, str) and tag.strip())
    raw_nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    nodes: List[Dict[str, Any]] = []
    for node in raw_nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id") if isinstance(node.get("id"), str) else node.get("skill_id")
        if used_skill_ids and node_id not in used_skill_ids:
            continue
        compact = {
            key: node.get(key)
            for key in ("id", "skill_id", "name", "short_name", "type", "parent_id")
            if node.get(key) is not None
        }
        aliases = node.get("aliases")
        if isinstance(aliases, list):
            compact["aliases"] = [alias for alias in aliases if isinstance(alias, str) and alias.strip()][:6]
        if compact:
            nodes.append(compact)
        if not used_skill_ids and len(nodes) >= 80:
            break
    return {"nodes": nodes, "selected_skill_count": len(used_skill_ids)}



def _compact_sub_questions(raw: Any, *, text_limit: int = 240) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    output: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        sub_qid = item.get("sub_question_id") if isinstance(item.get("sub_question_id"), str) else None
        sub_text = (
            item.get("sub_text")
            if isinstance(item.get("sub_text"), str)
            else item.get("problem_text") if isinstance(item.get("problem_text"), str) else ""
        )
        compact: Dict[str, Any] = {}
        if sub_qid:
            compact["sub_question_id"] = sub_qid
        if sub_text:
            compact["sub_text"] = _compact_text(sub_text, text_limit)
        max_score = item.get("max_score")
        if isinstance(max_score, (int, float)):
            compact["max_score"] = max_score
        if compact:
            output.append(compact)
    return output



def _compact_raw_answer_texts(raw_texts_by_page: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    for item in raw_texts_by_page:
        if not isinstance(item, dict):
            continue
        raw_text = item.get("raw_text") if isinstance(item.get("raw_text"), str) else ""
        if not raw_text.strip():
            continue
        output.append(
            {
                "page_index": item.get("page_index") if isinstance(item.get("page_index"), int) else None,
                "source": item.get("source") if isinstance(item.get("source"), str) else None,
                "section_name": item.get("section_name") if isinstance(item.get("section_name"), str) else None,
                "context_question_ids": [
                    qid
                    for qid in (item.get("context_question_ids") if isinstance(item.get("context_question_ids"), list) else [])
                    if isinstance(qid, str) and qid.strip()
                ][:20],
                "raw_text": _compact_text(raw_text, 3500),
            }
        )
    return output



def _compact_answer_candidates(answer_candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    for item in answer_candidates:
        if not isinstance(item, dict):
            continue
        compact: Dict[str, Any] = {}
        for key in (
            "question_id",
            "sub_question_id",
            "status",
            "score",
            "max_score",
            "deducted_score",
            "lost_score",
            "is_correct",
            "confidence",
            "page_index",
            "source_stage",
        ):
            value = item.get(key)
            if value is not None:
                compact[key] = value
        for key in ("student_answer_text", "answer_text", "selected_option", "filled_value", "evidence"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                compact[key] = _compact_text(value, 360)
        steps = _compact_steps(item.get("steps"))
        if steps:
            compact["steps"] = steps
        rule_conflicts = item.get("rule_conflicts")
        if isinstance(rule_conflicts, list) and rule_conflicts:
            compact["rule_conflicts"] = rule_conflicts[:4]
        if compact:
            output.append(compact)
    return output



def _question_sort_key(question: Dict[str, Any]) -> tuple[int, int, str]:
    qid = question.get("question_id") if isinstance(question.get("question_id"), str) else ""
    match = re.fullmatch(r"Q(\d{1,3})", qid)
    if match:
        return (0, int(match.group(1)), qid)
    return (1, 0, qid)



def _pick_questions_by_ids(questions: List[Dict[str, Any]], target_question_ids: List[str]) -> List[Dict[str, Any]]:
    if not target_question_ids:
        return list(questions)
    id_set = {qid for qid in target_question_ids if isinstance(qid, str) and qid}
    return [q for q in questions if isinstance(q, dict) and isinstance(q.get("question_id"), str) and q["question_id"] in id_set]

