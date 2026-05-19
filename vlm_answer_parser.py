from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from llm_knowledge_tagger import (
    _content_to_text,
    _load_llm_profile,
    _loads_json_like,
    call_llm_with_image,
)

from prompt_store import PromptStore

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def _iter_images(path: Path) -> Iterable[Path]:
    if path.is_file():
        if path.suffix.lower() in IMAGE_EXTS:
            yield path
        return
    for image_path in sorted(path.rglob("*")):
        if image_path.is_file() and image_path.suffix.lower() in IMAGE_EXTS:
            yield image_path


def _qid_sort_key(qid: str) -> Tuple[int, str]:
    match = re.match(r"^[Qq](\d+)$", qid.strip())
    if match:
        return int(match.group(1)), qid
    return 10**9, qid


def _load_question_map(path: Path) -> Dict[str, Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("question map must be a JSON list")
    question_map: Dict[str, Dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        qid = item.get("question_id")
        if not isinstance(qid, str) or not qid:
            continue
        question_map[qid] = {
            "question_type": item.get("question_type"),
            "knowledge_points": item.get("knowledge_points") or [],
            "max_score": item.get("max_score"),
            "source": item.get("source"),
            "difficulty": item.get("difficulty"),
        }
    return question_map


def _build_candidates(question_map: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidates = []
    for qid in sorted(question_map.keys(), key=_qid_sort_key):
        candidates.append(
            {
                "question_id": qid,
                "question_type": question_map[qid].get("question_type") or "unknown",
                "knowledge_points": question_map[qid].get("knowledge_points") or [],
            }
        )
    return candidates


def _build_prompt(candidates: List[Dict[str, Any]]) -> str:
    return PromptStore.vlm_answer_parser_prompt(candidates)



def _parse_score_text(text: str) -> Tuple[Optional[float], Optional[float]]:
    if not text:
        return None, None
    match = re.search(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", text)
    if match:
        return float(match.group(1)), float(match.group(2))
    return None, None


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _to_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "yes", "1"}:
            return True
        if text in {"false", "no", "0"}:
            return False
    return None


def _normalize_item(
    item: Dict[str, Any],
    question_map: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    qid = item.get("question_id")
    if not isinstance(qid, str) or qid not in question_map:
        return None

    score = _to_float(item.get("score"))
    max_score = _to_float(item.get("max_score"))
    score_text = item.get("score_text")
    if (score is None or max_score is None) and isinstance(score_text, str):
        parsed_score, parsed_total = _parse_score_text(score_text)
        score = score if score is not None else parsed_score
        max_score = max_score if max_score is not None else parsed_total

    is_correct = _to_bool(item.get("is_correct"))
    if is_correct is None:
        if score is not None and max_score is not None:
            is_correct = score >= max_score
    status = item.get("status") if isinstance(item.get("status"), str) else ""
    if status not in {"answered", "unseen", "unclear"}:
        raw_student_answer = item.get("student_answer_text")
        if not isinstance(raw_student_answer, str):
            raw_student_answer = item.get("answer_text") if isinstance(item.get("answer_text"), str) else None
        has_signal = any(
            (
                score is not None,
                is_correct is not None,
                isinstance(raw_student_answer, str) and bool(raw_student_answer.strip()),
                isinstance(item.get("selected_option"), str) and bool(item.get("selected_option").strip()),
                isinstance(item.get("filled_value"), str) and bool(item.get("filled_value").strip()),
            )
        )
        status = "answered" if has_signal else "unseen"
    student_answer_text = item.get("student_answer_text")
    if not isinstance(student_answer_text, str):
        student_answer_text = item.get("answer_text") if isinstance(item.get("answer_text"), str) else None

    selected_option = item.get("selected_option")
    if not isinstance(selected_option, str):
        selected_option = None
    filled_value = item.get("filled_value")
    if not isinstance(filled_value, str):
        filled_value = None
    question_type = item.get("question_type")
    if not isinstance(question_type, str):
        question_type = "unknown"

    steps = item.get("steps")
    if not isinstance(steps, list):
        steps = []
    else:
        steps = [s.strip() for s in steps if isinstance(s, str) and s.strip()]

    scratchwork = _to_bool(item.get("scratchwork"))
    corrections = _to_bool(item.get("corrections"))

    readability = _to_float(item.get("readability"))
    if readability is not None:
        readability = max(0.0, min(1.0, readability))

    confidence = _to_float(item.get("confidence"))
    if confidence is not None:
        confidence = max(0.0, min(1.0, confidence))

    notes = item.get("notes")
    if not isinstance(notes, str):
        notes = None

    meta = question_map[qid]
    return {
        "question_id": qid,
        "question_type": question_type,
        "status": status,
        "knowledge_points": meta.get("knowledge_points") or [],
        "is_correct": is_correct,
        "score": score,
        "max_score": max_score if max_score is not None else meta.get("max_score"),
        "selected_option": selected_option,
        "filled_value": filled_value,
        "student_answer_text": student_answer_text,
        "answer_text": student_answer_text,
        "answered_at": None,
        "difficulty": meta.get("difficulty"),
        "source": meta.get("source"),
        "time_spent_sec": None,
        "steps": steps,
        "trace": {
            "scratchwork": scratchwork,
            "corrections": corrections,
            "readability": readability,
            "confidence": confidence,
            "notes": notes,
        },
    }


def _parse_items(
    response: Dict[str, Any],
    question_map: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    choices = response.get("choices", [])
    if not choices:
        return []
    message = choices[0].get("message", {})
    content = _content_to_text(message.get("content", ""))
    if not content.strip():
        return []
    data = _loads_json_like(content)
    if not isinstance(data, dict):
        return []
    items = data.get("items")
    if not isinstance(items, list):
        return []

    records: List[Dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        record = _normalize_item(raw, question_map)
        if record:
            records.append(record)
    return records


def _record_rank(record: Dict[str, Any]) -> float:
    # Prefer records with scoring info and higher confidence.
    score = 0.0
    if record.get("score") is not None:
        score += 1.0
    if record.get("max_score") is not None:
        score += 1.0
    if isinstance(record.get("selected_option"), str) and record["selected_option"].strip():
        score += 0.6
    if isinstance(record.get("filled_value"), str) and record["filled_value"].strip():
        score += 0.6
    if isinstance(record.get("student_answer_text"), str) and record["student_answer_text"].strip():
        score += 0.6
    trace = record.get("trace") if isinstance(record.get("trace"), dict) else {}
    conf = trace.get("confidence")
    if isinstance(conf, (int, float)):
        score += float(conf)
    steps = record.get("steps")
    if isinstance(steps, list):
        score += min(1.0, len(steps) * 0.2)
    return score


def _merge_records(
    existing: Dict[str, Dict[str, Any]],
    incoming: Iterable[Dict[str, Any]],
) -> None:
    for record in incoming:
        qid = record.get("question_id")
        if not isinstance(qid, str):
            continue
        current = existing.get(qid)
        if not current or _record_rank(record) > _record_rank(current):
            existing[qid] = record


def _extract_student_id(folder_name: str) -> str:
    parts = folder_name.split("_")
    if parts and parts[-1].isdigit():
        return parts[-1]
    return folder_name


def build_history_records(
    student_dir: Path,
    question_map: Dict[str, Dict[str, Any]],
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout: int,
    max_retries: int,
    backoff_base_sec: float,
    min_interval_sec: float,
    use_env_proxy: bool,
    enable_thinking: bool,
    provider: str,
    max_tokens: int,
) -> List[Dict[str, Any]]:
    candidates = _build_candidates(question_map)
    prompt = _build_prompt(candidates)
    collected: Dict[str, Dict[str, Any]] = {}

    for image_path in _iter_images(student_dir):
        response = call_llm_with_image(
            image_path,
            prompt,
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=timeout,
            max_retries=max_retries,
            backoff_base_sec=backoff_base_sec,
            min_interval_sec=min_interval_sec,
            use_env_proxy=use_env_proxy,
            enable_thinking=enable_thinking,
            provider=provider,
            max_tokens=max_tokens,
            json_mode=True,
        )
        items = _parse_items(response, question_map)
        _merge_records(collected, items)

    return [collected[qid] for qid in sorted(collected, key=_qid_sort_key)]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse student answer sheet images with VLM to build structured records."
    )
    parser.add_argument(
        "--answers-root",
        required=True,
        help="Root folder containing per-student subfolders.",
    )
    parser.add_argument(
        "--question-map",
        required=True,
        help="Path to paper_knowledge_records.json.",
    )
    parser.add_argument(
        "--output-root",
        default=None,
        help="Output root (default: write history_records.json in each student folder).",
    )
    parser.add_argument(
        "--config",
        default="llm_config.json",
        help="Path to LLM config JSON (default: llm_config.json).",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="LLM profile name defined in config (overrides defaults.profile).",
    )
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--backoff-base-sec", type=float, default=1.5)
    parser.add_argument("--min-interval-sec", type=float, default=0.0)
    args = parser.parse_args()

    question_map = _load_question_map(Path(args.question_map))
    profile = _load_llm_profile(Path(args.config), args.profile)
    answers_root = Path(args.answers_root)
    output_root = Path(args.output_root) if args.output_root else answers_root

    for student_dir in sorted(answers_root.iterdir()):
        if not student_dir.is_dir():
            continue
        records = build_history_records(
            student_dir,
            question_map,
            base_url=profile["base_url"],
            api_key=profile["api_key"],
            model=profile["model"],
            timeout=args.timeout,
            max_retries=args.max_retries,
            backoff_base_sec=args.backoff_base_sec,
            min_interval_sec=args.min_interval_sec,
            use_env_proxy=profile.get("use_env_proxy", True),
            enable_thinking=profile.get("enable_thinking", False),
            provider=profile.get("provider", "openai_compatible"),
            max_tokens=profile.get("max_tokens", 0),
        )
        student_id = _extract_student_id(student_dir.name)
        output_dir = output_root / student_dir.name
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "history_records.json"
        output_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"{student_id}: {len(records)} records -> {output_path}")


if __name__ == "__main__":
    main()
