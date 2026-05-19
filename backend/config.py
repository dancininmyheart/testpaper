from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    text = value.strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


@dataclass(frozen=True)
class AppSettings:
    app_db_path: Path
    storage_root: Path
    llm_config_path: Path
    keyword_path: Path
    mastery_db_path: Path
    session_ttl_hours: int
    worker_poll_sec: float
    worker_enabled: bool
    demo_mock_mode: bool
    default_admin_username: str
    default_admin_password: str
    default_teacher_username: str
    default_teacher_password: str
    cors_allow_origins: list[str]

    @classmethod
    def load(cls) -> "AppSettings":
        app_db_path = Path(os.getenv("APP_DB_PATH", "outputs/platform/app.db"))
        storage_root = Path(os.getenv("APP_STORAGE_ROOT", "outputs/platform/storage"))
        llm_config_path = Path(os.getenv("LLM_CONFIG_PATH", "llm_config.json"))
        keyword_path = Path(os.getenv("KEYWORD_PATH", "key_word.json"))
        mastery_db_path = Path(os.getenv("MASTERY_DB_PATH", "mastery.db"))
        session_ttl_hours = int(os.getenv("SESSION_TTL_HOURS", "12"))
        worker_poll_sec = float(os.getenv("WORKER_POLL_SEC", "2.0"))
        worker_enabled = _as_bool(os.getenv("WORKER_ENABLED"), True)
        demo_mock_mode = _as_bool(os.getenv("DEMO_MOCK_MODE"), True)
        default_admin_username = os.getenv("DEFAULT_ADMIN_USERNAME", "admin").strip() or "admin"
        default_admin_password = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")
        default_teacher_username = os.getenv("DEFAULT_TEACHER_USERNAME", "teacher").strip() or "teacher"
        default_teacher_password = os.getenv("DEFAULT_TEACHER_PASSWORD", "teacher123")
        cors_raw = os.getenv("CORS_ALLOW_ORIGINS", "*")
        cors_allow_origins = [item.strip() for item in cors_raw.split(",") if item.strip()]
        if not cors_allow_origins:
            cors_allow_origins = ["*"]
        return cls(
            app_db_path=app_db_path,
            storage_root=storage_root,
            llm_config_path=llm_config_path,
            keyword_path=keyword_path,
            mastery_db_path=mastery_db_path,
            session_ttl_hours=max(1, session_ttl_hours),
            worker_poll_sec=max(0.5, worker_poll_sec),
            worker_enabled=worker_enabled,
            demo_mock_mode=demo_mock_mode,
            default_admin_username=default_admin_username,
            default_admin_password=default_admin_password,
            default_teacher_username=default_teacher_username,
            default_teacher_password=default_teacher_password,
            cors_allow_origins=cors_allow_origins,
        )

