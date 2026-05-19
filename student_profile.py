from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass
class CalcParams:
    half_life_days: float = 30.0
    target_attempts: float = 8.0
    min_score_for_correct: float = 0.999


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _difficulty_weight(difficulty: Optional[float]) -> float:
    if difficulty is None:
        return 1.0
    diff = _clamp(float(difficulty), 0.0, 1.0)
    return 0.5 + 0.5 * diff


def _time_decay(answered_at: Optional[datetime], now: datetime, half_life_days: float) -> float:
    if answered_at is None:
        return 1.0
    delta_days = max(0.0, (now - answered_at).total_seconds() / 86400.0)
    if half_life_days <= 0:
        return 1.0
    return 0.5 ** (delta_days / half_life_days)


def _record_score(record: Dict[str, Any]) -> Tuple[float, Optional[bool]]:
    score = record.get("score")
    max_score = record.get("max_score")
    if score is not None and max_score:
        try:
            score_value = float(score) / float(max_score)
        except (TypeError, ValueError, ZeroDivisionError):
            score_value = 0.0
        score_value = _clamp(score_value, 0.0, 1.0)
        is_correct = record.get("is_correct")
        if isinstance(is_correct, bool):
            return score_value, is_correct
        return score_value, None
    is_correct = record.get("is_correct")
    if isinstance(is_correct, bool):
        return (1.0 if is_correct else 0.0), is_correct
    return 0.0, None


def _level_from_mastery(mastery: Optional[float]) -> str:
    if mastery is None:
        return "unknown"
    if mastery >= 0.9:
        return "mastered"
    if mastery >= 0.75:
        return "high"
    if mastery >= 0.6:
        return "medium"
    if mastery >= 0.4:
        return "low"
    return "weak"


def _confidence(attempts: int, target_attempts: float) -> float:
    if attempts <= 0:
        return 0.0
    if target_attempts <= 0:
        return 1.0
    return 1.0 - math.exp(-attempts / target_attempts)


def _normalize_records(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        records = payload.get("records")
        if isinstance(records, list):
            return [r for r in records if isinstance(r, dict)]
    return []


def _load_records(path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = _normalize_records(payload)
    if not records:
        raise ValueError("history records are empty or invalid")
    return records


def _load_all_nodes(key_word_path: Path) -> List[str]:
    payload = json.loads(key_word_path.read_text(encoding="utf-8"))
    nodes = payload.get("nodes", [])
    ids: List[str] = []
    if isinstance(nodes, list):
        for node in nodes:
            if isinstance(node, dict):
                node_id = node.get("id")
                if isinstance(node_id, str):
                    ids.append(node_id)
    return ids


def build_profile(
    student_id: str,
    records: Iterable[Dict[str, Any]],
    params: CalcParams,
    now: Optional[datetime] = None,
    include_unknown: bool = False,
    all_nodes: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    mastery_map: Dict[str, Dict[str, Any]] = {}
    overall_weighted_score = 0.0
    overall_weight = 0.0
    total_attempts = 0

    for record in records:
        kps = record.get("knowledge_points") or []
        if not isinstance(kps, list) or not kps:
            continue
        score, is_correct = _record_score(record)
        answered_at = _parse_datetime(record.get("answered_at"))
        weight = _time_decay(answered_at, now, params.half_life_days)
        weight *= _difficulty_weight(record.get("difficulty"))
        question_id = record.get("question_id")
        source = record.get("source")
        evidence_id = None
        if isinstance(question_id, str) and isinstance(source, str):
            evidence_id = f"{source}#{question_id}"
        elif isinstance(question_id, str):
            evidence_id = question_id

        for kp_id in kps:
            if not isinstance(kp_id, str):
                continue
            agg = mastery_map.setdefault(
                kp_id,
                {
                    "attempts": 0,
                    "correct": 0,
                    "score_sum": 0.0,
                    "weight_sum": 0.0,
                    "weighted_score_sum": 0.0,
                    "last_seen": None,
                    "evidence": [],
                },
            )
            agg["attempts"] += 1
            if is_correct is not None:
                agg["correct"] += 1 if is_correct else 0
            else:
                agg["correct"] += 1 if score >= params.min_score_for_correct else 0
            agg["score_sum"] += score
            agg["weight_sum"] += weight
            agg["weighted_score_sum"] += score * weight
            if answered_at:
                last_seen = agg["last_seen"]
                if last_seen is None or answered_at > last_seen:
                    agg["last_seen"] = answered_at
            if evidence_id and len(agg["evidence"]) < 5:
                agg["evidence"].append(evidence_id)
            total_attempts += 1
            overall_weighted_score += score * weight
            overall_weight += weight

    profile_mastery: Dict[str, Dict[str, Any]] = {}
    for kp_id, agg in mastery_map.items():
        weight_sum = agg["weight_sum"]
        mastery = agg["weighted_score_sum"] / weight_sum if weight_sum > 0 else None
        score_avg = agg["score_sum"] / agg["attempts"] if agg["attempts"] > 0 else None
        profile_mastery[kp_id] = {
            "mastery": None if mastery is None else round(mastery, 4),
            "level": _level_from_mastery(mastery),
            "confidence": round(_confidence(agg["attempts"], params.target_attempts), 4),
            "attempts": agg["attempts"],
            "correct": agg["correct"],
            "score_avg": None if score_avg is None else round(score_avg, 4),
            "last_seen": agg["last_seen"].isoformat() if agg["last_seen"] else None,
            "evidence": agg["evidence"],
        }

    if include_unknown and all_nodes is not None:
        for node_id in all_nodes:
            if node_id not in profile_mastery:
                profile_mastery[node_id] = {
                    "mastery": None,
                    "level": "unknown",
                    "confidence": 0.0,
                    "attempts": 0,
                    "correct": 0,
                    "score_avg": None,
                    "last_seen": None,
                    "evidence": [],
                }

    overall_mastery = None
    if overall_weight > 0:
        overall_mastery = round(overall_weighted_score / overall_weight, 4)

    profile = {
        "meta": {
            "schema_version": "v1.0",
            "generated_at": now.isoformat(),
            "calc_params": {
                "half_life_days": params.half_life_days,
                "target_attempts": params.target_attempts,
                "min_score_for_correct": params.min_score_for_correct,
                "difficulty_weight": "0.5 + 0.5 * difficulty",
                "time_decay": "0.5 ** (delta_days / half_life_days)",
            },
        },
        "student": {"id": student_id},
        "summary": {
            "knowledge_points_seen": len(profile_mastery),
            "total_attempts": total_attempts,
            "overall_mastery": overall_mastery,
        },
        "mastery": profile_mastery,
    }
    return profile


def main() -> None:
    parser = argparse.ArgumentParser(description="Build student mastery profile from history records.")
    parser.add_argument("--history", required=True, help="Path to history records json.")
    parser.add_argument("--output", required=True, help="Output profile json path.")
    parser.add_argument("--student-id", required=True, help="Student id.")
    parser.add_argument("--half-life-days", type=float, default=30.0)
    parser.add_argument("--target-attempts", type=float, default=8.0)
    parser.add_argument("--min-score-for-correct", type=float, default=0.999)
    parser.add_argument("--key-word", help="Path to key_word.json to include unknown nodes.")
    parser.add_argument("--include-unknown", action="store_true", help="Include all nodes from key_word.")
    args = parser.parse_args()

    records = _load_records(Path(args.history))
    params = CalcParams(
        half_life_days=args.half_life_days,
        target_attempts=args.target_attempts,
        min_score_for_correct=args.min_score_for_correct,
    )
    all_nodes = None
    if args.include_unknown and args.key_word:
        all_nodes = _load_all_nodes(Path(args.key_word))

    profile = build_profile(
        student_id=args.student_id,
        records=records,
        params=params,
        include_unknown=args.include_unknown,
        all_nodes=all_nodes,
    )
    Path(args.output).write_text(json.dumps(profile, ensure_ascii=True, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
