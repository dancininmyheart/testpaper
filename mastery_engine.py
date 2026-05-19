from __future__ import annotations

import argparse
import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


ALLOWED_SOURCE_TYPES = {"exam", "practice", "homework"}
ALLOWED_ERROR_TYPES = {"concept", "calculation", "reading", "strategy", "unknown"}


@dataclass(frozen=True)
class EngineConfig:
    eta: float = 0.25
    decay_lambda_per_day: float = 0.008
    source_weights: Dict[str, float] = None  # type: ignore[assignment]
    initial_mastery: float = 0.5

    def __post_init__(self) -> None:
        if self.source_weights is None:
            object.__setattr__(
                self,
                "source_weights",
                {"exam": 1.0, "practice": 0.75, "homework": 0.55},
            )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    else:
        raise ValueError("invalid timestamp")
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def parse_score_ratio(record: Dict[str, Any]) -> float:
    score = record.get("score")
    max_score = record.get("max_score")
    if score is not None and max_score not in (None, 0):
        return clamp(float(score) / float(max_score))
    correct = record.get("correct")
    if isinstance(correct, bool):
        return 1.0 if correct else 0.0
    is_correct = record.get("is_correct")
    if isinstance(is_correct, bool):
        return 1.0 if is_correct else 0.0
    return 0.0


def ensure_list_str(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str) and v.strip()]


def validate_evidence(evidence: Dict[str, Any]) -> Dict[str, Any]:
    skill_tags = ensure_list_str(evidence.get("skill_tags"))
    error_type = evidence.get("error_type", "unknown")
    if error_type not in ALLOWED_ERROR_TYPES:
        error_type = "unknown"
    method_correctness = clamp(float(evidence.get("method_correctness", 0.5)))
    solution_completeness = clamp(float(evidence.get("solution_completeness", 0.5)))
    confidence = clamp(float(evidence.get("confidence", 0.6)))
    notes = evidence.get("notes", "")
    return {
        "skill_tags": skill_tags,
        "error_type": error_type,
        "method_correctness": method_correctness,
        "solution_completeness": solution_completeness,
        "confidence": confidence,
        "notes": notes if isinstance(notes, str) else "",
    }


def heuristic_evidence(record: Dict[str, Any]) -> Dict[str, Any]:
    y = parse_score_ratio(record)
    if y >= 0.95:
        error_type = "unknown"
    elif y >= 0.7:
        error_type = "calculation"
    elif y >= 0.4:
        error_type = "concept"
    else:
        error_type = "reading"
    skill_tags = ensure_list_str(record.get("skill_tags"))
    if not skill_tags:
        skill_tags = ensure_list_str(record.get("knowledge_points"))
    return {
        "skill_tags": skill_tags,
        "error_type": error_type,
        "method_correctness": clamp(y),
        "solution_completeness": clamp(0.35 + 0.65 * y),
        "confidence": 0.75,
        "notes": "heuristic_diagnosis",
    }


def normalize_record(raw: Dict[str, Any]) -> Dict[str, Any]:
    required = ["student_id", "timestamp", "problem_id", "source_type"]
    missing = [k for k in required if k not in raw]
    if missing:
        raise ValueError(f"missing required fields: {missing}")

    source_type = str(raw["source_type"]).strip().lower()
    if source_type not in ALLOWED_SOURCE_TYPES:
        raise ValueError(f"invalid source_type: {source_type}")

    record = {
        "student_id": str(raw["student_id"]).strip(),
        "timestamp": parse_time(raw["timestamp"]).isoformat(),
        "problem_id": str(raw["problem_id"]).strip(),
        "problem_text": raw.get("problem_text"),
        "student_answer": raw.get("student_answer"),
        "score": raw.get("score"),
        "max_score": raw.get("max_score"),
        "correct": raw.get("correct", raw.get("is_correct")),
        "source_type": source_type,
        "source_id": str(raw.get("source_id") or raw.get("paper_id") or "unknown"),
        "skill_id": raw.get("skill_id"),
    }
    evidence = raw.get("evidence")
    if isinstance(evidence, dict):
        record["evidence"] = validate_evidence(evidence)
    else:
        record["evidence"] = validate_evidence(heuristic_evidence(raw))
    return record


class MasteryStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS student_mastery (
                student_id TEXT NOT NULL,
                skill_id TEXT NOT NULL,
                mastery REAL NOT NULL,
                last_update TEXT NOT NULL,
                uncertainty REAL,
                PRIMARY KEY (student_id, skill_id)
            );

            CREATE TABLE IF NOT EXISTS evidence_chain (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                event_time TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_id TEXT NOT NULL,
                problem_id TEXT NOT NULL,
                skill_id TEXT NOT NULL,
                score_ratio REAL NOT NULL,
                s_before REAL NOT NULL,
                s_after REAL NOT NULL,
                evidence_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS knowledge_graph (
                skill_id_from TEXT NOT NULL,
                skill_id_to TEXT NOT NULL,
                confidence REAL NOT NULL,
                source TEXT NOT NULL,
                PRIMARY KEY (skill_id_from, skill_id_to)
            );

            CREATE INDEX IF NOT EXISTS idx_evidence_student_time
            ON evidence_chain (student_id, event_time);

            CREATE INDEX IF NOT EXISTS idx_evidence_source
            ON evidence_chain (source_id, source_type);
            """
        )
        self.conn.commit()

    def get_mastery(self, student_id: str, skill_id: str) -> Optional[sqlite3.Row]:
        cur = self.conn.execute(
            """
            SELECT student_id, skill_id, mastery, last_update, uncertainty
            FROM student_mastery
            WHERE student_id = ? AND skill_id = ?
            """,
            (student_id, skill_id),
        )
        return cur.fetchone()

    def upsert_mastery(
        self,
        student_id: str,
        skill_id: str,
        mastery: float,
        last_update: str,
        uncertainty: Optional[float],
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO student_mastery (student_id, skill_id, mastery, last_update, uncertainty)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(student_id, skill_id) DO UPDATE SET
              mastery = excluded.mastery,
              last_update = excluded.last_update,
              uncertainty = excluded.uncertainty
            """,
            (student_id, skill_id, mastery, last_update, uncertainty),
        )

    def add_evidence(
        self,
        student_id: str,
        event_time: str,
        source_type: str,
        source_id: str,
        problem_id: str,
        skill_id: str,
        score_ratio: float,
        s_before: float,
        s_after: float,
        evidence_json: Dict[str, Any],
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO evidence_chain (
              student_id, event_time, source_type, source_id, problem_id, skill_id,
              score_ratio, s_before, s_after, evidence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                student_id,
                event_time,
                source_type,
                source_id,
                problem_id,
                skill_id,
                score_ratio,
                s_before,
                s_after,
                json.dumps(evidence_json, ensure_ascii=False),
            ),
        )

    def commit(self) -> None:
        self.conn.commit()

    def list_student_mastery(self, student_id: str) -> List[Dict[str, Any]]:
        cur = self.conn.execute(
            """
            SELECT skill_id, mastery, last_update, uncertainty
            FROM student_mastery
            WHERE student_id = ?
            ORDER BY mastery ASC
            """,
            (student_id,),
        )
        return [dict(r) for r in cur.fetchall()]

    def list_recent_changes(self, student_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        cur = self.conn.execute(
            """
            SELECT event_time, source_type, source_id, problem_id, skill_id, score_ratio, s_before, s_after, evidence_json
            FROM evidence_chain
            WHERE student_id = ?
            ORDER BY event_time DESC, id DESC
            LIMIT ?
            """,
            (student_id, limit),
        )
        rows = [dict(r) for r in cur.fetchall()]
        for row in rows:
            row["evidence"] = json.loads(row.pop("evidence_json"))
        return rows

    def list_student_evidence_between(self, student_id: str, start: str, end: str) -> List[Dict[str, Any]]:
        cur = self.conn.execute(
            """
            SELECT event_time, source_type, source_id, problem_id, skill_id, score_ratio, s_before, s_after, evidence_json
            FROM evidence_chain
            WHERE student_id = ? AND event_time >= ? AND event_time <= ?
            ORDER BY event_time ASC, id ASC
            """,
            (student_id, start, end),
        )
        rows = [dict(r) for r in cur.fetchall()]
        for row in rows:
            row["evidence"] = json.loads(row.pop("evidence_json"))
        return rows

    def list_exam_analysis(self, source_id: str) -> List[Dict[str, Any]]:
        cur = self.conn.execute(
            """
            SELECT problem_id, skill_id, source_type, score_ratio, evidence_json, COUNT(*) AS n
            FROM evidence_chain
            WHERE source_id = ?
            GROUP BY problem_id, skill_id, source_type, score_ratio, evidence_json
            ORDER BY problem_id, skill_id
            """,
            (source_id,),
        )
        rows = [dict(r) for r in cur.fetchall()]
        for row in rows:
            row["evidence"] = json.loads(row.pop("evidence_json"))
        return rows


def decayed_mastery(prev_mastery: float, last_update: datetime, now_time: datetime, lam: float) -> float:
    delta_days = max(0.0, (now_time - last_update).total_seconds() / 86400.0)
    return clamp(prev_mastery * math.exp(-lam * delta_days))


def update_student_skill(
    s_before: float,
    y: float,
    source_weight: float,
    evidence: Dict[str, Any],
    eta: float,
) -> float:
    r = source_weight * evidence["confidence"] * (0.5 + 0.5 * evidence["method_correctness"])
    return clamp(s_before + eta * r * (y - s_before))


def ingest_records(
    store: MasteryStore,
    records: Sequence[Dict[str, Any]],
    config: Optional[EngineConfig] = None,
) -> Dict[str, Any]:
    cfg = config or EngineConfig()
    normalized = [normalize_record(r) for r in records]
    normalized.sort(key=lambda r: r["timestamp"])

    applied = 0
    for record in normalized:
        student_id = record["student_id"]
        source_type = record["source_type"]
        source_weight = cfg.source_weights.get(source_type, 0.5)
        y = parse_score_ratio(record)
        event_time = parse_time(record["timestamp"])
        evidence = record["evidence"]
        skill_tags = evidence["skill_tags"]
        if not skill_tags and isinstance(record.get("skill_id"), str):
            skill_tags = [record["skill_id"]]
        if not skill_tags:
            continue

        for skill_id in skill_tags:
            current = store.get_mastery(student_id, skill_id)
            if current:
                prev_mastery = float(current["mastery"])
                last_update = parse_time(current["last_update"])
                s_before = decayed_mastery(prev_mastery, last_update, event_time, cfg.decay_lambda_per_day)
            else:
                s_before = cfg.initial_mastery
            s_after = update_student_skill(s_before, y, source_weight, evidence, cfg.eta)
            uncertainty = round(1.0 - evidence["confidence"], 4)
            store.upsert_mastery(student_id, skill_id, round(s_after, 6), event_time.isoformat(), uncertainty)
            store.add_evidence(
                student_id=student_id,
                event_time=event_time.isoformat(),
                source_type=source_type,
                source_id=record["source_id"],
                problem_id=record["problem_id"],
                skill_id=skill_id,
                score_ratio=round(y, 6),
                s_before=round(s_before, 6),
                s_after=round(s_after, 6),
                evidence_json=evidence,
            )
            applied += 1
    store.commit()
    return {"records_in": len(records), "updates_applied": applied}


def _load_json_records(path: Path) -> List[Dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        items = payload.get("records")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    raise ValueError("input must be list[dict] or {\"records\": [...]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic student mastery engine.")
    parser.add_argument("--db", default="mastery.db", help="SQLite database path.")
    parser.add_argument("--input", required=True, help="Path to normalized records json.")
    parser.add_argument("--eta", type=float, default=0.25, help="Update speed.")
    parser.add_argument("--decay-lambda", type=float, default=0.008, help="Forgetting rate per day.")
    args = parser.parse_args()

    records = _load_json_records(Path(args.input))
    cfg = EngineConfig(eta=args.eta, decay_lambda_per_day=args.decay_lambda)
    store = MasteryStore(Path(args.db))
    try:
        result = ingest_records(store, records, cfg)
    finally:
        store.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
