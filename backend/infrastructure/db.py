from __future__ import annotations

import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked_at TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS analysis_jobs (
  job_id TEXT PRIMARY KEY,
  student_id TEXT NOT NULL,
  input_mode TEXT NOT NULL,
  status TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  stage_logs_json TEXT NOT NULL DEFAULT '[]',
  created_by INTEGER NOT NULL,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  error_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  FOREIGN KEY(created_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS analysis_job_files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  category TEXT NOT NULL,
  file_name TEXT NOT NULL,
  local_path TEXT NOT NULL,
  content_type TEXT,
  size_bytes INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(job_id) REFERENCES analysis_jobs(job_id)
);

CREATE TABLE IF NOT EXISTS analysis_results (
  job_id TEXT PRIMARY KEY,
  result_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(job_id) REFERENCES analysis_jobs(job_id)
);

CREATE TABLE IF NOT EXISTS mastery_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_by INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(created_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS audit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor_user_id INTEGER,
  action TEXT NOT NULL,
  target_type TEXT,
  target_id TEXT,
  detail_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(actor_user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_analysis_jobs_status_created_at
ON analysis_jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_analysis_job_files_job_id
ON analysis_job_files(job_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at
ON audit_logs(created_at);

CREATE TABLE IF NOT EXISTS students (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id TEXT NOT NULL,
  name TEXT NOT NULL,
  grade TEXT NOT NULL DEFAULT '',
  created_by INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(created_by) REFERENCES users(id),
  UNIQUE(created_by, student_id)
);

CREATE TABLE IF NOT EXISTS paper_projects (
  project_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  subject TEXT NOT NULL DEFAULT '',
  grade TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'draft',
  student_count INTEGER NOT NULL DEFAULT 0,
  paper_page_count INTEGER NOT NULL DEFAULT 0,
  answer_key_source TEXT NOT NULL DEFAULT '',
  error_message TEXT,
  created_by INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(created_by) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS paper_project_files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id TEXT NOT NULL,
  category TEXT NOT NULL,
  file_name TEXT NOT NULL,
  local_path TEXT NOT NULL,
  content_type TEXT,
  size_bytes INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(project_id) REFERENCES paper_projects(project_id)
);

CREATE TABLE IF NOT EXISTS paper_questions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id TEXT NOT NULL,
  question_id TEXT NOT NULL,
  question_no TEXT NOT NULL DEFAULT '',
  question_type TEXT NOT NULL DEFAULT 'unknown',
  content TEXT NOT NULL DEFAULT '',
  max_score REAL,
  page_index INTEGER,
  skill_tags TEXT NOT NULL DEFAULT '[]',
  confidence REAL,
  raw_json TEXT NOT NULL DEFAULT '{}',
  sort_order INTEGER NOT NULL DEFAULT 0,
  parent_question_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT,
  FOREIGN KEY(project_id) REFERENCES paper_projects(project_id),
  UNIQUE(project_id, question_id)
);

CREATE TABLE IF NOT EXISTS paper_reference_answers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id TEXT NOT NULL,
  question_id TEXT NOT NULL,
  answer_text TEXT NOT NULL DEFAULT '',
  final_answer TEXT,
  steps TEXT NOT NULL DEFAULT '[]',
  analysis TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'uploaded',
  confidence REAL,
  warnings TEXT NOT NULL DEFAULT '[]',
  raw_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  FOREIGN KEY(project_id) REFERENCES paper_projects(project_id),
  UNIQUE(project_id, question_id)
);

CREATE TABLE IF NOT EXISTS paper_question_images (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id TEXT NOT NULL,
  question_id TEXT NOT NULL,
  file_id INTEGER NOT NULL,
  page_index INTEGER NOT NULL DEFAULT 0,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  FOREIGN KEY(project_id) REFERENCES paper_projects(project_id),
  FOREIGN KEY(file_id) REFERENCES paper_project_files(id)
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = RLock()
        with self._lock:
            self.conn.execute("PRAGMA journal_mode=WAL;")
            self.conn.execute("PRAGMA synchronous=NORMAL;")
            self.conn.executescript(SCHEMA_SQL)
            self._run_migrations()
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def _run_migrations(self) -> None:
        """Apply additive schema migrations."""
        cursor = self.conn.execute("PRAGMA table_info(analysis_jobs)")
        cols = {row[1] for row in cursor.fetchall()}
        if "paper_project_id" not in cols:
            self.conn.execute(
                "ALTER TABLE analysis_jobs ADD COLUMN paper_project_id TEXT "
                "REFERENCES paper_projects(project_id)"
            )
        # Migrations for paper_projects
        pp_cols_cursor = self.conn.execute("PRAGMA table_info(paper_projects)")
        pp_cols = {row[1] for row in pp_cols_cursor.fetchall()}
        if "score_review_data" not in pp_cols:
            try:
                self.conn.execute("ALTER TABLE paper_projects ADD COLUMN score_review_data TEXT DEFAULT '{}'")
            except Exception:
                pass
        if "final_report_data" not in pp_cols:
            try:
                self.conn.execute("ALTER TABLE paper_projects ADD COLUMN final_report_data TEXT DEFAULT '{}'")
            except Exception:
                pass
        # Add mineru_state column for MinerU extraction pipeline
        pp_cols2 = {row[1] for row in self.conn.execute("PRAGMA table_info(paper_projects)")}
        if "mineru_state" not in pp_cols2:
            try:
                self.conn.execute("ALTER TABLE paper_projects ADD COLUMN mineru_state TEXT DEFAULT '{}'")
            except Exception:
                pass
        # Persist mineru artifact directory path so review endpoints can find it
        pp_cols3 = {row[1] for row in self.conn.execute("PRAGMA table_info(paper_projects)")}
        if "mineru_artifact_dir" not in pp_cols3:
            try:
                self.conn.execute("ALTER TABLE paper_projects ADD COLUMN mineru_artifact_dir TEXT")
            except Exception:
                pass
        if "updated_at" not in cols:
            try:
                self.conn.execute(
                    "ALTER TABLE paper_questions ADD COLUMN updated_at TEXT"
                )
            except Exception:
                pass
        # Migration for analysis field in paper_reference_answers
        pra_cols = {row[1] for row in self.conn.execute("PRAGMA table_info(paper_reference_answers)")}
        if "analysis" not in pra_cols:
            try:
                self.conn.execute("ALTER TABLE paper_reference_answers ADD COLUMN analysis TEXT NOT NULL DEFAULT ''")
            except Exception:
                pass

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def query_one(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self._lock:
            cur = self.conn.execute(sql, params)
            row = cur.fetchone()
            return row

    def query_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self.conn.execute(sql, params)
            return cur.fetchall()

    def with_lock(self):
        return self._lock
