from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .db import Database


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode_json(value: str, default: Any) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return default


@dataclass
class SessionInfo:
    token: str
    user_id: int
    username: str
    role: str
    expires_at: str


class UserRepository:
    def __init__(self, db: Database):
        self.db = db

    def get_by_username(self, username: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT id, username, password_hash, role, created_at, updated_at FROM users WHERE username=?",
            (username,),
        )
        return dict(row) if row else None

    def get_by_id(self, user_id: int) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT id, username, password_hash, role, created_at, updated_at FROM users WHERE id=?",
            (user_id,),
        )
        return dict(row) if row else None

    def create_user(self, *, username: str, password_hash: str, role: str) -> int:
        ts = now_iso()
        cur = self.db.execute(
            "INSERT INTO users(username, password_hash, role, created_at, updated_at) VALUES(?, ?, ?, ?, ?)",
            (username, password_hash, role, ts, ts),
        )
        return int(cur.lastrowid)


class SessionRepository:
    def __init__(self, db: Database):
        self.db = db

    def create_session(self, *, token: str, user_id: int, ttl_hours: int) -> str:
        created = datetime.now(timezone.utc)
        expires = created + timedelta(hours=ttl_hours)
        self.db.execute(
            "INSERT INTO sessions(token, user_id, created_at, expires_at, revoked_at) VALUES(?, ?, ?, ?, NULL)",
            (token, user_id, created.isoformat(), expires.isoformat()),
        )
        return expires.isoformat()

    def get_active_session(self, token: str) -> SessionInfo | None:
        row = self.db.query_one(
            """
            SELECT s.token, s.user_id, s.expires_at, u.username, u.role
            FROM sessions s
            JOIN users u ON u.id=s.user_id
            WHERE s.token=? AND s.revoked_at IS NULL
            """,
            (token,),
        )
        if row is None:
            return None
        expires_at = datetime.fromisoformat(str(row["expires_at"]))
        if expires_at < datetime.now(timezone.utc):
            return None
        return SessionInfo(
            token=str(row["token"]),
            user_id=int(row["user_id"]),
            username=str(row["username"]),
            role=str(row["role"]),
            expires_at=str(row["expires_at"]),
        )

    def revoke(self, token: str) -> None:
        self.db.execute("UPDATE sessions SET revoked_at=? WHERE token=?", (now_iso(), token))


class AnalysisRepository:
    def __init__(self, db: Database):
        self.db = db

    def create_job(
        self,
        *,
        job_id: str,
        student_id: str,
        input_mode: str,
        payload: dict[str, Any],
        created_by: int,
        paper_project_id: str | None = None,
    ) -> None:
        ts = now_iso()
        self.db.execute(
            """
            INSERT INTO analysis_jobs(
              job_id, student_id, input_mode, status, payload_json, stage_logs_json,
              created_by, attempt_count, error_message, created_at, updated_at,
              paper_project_id
            ) VALUES (?, ?, ?, 'queued', ?, '[]', ?, 0, NULL, ?, ?, ?)
            """,
            (job_id, student_id, input_mode, json.dumps(payload, ensure_ascii=False),
             created_by, ts, ts, paper_project_id),
        )

    def add_job_file(
        self,
        *,
        job_id: str,
        category: str,
        file_name: str,
        local_path: str,
        content_type: str | None,
        size_bytes: int,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO analysis_job_files(job_id, category, file_name, local_path, content_type, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (job_id, category, file_name, local_path, content_type, size_bytes, now_iso()),
        )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            """
            SELECT job_id, student_id, input_mode, status, payload_json, stage_logs_json, created_by,
                   attempt_count, error_message, created_at, updated_at, started_at, finished_at,
                   paper_project_id
            FROM analysis_jobs
            WHERE job_id=?
            """,
            (job_id,),
        )
        if row is None:
            return None
        data = dict(row)
        data["payload"] = _decode_json(str(data.pop("payload_json", "{}")), {})
        data["stage_logs"] = _decode_json(str(data.pop("stage_logs_json", "[]")), [])
        return data

    def list_job_files(self, job_id: str) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            """
            SELECT id, job_id, category, file_name, local_path, content_type, size_bytes, created_at
            FROM analysis_job_files
            WHERE job_id=?
            ORDER BY id ASC
            """,
            (job_id,),
        )
        return [dict(row) for row in rows]

    def list_jobs(self, *, limit: int, created_by: int | None = None) -> list[dict[str, Any]]:
        if created_by is None:
            rows = self.db.query_all(
                """
                SELECT job_id, student_id, input_mode, status, created_by, attempt_count, error_message,
                       created_at, updated_at, started_at, finished_at, paper_project_id
                FROM analysis_jobs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        else:
            rows = self.db.query_all(
                """
                SELECT job_id, student_id, input_mode, status, created_by, attempt_count, error_message,
                       created_at, updated_at, started_at, finished_at, paper_project_id
                FROM analysis_jobs
                WHERE created_by=?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (created_by, limit),
            )
        return [dict(row) for row in rows]

    def claim_next_queued_job(self) -> dict[str, Any] | None:
        with self.db.with_lock():
            row = self.db.conn.execute(
                """
                SELECT job_id, student_id, input_mode, status, payload_json, stage_logs_json, created_by,
                       attempt_count, error_message, created_at, updated_at, started_at, finished_at,
                       paper_project_id
                FROM analysis_jobs
                WHERE status='queued'
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            job_id = str(row["job_id"])
            ts = now_iso()
            self.db.conn.execute(
                """
                UPDATE analysis_jobs
                SET status='running',
                    attempt_count=attempt_count + 1,
                    error_message=NULL,
                    started_at=?,
                    updated_at=?
                WHERE job_id=? AND status='queued'
                """,
                (ts, ts, job_id),
            )
            self.db.conn.commit()
            refreshed = self.db.conn.execute(
                """
                SELECT job_id, student_id, input_mode, status, payload_json, stage_logs_json, created_by,
                       attempt_count, error_message, created_at, updated_at, started_at, finished_at,
                       paper_project_id,
                       paper_project_id
                FROM analysis_jobs WHERE job_id=?
                """,
                (job_id,),
            ).fetchone()
            if refreshed is None:
                return None
            data = dict(refreshed)
            data["payload"] = _decode_json(str(data.pop("payload_json", "{}")), {})
            data["stage_logs"] = _decode_json(str(data.pop("stage_logs_json", "[]")), [])
            return data

    def mark_job_succeeded(self, job_id: str, *, stage_logs: list[dict[str, Any]]) -> None:
        ts = now_iso()
        self.db.execute(
            """
            UPDATE analysis_jobs
            SET status='succeeded', updated_at=?, finished_at=?, stage_logs_json=?
            WHERE job_id=?
            """,
            (ts, ts, json.dumps(stage_logs, ensure_ascii=False), job_id),
        )

    def mark_job_failed(self, job_id: str, *, error_message: str, stage_logs: list[dict[str, Any]] | None = None) -> None:
        ts = now_iso()
        stage_payload = json.dumps(stage_logs or [], ensure_ascii=False)
        self.db.execute(
            """
            UPDATE analysis_jobs
            SET status='failed', updated_at=?, finished_at=?, error_message=?, stage_logs_json=?
            WHERE job_id=?
            """,
            (ts, ts, error_message[:4000], stage_payload, job_id),
        )

    def mark_job_canceled(self, job_id: str) -> None:
        self.db.execute(
            "UPDATE analysis_jobs SET status='canceled', updated_at=?, finished_at=? WHERE job_id=?",
            (now_iso(), now_iso(), job_id),
        )

    def update_job_payload(self, job_id: str, payload: dict[str, Any]) -> None:
        self.db.execute(
            "UPDATE analysis_jobs SET payload_json=? WHERE job_id=?",
            (json.dumps(payload, ensure_ascii=False), job_id),
        )

    def retry_job(self, job_id: str) -> None:
        self.db.execute(
            """
            UPDATE analysis_jobs
            SET status='queued', updated_at=?, started_at=NULL, finished_at=NULL, error_message=NULL, stage_logs_json='[]'
            WHERE job_id=?
            """,
            (now_iso(), job_id),
        )

    def recover_stale_running_jobs(self) -> int:
        ts = now_iso()
        with self.db.with_lock():
            cur = self.db.conn.execute(
                """
                UPDATE analysis_jobs
                SET status='queued', updated_at=?, started_at=NULL, error_message='recovered after restart'
                WHERE status='running'
                """,
                (ts,),
            )
            self.db.conn.commit()
            return cur.rowcount

    def save_job_result(self, *, job_id: str, result: dict[str, Any]) -> None:
        ts = now_iso()
        payload = json.dumps(result, ensure_ascii=False)
        exists = self.db.query_one("SELECT job_id FROM analysis_results WHERE job_id=?", (job_id,))
        if exists is None:
            self.db.execute(
                "INSERT INTO analysis_results(job_id, result_json, created_at, updated_at) VALUES(?, ?, ?, ?)",
                (job_id, payload, ts, ts),
            )
            return
        self.db.execute(
            "UPDATE analysis_results SET result_json=?, updated_at=? WHERE job_id=?",
            (payload, ts, job_id),
        )

    def get_job_result(self, job_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT result_json FROM analysis_results WHERE job_id=?", (job_id,))
        if row is None:
            return None
        return _decode_json(str(row["result_json"]), None)

    def list_project_runs(self, *, project_id: str, created_by: int) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            """
            SELECT
              j.job_id, j.student_id, j.input_mode, j.status, j.created_by,
              j.attempt_count, j.error_message, j.created_at, j.updated_at,
              j.started_at, j.finished_at, j.paper_project_id,
              CASE WHEN r.job_id IS NULL THEN 0 ELSE 1 END AS has_result
            FROM analysis_jobs j
            LEFT JOIN analysis_results r ON r.job_id = j.job_id
            WHERE j.paper_project_id=? AND j.created_by=?
            ORDER BY COALESCE(j.finished_at, j.updated_at, j.created_at) DESC, j.job_id DESC
            """,
            (project_id, created_by),
        )
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["has_result"] = bool(item.get("has_result"))
            items.append(item)
        return items

    def get_project_run(self, *, project_id: str, job_id: str, created_by: int) -> dict[str, Any] | None:
        row = self.db.query_one(
            """
            SELECT
              j.job_id, j.student_id, j.input_mode, j.status, j.created_by,
              j.attempt_count, j.error_message, j.created_at, j.updated_at,
              j.started_at, j.finished_at, j.paper_project_id,
              CASE WHEN r.job_id IS NULL THEN 0 ELSE 1 END AS has_result
            FROM analysis_jobs j
            LEFT JOIN analysis_results r ON r.job_id = j.job_id
            WHERE j.paper_project_id=? AND j.job_id=? AND j.created_by=?
            """,
            (project_id, job_id, created_by),
        )
        if row is None:
            return None
        item = dict(row)
        item["has_result"] = bool(item.get("has_result"))
        return item


class MasteryEventRepository:
    def __init__(self, db: Database):
        self.db = db

    def add_event(self, *, student_id: str, payload: dict[str, Any], created_by: int) -> None:
        self.db.execute(
            "INSERT INTO mastery_events(student_id, payload_json, created_by, created_at) VALUES(?, ?, ?, ?)",
            (student_id, json.dumps(payload, ensure_ascii=False), created_by, now_iso()),
        )


class AnalysisReviewRepository:
    def __init__(self, db: Database):
        self.db = db

    def approve_job(
        self,
        *,
        job_id: str,
        project_id: str,
        student_id: str,
        reviewed_by: int,
    ) -> dict[str, Any]:
        ts = now_iso()
        exists = self.db.query_one("SELECT job_id FROM analysis_job_reviews WHERE job_id=?", (job_id,))
        if exists is None:
            self.db.execute(
                """
                INSERT INTO analysis_job_reviews(
                  job_id, project_id, student_id, review_status, reviewed_by,
                  reviewed_at, created_at, updated_at
                ) VALUES (?, ?, ?, 'approved', ?, ?, ?, ?)
                """,
                (job_id, project_id, student_id, reviewed_by, ts, ts, ts),
            )
        else:
            self.db.execute(
                """
                UPDATE analysis_job_reviews
                SET project_id=?, student_id=?, review_status='approved',
                    reviewed_by=?, reviewed_at=?, updated_at=?
                WHERE job_id=?
                """,
                (project_id, student_id, reviewed_by, ts, ts, job_id),
            )
        row = self.db.query_one(
            """
            SELECT job_id, project_id, student_id, review_status, reviewed_by,
                   reviewed_at, created_at, updated_at
            FROM analysis_job_reviews
            WHERE job_id=?
            """,
            (job_id,),
        )
        return dict(row) if row else {}

    def list_approved_student_reports(self, *, student_id: str, created_by: int) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            """
            SELECT
              r.job_id, r.project_id, r.student_id, r.reviewed_at,
              j.created_at, j.updated_at, j.finished_at,
              p.title, p.subject, p.grade,
              ar.result_json
            FROM analysis_job_reviews r
            JOIN analysis_jobs j ON j.job_id = r.job_id
            JOIN analysis_results ar ON ar.job_id = r.job_id
            LEFT JOIN paper_projects p ON p.project_id = r.project_id
            WHERE r.reviewed_by=? AND r.student_id=? AND r.review_status='approved'
            ORDER BY r.reviewed_at DESC, r.job_id DESC
            """,
            (created_by, student_id),
        )
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["result"] = _decode_json(str(item.pop("result_json", "{}")), {})
            items.append(item)
        return items


class StudentStateRepository:
    def __init__(self, db: Database):
        self.db = db

    def save_snapshot(
        self,
        *,
        student_id: str,
        created_by: int,
        summary: dict[str, Any],
        mastery: list[dict[str, Any]],
        literacy: list[dict[str, Any]],
        evidence: dict[str, Any],
        source_report_ids: list[str],
        source_version: str,
        updated_at: str,
    ) -> None:
        payload = (
            student_id,
            created_by,
            json.dumps(summary, ensure_ascii=False),
            json.dumps(mastery, ensure_ascii=False),
            json.dumps(literacy, ensure_ascii=False),
            json.dumps(evidence, ensure_ascii=False),
            json.dumps(source_report_ids, ensure_ascii=False),
            source_version,
            updated_at,
        )
        exists = self.db.query_one(
            "SELECT student_id FROM student_state_snapshots WHERE student_id=? AND created_by=?",
            (student_id, created_by),
        )
        if exists is None:
            self.db.execute(
                """
                INSERT INTO student_state_snapshots(
                  student_id, created_by, summary_json, mastery_json, literacy_json,
                  evidence_json, source_report_ids_json, source_version, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                payload,
            )
            return
        self.db.execute(
            """
            UPDATE student_state_snapshots
            SET summary_json=?, mastery_json=?, literacy_json=?, evidence_json=?,
                source_report_ids_json=?, source_version=?, updated_at=?
            WHERE student_id=? AND created_by=?
            """,
            (
                payload[2],
                payload[3],
                payload[4],
                payload[5],
                payload[6],
                payload[7],
                payload[8],
                student_id,
                created_by,
            ),
        )

    def get_snapshot(self, *, student_id: str, created_by: int) -> dict[str, Any] | None:
        row = self.db.query_one(
            """
            SELECT student_id, created_by, summary_json, mastery_json, literacy_json,
                   evidence_json, source_report_ids_json, source_version, updated_at
            FROM student_state_snapshots
            WHERE student_id=? AND created_by=?
            """,
            (student_id, created_by),
        )
        if row is None:
            return None
        data = dict(row)
        return {
            "student_id": data["student_id"],
            "created_by": data["created_by"],
            "summary": _decode_json(str(data["summary_json"]), {}),
            "mastery": _decode_json(str(data["mastery_json"]), []),
            "literacy": _decode_json(str(data["literacy_json"]), []),
            "evidence": _decode_json(str(data["evidence_json"]), {}),
            "source_report_ids": _decode_json(str(data["source_report_ids_json"]), []),
            "source_version": data["source_version"],
            "updated_at": data["updated_at"],
        }


class StudentRepository:
    def __init__(self, db: Database):
        self.db = db

    def create_student(self, *, student_id: str, name: str, grade: str, created_by: int) -> dict[str, Any]:
        ts = now_iso()
        try:
            self.db.execute(
                """
                INSERT INTO students(student_id, name, grade, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (student_id, name, grade, created_by, ts, ts),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("student already exists") from exc
        student = self.get_student(student_id=student_id, created_by=created_by)
        if student is None:
            raise ValueError("student create failed")
        return student

    def list_students(self, *, created_by: int) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            """
            SELECT id, student_id, name, grade, created_by, created_at, updated_at
            FROM students
            WHERE created_by=?
            ORDER BY updated_at DESC, id DESC
            """,
            (created_by,),
        )
        return [dict(row) for row in rows]

    def get_student(self, *, student_id: str, created_by: int) -> dict[str, Any] | None:
        row = self.db.query_one(
            """
            SELECT id, student_id, name, grade, created_by, created_at, updated_at
            FROM students
            WHERE created_by=? AND student_id=?
            """,
            (created_by, student_id),
        )
        return dict(row) if row else None

    def update_student(
        self,
        *,
        student_id: str,
        created_by: int,
        name: str | None = None,
        grade: str | None = None,
    ) -> dict[str, Any] | None:
        parts: list[str] = []
        params: list[Any] = []
        if name is not None:
            parts.append("name=?")
            params.append(name)
        if grade is not None:
            parts.append("grade=?")
            params.append(grade)
        if not parts:
            return self.get_student(student_id=student_id, created_by=created_by)
        parts.append("updated_at=?")
        params.append(now_iso())
        params.extend([created_by, student_id])
        self.db.execute(
            f"UPDATE students SET {', '.join(parts)} WHERE created_by=? AND student_id=?",
            tuple(params),
        )
        return self.get_student(student_id=student_id, created_by=created_by)

    def list_latest_project_reports(self, *, student_id: str, created_by: int) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            """
            SELECT
              j.job_id, j.student_id, j.status, j.created_at, j.updated_at, j.finished_at,
              j.paper_project_id AS project_id,
              p.title, p.subject, p.grade, p.student_count,
              (
                SELECT COUNT(*)
                FROM paper_questions q
                WHERE q.project_id = p.project_id
              ) AS question_count
            FROM analysis_jobs j
            JOIN analysis_results r ON r.job_id = j.job_id
            JOIN paper_projects p ON p.project_id = j.paper_project_id
            WHERE j.created_by=? AND j.student_id=? AND j.status='succeeded' AND j.paper_project_id IS NOT NULL
            ORDER BY COALESCE(j.finished_at, j.updated_at, j.created_at) DESC, j.job_id DESC
            """,
            (created_by, student_id),
        )
        latest_by_project: dict[str, dict[str, Any]] = {}
        for row in rows:
            item = dict(row)
            project_id = str(item.get("project_id") or "")
            if not project_id or project_id in latest_by_project:
                continue
            item["analyzed_at"] = item.get("finished_at") or item.get("updated_at") or item.get("created_at")
            latest_by_project[project_id] = item
        return list(latest_by_project.values())

    def get_latest_project_report(
        self,
        *,
        student_id: str,
        project_id: str,
        created_by: int,
    ) -> dict[str, Any] | None:
        row = self.db.query_one(
            """
            SELECT r.result_json
            FROM analysis_jobs j
            JOIN analysis_results r ON r.job_id = j.job_id
            WHERE j.created_by=? AND j.student_id=? AND j.paper_project_id=? AND j.status='succeeded'
            ORDER BY COALESCE(j.finished_at, j.updated_at, j.created_at) DESC, j.job_id DESC
            LIMIT 1
            """,
            (created_by, student_id, project_id),
        )
        if row is None:
            return None
        return _decode_json(str(row["result_json"]), None)


class AuditRepository:
    def __init__(self, db: Database):
        self.db = db

    def log(
        self,
        *,
        actor_user_id: int | None,
        action: str,
        target_type: str | None,
        target_id: str | None,
        detail: dict[str, Any],
    ) -> None:
        self.db.execute(
            """
            INSERT INTO audit_logs(actor_user_id, action, target_type, target_id, detail_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                actor_user_id,
                action,
                target_type,
                target_id,
                json.dumps(detail, ensure_ascii=False),
                now_iso(),
            ),
        )


class PaperRepository:
    def __init__(self, db: Database):
        self.db = db

    # --- PaperProject CRUD ---

    def create_project(
        self,
        *,
        project_id: str,
        title: str,
        subject: str,
        grade: str,
        created_by: int,
    ) -> None:
        ts = now_iso()
        self.db.execute(
            """
            INSERT INTO paper_projects(
              project_id, title, subject, grade, status, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'draft', ?, ?, ?)
            """,
            (project_id, title, subject, grade, created_by, ts, ts),
        )

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM paper_projects WHERE project_id=?", (project_id,)
        )
        return dict(row) if row else None

    def list_projects(self, *, limit: int, created_by: int | None = None) -> list[dict[str, Any]]:
        if created_by is None:
            rows = self.db.query_all(
                "SELECT * FROM paper_projects ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        else:
            rows = self.db.query_all(
                "SELECT * FROM paper_projects WHERE created_by=? ORDER BY created_at DESC LIMIT ?",
                (created_by, limit),
            )
        return [dict(row) for row in rows]

    def _update_project_status_internal(
        self,
        project_id: str,
        *,
        status: str,
        error_message: str | None = None,
        paper_page_count: int | None = None,
        answer_key_source: str | None = None,
    ) -> None:
        """Private status writer. Use ProjectStateService.transition() instead. See ADR-0006."""
        parts: list[str] = ["status=?", "updated_at=?"]
        params: list[Any] = [status, now_iso()]
        if error_message is not None:
            parts.append("error_message=?")
            params.append(error_message[:4000])
        elif status != "error":
            parts.append("error_message=NULL")
        if paper_page_count is not None:
            parts.append("paper_page_count=?")
            params.append(paper_page_count)
        if answer_key_source is not None:
            parts.append("answer_key_source=?")
            params.append(answer_key_source)
        params.append(project_id)
        self.db.execute(
            f"UPDATE paper_projects SET {', '.join(parts)} WHERE project_id=?",
            tuple(params),
        )

    def increment_project_student_count(self, project_id: str) -> None:
        self.db.execute(
            "UPDATE paper_projects SET student_count=student_count+1, updated_at=? WHERE project_id=?",
            (now_iso(), project_id),
        )

    def count_active_jobs_for_project(self, project_id: str) -> int:
        """Return the number of queued or running jobs for a given paper project."""
        row = self.db.query_one(
            "SELECT COUNT(*) AS cnt FROM analysis_jobs WHERE paper_project_id=? AND status IN ('queued', 'running')",
            (project_id,),
        )
        return int(row["cnt"]) if row else 0

    def delete_project(self, project_id: str) -> bool:
        """Delete a paper project and all associated data. Returns True if deleted."""
        existing = self.get_project(project_id)
        if existing is None:
            return False
        self.db.execute("DELETE FROM paper_question_images WHERE project_id=?", (project_id,))
        self.db.execute("DELETE FROM paper_project_files WHERE project_id=?", (project_id,))
        self.db.execute("DELETE FROM paper_questions WHERE project_id=?", (project_id,))
        self.db.execute("DELETE FROM paper_reference_answers WHERE project_id=?", (project_id,))
        self.db.execute("DELETE FROM paper_projects WHERE project_id=?", (project_id,))
        return True

    # --- PaperProjectFiles ---

    def add_project_file(
        self,
        *,
        project_id: str,
        category: str,
        file_name: str,
        local_path: str,
        content_type: str | None,
        size_bytes: int,
    ) -> int:
        cur = self.db.execute(
            """
            INSERT INTO paper_project_files(
              project_id, category, file_name, local_path, content_type, size_bytes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, category, file_name, local_path, content_type, size_bytes, now_iso()),
        )
        return int(cur.lastrowid)

    def list_project_files(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            "SELECT * FROM paper_project_files WHERE project_id=? ORDER BY id ASC",
            (project_id,),
        )
        return [dict(row) for row in rows]

    # --- PaperQuestions ---

    def save_questions(
        self,
        *,
        project_id: str,
        questions: list[dict[str, Any]],
    ) -> None:
        ts = now_iso()
        for idx, q in enumerate(questions):
            qid = str(q.get("question_id") or f"Q{idx + 1}")
            qtype = str(q.get("question_type") or "unknown")
            content = str(q.get("content") or q.get("problem_text") or "")
            max_score = q.get("max_score")
            if isinstance(max_score, str):
                try:
                    max_score = float(max_score)
                except (ValueError, TypeError):
                    max_score = None
            page_index = q.get("page_index") or q.get("paper_page_index")
            if isinstance(page_index, str):
                try:
                    page_index = int(page_index)
                except (ValueError, TypeError):
                    page_index = None
            skill_tags = json.dumps(q.get("skill_tags") or [], ensure_ascii=False)
            confidence = q.get("confidence")
            if isinstance(confidence, str):
                try:
                    confidence = float(confidence)
                except (ValueError, TypeError):
                    confidence = None
            raw_json = json.dumps(q.get("raw", q), ensure_ascii=False)
            sort_order = idx + 1
            parent_qid = q.get("parent_question_id")
            self.db.execute(
                """
                INSERT OR REPLACE INTO paper_questions(
                  project_id, question_id, question_no, question_type, content,
                  max_score, page_index, skill_tags, confidence, raw_json,
                  sort_order, parent_question_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id, qid, str(q.get("question_no", "")), qtype,
                    content, max_score, page_index, skill_tags, confidence,
                    raw_json, sort_order, parent_qid, ts, ts,
                ),
            )

    def get_questions(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            "SELECT * FROM paper_questions WHERE project_id=? ORDER BY sort_order ASC",
            (project_id,),
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["skill_tags"] = _decode_json(str(item.get("skill_tags", "[]")), [])
            item["raw"] = _decode_json(str(item.get("raw_json", "{}")), {})
            result.append(item)
        return result

    # --- PaperReferenceAnswers ---

    def save_reference_answers(
        self,
        *,
        project_id: str,
        answers: list[dict[str, Any]],
    ) -> None:
        ts = now_iso()
        for a in answers:
            qid = str(a.get("question_id") or "")
            if not qid:
                continue
            answer_text = a.get("answer_text")
            if not isinstance(answer_text, str) or not answer_text.strip():
                answer_text = a.get("reference_answer_text")
            final_answer = a.get("final_answer")
            if not isinstance(final_answer, str) or not final_answer.strip():
                final_answer = a.get("reference_final_answer")
            steps = a.get("steps")
            if not isinstance(steps, list) or not steps:
                steps = a.get("reference_steps")
            if not isinstance(steps, list):
                steps = []
            analysis = a.get("analysis")
            if not isinstance(analysis, str) or not analysis.strip():
                analysis = ""
            raw = a.get("raw")
            if not isinstance(raw, dict) or not raw:
                raw = dict(a)
            self.db.execute(
                """
                INSERT OR REPLACE INTO paper_reference_answers(
                  project_id, question_id, answer_text, final_answer, steps,
                  analysis, source, confidence, warnings, raw_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id, qid,
                    str(answer_text or ""),
                    final_answer,
                    json.dumps(steps, ensure_ascii=False),
                    analysis,
                    str(a.get("source", "uploaded")),
                    a.get("confidence"),
                    json.dumps(a.get("warnings", []), ensure_ascii=False),
                    json.dumps(raw, ensure_ascii=False),
                    ts,
                ),
            )

    def get_reference_answers(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            "SELECT * FROM paper_reference_answers WHERE project_id=? ORDER BY id ASC",
            (project_id,),
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["steps"] = _decode_json(str(item.get("steps", "[]")), [])
            item["warnings"] = _decode_json(str(item.get("warnings", "[]")), [])
            item["raw"] = _decode_json(str(item.get("raw_json", "{}")), {})
            result.append(item)
        return result

    def update_job_paper_project_id(self, job_id: str, project_id: str) -> None:
        self.db.execute(
            "UPDATE analysis_jobs SET paper_project_id=? WHERE job_id=?",
            (project_id, job_id),
        )

    def update_job_payload(self, job_id: str, payload: dict[str, Any]) -> None:
        self.db.execute(
            "UPDATE analysis_jobs SET payload_json=? WHERE job_id=?",
            (json.dumps(payload, ensure_ascii=False), job_id),
        )

    def create_paper_analysis_job(
        self,
        *,
        job_id: str,
        student_id: str,
        payload: dict[str, Any],
        created_by: int,
        paper_project_id: str,
    ) -> None:
        """Create an analysis job with full payload in one atomic write."""
        ts = now_iso()
        self.db.execute(
            """
            INSERT INTO analysis_jobs(
              job_id, student_id, input_mode, status, payload_json, stage_logs_json,
              created_by, attempt_count, error_message, created_at, updated_at,
              paper_project_id
            ) VALUES (?, ?, ?, 'queued', ?, '[]', ?, 0, NULL, ?, ?, ?)
            """,
            (job_id, student_id, str(payload.get("input_mode", "")),
             json.dumps(payload, ensure_ascii=False),
             created_by, ts, ts, paper_project_id),
        )

    def update_project_data(self, project_id: str, **fields: Any) -> None:
        """Update JSON data columns on a paper project."""
        set_parts: list[str] = ["updated_at=?"]
        params: list[Any] = [now_iso()]
        extra_updates: dict[str, Any] = {}
        for key, value in fields.items():
            if key in {"score_review_data", "final_report_data"}:
                set_parts.append(f"{key}=?")
                params.append(json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value)
            elif key in {"generated_paper_path", "generated_paper_pdf_path", "generated_paper_error"}:
                extra_updates[key] = value
        if extra_updates:
            existing = self.get_project_extra(project_id) or {}
            existing.update(extra_updates)
            set_parts.append("extra_data=?")
            params.append(json.dumps(existing, ensure_ascii=False))
        params.append(project_id)
        self.db.execute(
            f"UPDATE paper_projects SET {', '.join(set_parts)} WHERE project_id=?",
            tuple(params),
        )

    def get_project_extra(self, project_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT extra_data FROM paper_projects WHERE project_id=?", (project_id,)
        )
        if row is None:
            return None
        raw = row["extra_data"]
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return {}
        return raw or {}

    def save_final_report(self, project_id: str, *, report_data: dict[str, Any]) -> None:
        ts = now_iso()
        self.db.execute(
            "UPDATE paper_projects SET final_report_data=?, updated_at=? WHERE project_id=?",
            (json.dumps(report_data, ensure_ascii=False), ts, project_id),
        )

    # --- PaperQuestionImages ---

    def save_question_image(
        self,
        *,
        project_id: str,
        question_id: str,
        file_id: int,
        page_index: int = 0,
        sort_order: int = 0,
    ) -> None:
        self.db.execute(
            "INSERT INTO paper_question_images(project_id, question_id, file_id, page_index, sort_order, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, question_id, file_id, page_index, sort_order, now_iso()),
        )

    def get_question_images(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.db.query_all(
            """SELECT pqi.*, ppf.file_name, ppf.local_path, ppf.content_type
               FROM paper_question_images pqi
               JOIN paper_project_files ppf ON pqi.file_id = ppf.id
               WHERE pqi.project_id=?
               ORDER BY pqi.sort_order ASC""",
            (project_id,),
        )
        return [dict(row) for row in rows]

    def delete_question_images(self, project_id: str) -> None:
        self.db.execute("DELETE FROM paper_question_images WHERE project_id=?", (project_id,))

    # --- MinerU State ---

    def update_mineru_state(self, project_id: str, state: dict[str, Any]) -> None:
        self.db.execute(
            "UPDATE paper_projects SET mineru_state=?, updated_at=? WHERE project_id=?",
            (json.dumps(state, ensure_ascii=False), now_iso(), project_id),
        )

    def get_mineru_state(self, project_id: str) -> dict[str, Any]:
        row = self.db.query_one(
            "SELECT mineru_state FROM paper_projects WHERE project_id=?", (project_id,)
        )
        if row is None:
            return {}
        raw = row[0]
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return {}
        return raw or {}

    def clear_mineru_state(self, project_id: str) -> None:
        self.update_mineru_state(project_id, {})

    def set_mineru_artifact_dir(self, project_id: str, artifact_dir: str) -> None:
        self.db.execute(
            "UPDATE paper_projects SET mineru_artifact_dir=?, updated_at=? WHERE project_id=?",
            (artifact_dir, now_iso(), project_id),
        )

    def get_mineru_artifact_dir(self, project_id: str) -> str | None:
        row = self.db.query_one(
            "SELECT mineru_artifact_dir FROM paper_projects WHERE project_id=?", (project_id,)
        )
        if row is None:
            return None
        val = row[0]
        return str(val) if val else None
