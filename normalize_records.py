from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def infer_source_type(source: str) -> str:
    s = source.lower()
    if "paper" in s or "exam" in s or "midterm" in s or "final" in s:
        return "exam"
    if "hw" in s or "homework" in s:
        return "homework"
    return "practice"


def score_ratio(record: Dict[str, Any]) -> float:
    score = record.get("score")
    max_score = record.get("max_score")
    if score is not None and max_score not in (None, 0):
        return max(0.0, min(1.0, float(score) / float(max_score)))
    is_correct = record.get("is_correct")
    if isinstance(is_correct, bool):
        return 1.0 if is_correct else 0.0
    return 0.0


def to_evidence(record: Dict[str, Any]) -> Dict[str, Any]:
    y = score_ratio(record)
    if y >= 0.95:
        err = "unknown"
    elif y >= 0.7:
        err = "calculation"
    elif y >= 0.4:
        err = "concept"
    else:
        err = "reading"
    return {
        "skill_tags": record.get("knowledge_points") or [],
        "error_type": err,
        "method_correctness": round(y, 4),
        "solution_completeness": round(0.35 + 0.65 * y, 4),
        "confidence": 0.75,
        "notes": "generated_by_normalizer",
    }


def normalize_one(record: Dict[str, Any], student_id: str, default_source_id: str) -> Dict[str, Any]:
    source = str(record.get("source") or default_source_id)
    timestamp = record.get("timestamp", record.get("answered_at"))
    problem_id = record.get("problem_id", record.get("question_id"))
    skill_tags = record.get("knowledge_points") or record.get("skill_tags") or []
    if not skill_tags and isinstance(record.get("skill_id"), str):
        skill_tags = [record["skill_id"]]
    return {
        "student_id": student_id,
        "timestamp": timestamp,
        "problem_id": problem_id,
        "problem_text": record.get("problem_text"),
        "student_answer": record.get("student_answer"),
        "score": record.get("score"),
        "max_score": record.get("max_score"),
        "correct": record.get("correct", record.get("is_correct")),
        "source_type": infer_source_type(source),
        "source_id": source,
        "skill_id": (skill_tags or [None])[0],
        "evidence": to_evidence(
            {
                "knowledge_points": skill_tags,
                "score": record.get("score"),
                "max_score": record.get("max_score"),
                "is_correct": record.get("correct", record.get("is_correct")),
            }
        ),
    }


def normalize_records(payload: Any, student_id: str, default_source_id: str) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        payload = payload.get("records")
    if not isinstance(payload, list):
        raise ValueError("input should be list or {records: list}")
    result: List[Dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        out = normalize_one(item, student_id, default_source_id)
        if out["timestamp"] and out["problem_id"]:
            result.append(out)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize legacy history records to MVP schema.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--student-id", required=True)
    parser.add_argument("--default-source-id", default="unknown_source")
    args = parser.parse_args()

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    normalized = normalize_records(payload, args.student_id, args.default_source_id)
    Path(args.output).write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"normalized {len(normalized)} records -> {args.output}")


if __name__ == "__main__":
    main()
