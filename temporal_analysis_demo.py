from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Sequence

from mastery_engine import EngineConfig, MasteryStore, ingest_records


DEFAULT_DB_PATH = "mastery.db"
DEFAULT_RECENT_LIMIT = 20
MAX_RECENT_LIMIT = 100


def _parse_records(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("records is required and must be a list")
    if not records:
        raise ValueError("records must not be empty")

    normalized: List[Dict[str, Any]] = []
    for idx, item in enumerate(records):
        if not isinstance(item, dict):
            raise ValueError(f"records[{idx}] must be an object")
        normalized.append(item)
    return normalized


def _extract_single_student_id(records: Sequence[Dict[str, Any]]) -> str:
    student_ids: set[str] = set()
    for idx, record in enumerate(records):
        student_id = record.get("student_id")
        if not isinstance(student_id, str) or not student_id.strip():
            raise ValueError(f"records[{idx}].student_id is required")
        student_ids.add(student_id.strip())

    if len(student_ids) != 1:
        raise ValueError("records must contain exactly one student_id")
    return next(iter(student_ids))


def _parse_recent_limit(payload: Dict[str, Any]) -> int:
    raw = payload.get("recent_limit", DEFAULT_RECENT_LIMIT)
    if isinstance(raw, bool):
        raise ValueError("recent_limit must be an integer")
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("recent_limit must be an integer") from exc
    return max(1, min(MAX_RECENT_LIMIT, value))


def _parse_db_path(payload: Dict[str, Any]) -> Path:
    raw = payload.get("db_path", DEFAULT_DB_PATH)
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("db_path must be a non-empty string")
    return Path(raw.strip())


def _level(mastery: float) -> str:
    if mastery >= 0.9:
        return "mastered"
    if mastery >= 0.75:
        return "high"
    if mastery >= 0.6:
        return "medium"
    if mastery >= 0.4:
        return "low"
    return "weak"


def _format_skills(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    skills: List[Dict[str, Any]] = []
    for row in rows:
        mastery = float(row["mastery"])
        skills.append(
            {
                "skill_id": row["skill_id"],
                "mastery": round(mastery, 4),
                "level": _level(mastery),
                "last_update": row["last_update"],
                "uncertainty": row["uncertainty"],
            }
        )
    return skills


def run_temporal_demo(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")

    records = _parse_records(payload)
    student_id = _extract_single_student_id(records)
    recent_limit = _parse_recent_limit(payload)
    db_path = _parse_db_path(payload)

    store = MasteryStore(db_path)
    try:
        ingest_result = ingest_records(store, records, EngineConfig())
        skills = _format_skills(store.list_student_mastery(student_id))
        recent_changes = store.list_recent_changes(student_id, limit=recent_limit)
    finally:
        store.close()

    return {
        "student_id": student_id,
        "records_in": ingest_result["records_in"],
        "updates_applied": ingest_result["updates_applied"],
        "skills": skills,
        "recent_change_reasons": recent_changes,
    }
