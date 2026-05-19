from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Response, current_app, jsonify, request

from backend.app_context import AppContext
from backend.application.auth_service import AuthUser


class ApiError(Exception):
    def __init__(self, status_code: int, message: str, code: str = "BAD_REQUEST"):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.code = code


INTAKE_FILE_FIELDS = (
    "paper_files",
    "answer_sheet_files",
    "combined_files",
    "answer_key_files",
)
INTAKE_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".pdf"}
INTAKE_MODE_OPTIONS = {"paper_answer_with_key", "paper_answer_auto_key", "paper_same_page", "pre_split_questions"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_response(data: Any = None, status_code: int = 200) -> Response:
    # Pass through data that already has ok/error keys (legacy routes)
    if isinstance(data, dict) and ("ok" in data or "error" in data):
        return jsonify(data), status_code
    payload: dict[str, Any] = {"ok": True}
    if data is not None:
        payload["data"] = data
    return jsonify(payload), status_code


def _json_list_response(items: list[Any], total: int | None = None, status_code: int = 200) -> Response:
    data: dict[str, Any] = {"items": items}
    if total is not None:
        data["total"] = total
    return _json_response(data, status_code=status_code)


def _parse_json_body() -> dict[str, Any]:
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(status_code=400, message="request json must be object")
    return body


def _parse_json_list(raw: str | None, field: str) -> list[dict[str, Any]]:
    if raw is None or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ApiError(status_code=400, message=f"{field} must be valid JSON") from exc
    if not isinstance(parsed, list):
        raise ApiError(status_code=400, message=f"{field} must be list")
    return [item for item in parsed if isinstance(item, dict)]


def _coerce_dict_list(value: Any, field: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, str):
        if not value.strip():
            return []
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ApiError(status_code=400, message=f"{field} must be valid JSON array") from exc
    if not isinstance(value, list):
        raise ApiError(status_code=400, message=f"{field} must be list")
    return [item for item in value if isinstance(item, dict)]


def _normalize_mode(value: Any, *, field: str = "manual_mode") -> str | None:
    if value is None:
        return None
    mode = str(value).strip()
    if not mode:
        return None
    if mode not in INTAKE_MODE_OPTIONS:
        raise ApiError(status_code=400, message=f"{field} is invalid")
    return mode


def _read_uploads(field_name: str) -> list[tuple[str, bytes, str | None]]:
    files = request.files.getlist(field_name)
    output: list[tuple[str, bytes, str | None]] = []
    for item in files:
        content = item.read()
        output.append((item.filename or "upload.bin", content, item.mimetype))
    return output


def _get_ctx() -> AppContext:
    ctx = current_app.config.get("ctx")
    if not isinstance(ctx, AppContext):
        raise ApiError(status_code=500, message="app context not ready")
    return ctx


def _get_intake_store() -> "IntakeDraftStore":
    store = current_app.config.get("intake_store")
    if store is None:
        raise ApiError(status_code=500, message="intake store not ready")
    return store


def _extract_bearer_token() -> str:
    header = request.headers.get("Authorization", "")
    parts = header.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise ApiError(status_code=401, message="missing bearer token")
    return parts[1].strip()


def _require_user(*roles: str) -> tuple[AuthUser, str]:
    ctx = _get_ctx()
    token = _extract_bearer_token()
    user = ctx.auth_service.get_user_by_token(token)
    if user is None:
        raise ApiError(status_code=401, message="invalid or expired token")
    if roles and user.role not in set(roles):
        raise ApiError(status_code=403, message="forbidden")
    return user, token


def _require_job_access(user: AuthUser, job_id: str) -> dict[str, Any]:
    ctx = _get_ctx()
    try:
        job = ctx.analysis_service.get_job(job_id)
    except KeyError as exc:
        raise ApiError(status_code=404, message=str(exc)) from exc
    if user.role != "admin" and int(job["created_by"]) != user.id:
        raise ApiError(status_code=403, message="forbidden")
    return job


def _require_draft_access(*, user: AuthUser, draft_id: str) -> dict[str, Any]:
    store = _get_intake_store()
    draft = store.get(draft_id)
    if draft is None:
        raise ApiError(status_code=404, message="intake draft not found")
    if user.role != "admin" and int(draft.get("created_by") or -1) != user.id:
        raise ApiError(status_code=403, message="forbidden")
    return draft


def _parse_student_ids(body: dict[str, Any]) -> list[str]:
    raw_value = body.get("student_ids")
    items: list[str] = []
    if isinstance(raw_value, list):
        items = [str(item).strip() for item in raw_value]
    elif isinstance(raw_value, str):
        normalized = raw_value.replace("\r", "\n").replace("\uff0c", ",").replace("\uff1b", ",")
        parts: list[str] = []
        for block in normalized.split("\n"):
            for piece in block.split(","):
                parts.append(piece)
        items = [piece.strip() for piece in parts]
    else:
        raise ApiError(status_code=400, message="student_ids is required")
    student_ids = [item for item in items if item]
    if not student_ids:
        raise ApiError(status_code=400, message="student_ids is empty")
    duplicated_set: set[str] = set()
    seen: set[str] = set()
    for item in student_ids:
        if item in seen:
            duplicated_set.add(item)
            continue
        seen.add(item)
    duplicated = sorted(duplicated_set)
    if duplicated:
        raise ApiError(status_code=400, message=f"student_ids has duplicates: {', '.join(duplicated[:5])}")
    return student_ids


def _extract_pre_split_questions_from_report(report: dict[str, Any]) -> list[dict[str, Any]]:
    source = report.get("structured_questions_full")
    if not isinstance(source, list) or not source:
        source = report.get("question_analysis")
    if not isinstance(source, list) or not source:
        raise ApiError(status_code=400, message="template report has no question list for pre_split conversion")

    question_by_id: dict[str, dict[str, Any]] = {}
    for item in source:
        if not isinstance(item, dict):
            continue
        question_id = str(item.get("question_id") or "").strip()
        if not question_id:
            continue
        converted: dict[str, Any] = {"question_id": question_id}
        question_type = str(item.get("question_type") or "").strip()
        if question_type:
            converted["question_type"] = question_type
        sub_questions = item.get("sub_questions")
        if isinstance(sub_questions, list):
            normalized_sub = [sub for sub in sub_questions if isinstance(sub, dict)]
            if normalized_sub:
                converted["sub_questions"] = normalized_sub
        question_by_id[question_id] = converted

    questions = sorted(question_by_id.values(), key=lambda item: str(item.get("question_id") or ""))
    if not questions:
        raise ApiError(status_code=400, message="template report question list is empty")
    return questions


class IntakeDraftStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._drafts: dict[str, dict[str, Any]] = {}

    def create(
        self,
        *,
        created_by: int,
        student_id: str,
        vision_profile: str | None,
        text_profile: str | None,
        manual_mode: str | None,
        pre_split_questions: list[dict[str, Any]],
        selected_answer_blocks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        draft_id = uuid.uuid4().hex
        now = _utc_now_iso()
        with self._lock:
            draft = {
                "draft_id": draft_id,
                "created_by": created_by,
                "student_id": student_id,
                "vision_profile": vision_profile,
                "text_profile": text_profile,
                "manual_mode": manual_mode,
                "pre_split_questions": pre_split_questions,
                "selected_answer_blocks": selected_answer_blocks,
                "upload_groups": {field: [] for field in INTAKE_FILE_FIELDS},
                "detected_mode": None,
                "readiness": "needs_input",
                "missing_requirements": [],
                "conflicts": [],
                "suggestions": [],
                "created_at": now,
                "updated_at": now,
            }
            self._drafts[draft_id] = draft
            return draft

    def get(self, draft_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._drafts.get(draft_id)

    def touch(self, draft_id: str) -> None:
        with self._lock:
            draft = self._drafts.get(draft_id)
            if draft is not None:
                draft["updated_at"] = _utc_now_iso()

    def update_fields(self, draft_id: str, *, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            draft = self._drafts.get(draft_id)
            if draft is None:
                raise KeyError("draft not found")
            if "student_id" in payload and isinstance(payload["student_id"], str):
                draft["student_id"] = payload["student_id"].strip()
            if "vision_profile" in payload:
                value = payload["vision_profile"]
                if isinstance(value, str):
                    draft["vision_profile"] = value.strip() or None
                else:
                    draft["vision_profile"] = None
            if "text_profile" in payload:
                value = payload["text_profile"]
                if isinstance(value, str):
                    draft["text_profile"] = value.strip() or None
                else:
                    draft["text_profile"] = None
            if "manual_mode" in payload:
                draft["manual_mode"] = payload["manual_mode"]
            if "pre_split_questions" in payload:
                draft["pre_split_questions"] = payload["pre_split_questions"]
            if "selected_answer_blocks" in payload:
                draft["selected_answer_blocks"] = payload["selected_answer_blocks"]
            draft["updated_at"] = _utc_now_iso()
            return draft

    def add_files(
        self,
        draft_id: str,
        *,
        upload_groups: dict[str, list[tuple[str, bytes, str | None]]],
        replace: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            draft = self._drafts.get(draft_id)
            if draft is None:
                raise KeyError("draft not found")
            groups: dict[str, list[tuple[str, bytes, str | None]]] = draft["upload_groups"]
            if replace:
                for key in INTAKE_FILE_FIELDS:
                    groups[key] = []
            for key, values in upload_groups.items():
                if key not in groups:
                    continue
                groups[key].extend(values)
            draft["updated_at"] = _utc_now_iso()
            return draft

    def replace_analysis(
        self,
        draft_id: str,
        *,
        detected_mode: str | None,
        readiness: str,
        missing_requirements: list[dict[str, str]],
        conflicts: list[dict[str, str]],
        suggestions: list[str],
    ) -> dict[str, Any]:
        with self._lock:
            draft = self._drafts.get(draft_id)
            if draft is None:
                raise KeyError("draft not found")
            draft["detected_mode"] = detected_mode
            draft["readiness"] = readiness
            draft["missing_requirements"] = missing_requirements
            draft["conflicts"] = conflicts
            draft["suggestions"] = suggestions
            draft["updated_at"] = _utc_now_iso()
            return draft

    def reset_for_continuous_submit(self, draft_id: str) -> dict[str, Any]:
        with self._lock:
            draft = self._drafts.get(draft_id)
            if draft is None:
                raise KeyError("draft not found")
            draft["student_id"] = ""
            draft["upload_groups"] = {field: [] for field in INTAKE_FILE_FIELDS}
            draft["detected_mode"] = draft.get("manual_mode")
            draft["readiness"] = "needs_input"
            draft["missing_requirements"] = []
            draft["conflicts"] = []
            draft["suggestions"] = ["\u5df2\u4fdd\u7559\u573a\u666f\u548c\u9ad8\u7ea7\u8bbe\u7f6e\uff0c\u8bf7\u4e0a\u4f20\u4e0b\u4e00\u4f4d\u5b66\u751f\u7684\u6587\u4ef6\u540e\u7ee7\u7eed\u63d0\u4ea4\u3002"]
            draft["updated_at"] = _utc_now_iso()
            return draft


def _draft_file_stats(draft: dict[str, Any]) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    groups = draft.get("upload_groups")
    if not isinstance(groups, dict):
        return stats
    for key in INTAKE_FILE_FIELDS:
        values = groups.get(key) or []
        names = [str(item[0]) for item in values[:5] if isinstance(item, tuple) and item]
        stats[key] = {"count": len(values), "sample_names": names}
    return stats


def _detect_mode_from_draft(draft: dict[str, Any]) -> str | None:
    groups = draft.get("upload_groups") if isinstance(draft.get("upload_groups"), dict) else {}
    paper_count = len(groups.get("paper_files") or [])
    answer_sheet_count = len(groups.get("answer_sheet_files") or [])
    combined_count = len(groups.get("combined_files") or [])
    answer_key_count = len(groups.get("answer_key_files") or [])
    pre_split = draft.get("pre_split_questions")
    if isinstance(pre_split, list) and len(pre_split) > 0:
        return "pre_split_questions"
    if combined_count > 0 and paper_count == 0 and answer_sheet_count == 0:
        return "paper_same_page"
    if paper_count > 0 and answer_sheet_count > 0 and answer_key_count > 0:
        return "paper_answer_with_key"
    if paper_count > 0 and answer_sheet_count > 0 and answer_key_count == 0:
        return "paper_answer_auto_key"
    return None


def _make_issue(*, code: str, message: str, fix: str) -> dict[str, str]:
    return {"code": code, "message": message, "fix": fix}


def _analyze_draft(draft: dict[str, Any]) -> dict[str, Any]:
    manual_mode = draft.get("manual_mode")
    auto_mode = _detect_mode_from_draft(draft)
    detected_mode = manual_mode if isinstance(manual_mode, str) and manual_mode else auto_mode

    groups = draft.get("upload_groups") if isinstance(draft.get("upload_groups"), dict) else {}
    counts = {key: len(groups.get(key) or []) for key in INTAKE_FILE_FIELDS}
    missing_requirements: list[dict[str, str]] = []
    conflicts: list[dict[str, str]] = []
    suggestions: list[str] = []

    allowed_message = "\u652f\u6301\u56fe\u7247(PNG/JPG/WebP/BMP/TIFF)\u4e0e PDF\u3002"
    for field in INTAKE_FILE_FIELDS:
        for item in groups.get(field) or []:
            if not isinstance(item, tuple) or not item:
                continue
            file_name = str(item[0])
            ext = Path(file_name).suffix.lower()
            if ext and ext not in INTAKE_ALLOWED_EXTENSIONS:
                conflicts.append(
                    _make_issue(
                        code="unsupported_file_type",
                        message=f"{file_name} \u7c7b\u578b\u6682\u4e0d\u652f\u6301\u3002",
                        fix=allowed_message,
                    )
                )

    image_count = 0
    has_pdf = False
    for field in INTAKE_FILE_FIELDS:
        for item in groups.get(field) or []:
            if not isinstance(item, tuple) or not item:
                continue
            ext = Path(str(item[0])).suffix.lower()
            if ext == ".pdf":
                has_pdf = True
            if ext in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}:
                image_count += 1
    if has_pdf:
        suggestions.append("\u68c0\u6d4b\u5230 PDF \u626b\u63cf\u4ef6\uff0c\u7cfb\u7edf\u4f1a\u81ea\u52a8\u62c6\u9875\u5904\u7406\u3002")
    if image_count >= 2:
        suggestions.append("\u82e5\u624b\u673a\u62cd\u7167\u987a\u5e8f\u4e0d\u786e\u5b9a\uff0c\u8bf7\u5728\u63d0\u4ea4\u524d\u786e\u8ba4\u4e0a\u4f20\u987a\u5e8f\u3002")

    if detected_mode is None:
        if sum(counts.values()) == 0:
            missing_requirements.append(
                _make_issue(
                    code="missing_files",
                    message="\u5c1a\u672a\u4e0a\u4f20\u4efb\u4f55\u6587\u4ef6\u3002",
                    fix="\u8bf7\u5148\u4e0a\u4f20\u8bd5\u5377\u3001\u7b54\u9898\u5361\u6216\u540c\u5377\u4f5c\u7b54\u6587\u4ef6\u3002",
                )
            )
            suggestions.append("\u53ef\u5148\u9009\u62e9\u201c\u8bd5\u5377+\u7b54\u9898\u5361\uff08\u81ea\u52a8\u751f\u6210\u6807\u51c6\u7b54\u6848\uff09\u201d\u4f5c\u4e3a\u8d77\u6b65\u573a\u666f\u3002")
        else:
            conflicts.append(
                _make_issue(
                    code="mode_not_determined",
                    message="\u5f53\u524d\u4e0a\u4f20\u7ec4\u5408\u65e0\u6cd5\u81ea\u52a8\u5224\u5b9a\u573a\u666f\u3002",
                    fix="\u53ef\u5728\u6b65\u9aa4 1 \u624b\u52a8\u9009\u62e9\u573a\u666f\uff0c\u6216\u6309\u5efa\u8bae\u8865\u9f50/\u79fb\u9664\u6587\u4ef6\u540e\u91cd\u8bd5\u68c0\u67e5\u3002",
                )
            )
            if counts["combined_files"] > 0 and (counts["paper_files"] > 0 or counts["answer_sheet_files"] > 0):
                suggestions.append("\u68c0\u6d4b\u5230\u201c\u540c\u5377\u4f5c\u7b54\u6587\u4ef6\u201d\u548c\u201c\u8bd5\u5377/\u7b54\u9898\u5361\u201d\u6df7\u4f20\uff0c\u5efa\u8bae\u53ea\u4fdd\u7559\u4e00\u79cd\u65b9\u6848\u3002")

    if detected_mode == "paper_answer_with_key":
        if counts["paper_files"] == 0:
            missing_requirements.append(
                _make_issue(code="missing_paper_files", message="\u7f3a\u5c11\u8bd5\u5377\u6587\u4ef6\u3002", fix="\u4e0a\u4f20 `paper_files`\u3002")
            )
        if counts["answer_sheet_files"] == 0:
            missing_requirements.append(
                _make_issue(code="missing_answer_sheet_files", message="\u7f3a\u5c11\u7b54\u9898\u5361\u6587\u4ef6\u3002", fix="\u4e0a\u4f20 `answer_sheet_files`\u3002")
            )
        if counts["answer_key_files"] == 0:
            missing_requirements.append(
                _make_issue(code="missing_answer_key_files", message="\u7f3a\u5c11\u6807\u51c6\u7b54\u6848\u6587\u4ef6\u3002", fix="\u4e0a\u4f20 `answer_key_files`\uff0c\u6216\u6539\u4e3a\u201c\u81ea\u52a8\u751f\u6210\u6807\u51c6\u7b54\u6848\u201d\u573a\u666f\u3002")
            )
        if counts["combined_files"] > 0:
            conflicts.append(
                _make_issue(code="combined_conflict", message="\u5f53\u524d\u573a\u666f\u4e0d\u9700\u8981\u540c\u5377\u4f5c\u7b54\u6587\u4ef6\u3002", fix="\u79fb\u9664 `combined_files` \u6216\u5207\u6362\u4e3a\u201c\u540c\u5377\u4f5c\u7b54\u201d\u573a\u666f\u3002")
            )

    if detected_mode == "paper_answer_auto_key":
        if counts["paper_files"] == 0:
            missing_requirements.append(
                _make_issue(code="missing_paper_files", message="\u7f3a\u5c11\u8bd5\u5377\u6587\u4ef6\u3002", fix="\u4e0a\u4f20 `paper_files`\u3002")
            )
        if counts["answer_sheet_files"] == 0:
            missing_requirements.append(
                _make_issue(code="missing_answer_sheet_files", message="\u7f3a\u5c11\u7b54\u9898\u5361\u6587\u4ef6\u3002", fix="\u4e0a\u4f20 `answer_sheet_files`\u3002")
            )
        if counts["answer_key_files"] > 0:
            conflicts.append(
                _make_issue(code="answer_key_not_needed", message="\u81ea\u52a8\u751f\u6210\u6807\u51c6\u7b54\u6848\u573a\u666f\u4e0d\u5e94\u4e0a\u4f20\u6807\u51c6\u7b54\u6848\u6587\u4ef6\u3002", fix="\u79fb\u9664 `answer_key_files` \u6216\u5207\u6362\u4e3a\u201c\u542b\u6807\u51c6\u7b54\u6848\u201d\u573a\u666f\u3002")
            )
        if counts["combined_files"] > 0:
            conflicts.append(
                _make_issue(code="combined_conflict", message="\u5f53\u524d\u573a\u666f\u4e0d\u9700\u8981\u540c\u5377\u4f5c\u7b54\u6587\u4ef6\u3002", fix="\u79fb\u9664 `combined_files` \u6216\u5207\u6362\u4e3a\u201c\u540c\u5377\u4f5c\u7b54\u201d\u573a\u666f\u3002")
            )
        suggestions.append("\u7cfb\u7edf\u5c06\u6839\u636e\u8bd5\u5377\u4e0e\u4f5c\u7b54\u81ea\u52a8\u751f\u6210\u6807\u51c6\u7b54\u6848\u3002")

    if detected_mode == "paper_same_page":
        if counts["combined_files"] == 0:
            missing_requirements.append(
                _make_issue(code="missing_combined_files", message="\u7f3a\u5c11\u540c\u5377\u4f5c\u7b54\u6587\u4ef6\u3002", fix="\u4e0a\u4f20 `combined_files`\u3002")
            )
        if counts["paper_files"] > 0 or counts["answer_sheet_files"] > 0:
            conflicts.append(
                _make_issue(code="same_page_conflict", message="\u540c\u5377\u4f5c\u7b54\u573a\u666f\u4e0d\u5e94\u518d\u4e0a\u4f20\u8bd5\u5377/\u7b54\u9898\u5361\u3002", fix="\u4ec5\u4fdd\u7559 `combined_files`\uff0c\u5982\u6709\u6807\u51c6\u7b54\u6848\u53ef\u989d\u5916\u4fdd\u7559 `answer_key_files`\u3002")
            )

    if detected_mode == "pre_split_questions":
        if counts["answer_sheet_files"] == 0:
            missing_requirements.append(
                _make_issue(code="missing_answer_sheet_files", message="\u7f3a\u5c11\u7b54\u9898\u5361\u6587\u4ef6\u3002", fix="\u4e0a\u4f20 `answer_sheet_files`\u3002")
            )
        pre_split = draft.get("pre_split_questions")
        if not isinstance(pre_split, list) or len(pre_split) == 0:
            missing_requirements.append(
                _make_issue(code="missing_pre_split_questions", message="\u7f3a\u5c11\u624b\u52a8\u5207\u9898 JSON\u3002", fix="\u586b\u5199 `pre_split_questions`\uff08JSON \u6570\u7ec4\uff09\u3002")
            )
        if counts["paper_files"] > 0 or counts["combined_files"] > 0:
            conflicts.append(
                _make_issue(code="pre_split_conflict", message="\u624b\u52a8\u5207\u9898\u573a\u666f\u65e0\u9700\u8bd5\u5377\u6587\u4ef6\u6216\u540c\u5377\u4f5c\u7b54\u6587\u4ef6\u3002", fix="\u4fdd\u7559 `answer_sheet_files`\uff08\u53ef\u9009 `answer_key_files`\uff09\u5e76\u79fb\u9664\u5176\u4f59\u6587\u4ef6\u3002")
            )

    if manual_mode and auto_mode and manual_mode != auto_mode:
        suggestions.append(f"\u7cfb\u7edf\u81ea\u52a8\u5224\u5b9a\u4e3a `{auto_mode}`\uff0c\u5f53\u524d\u5df2\u6309\u4f60\u624b\u52a8\u9009\u62e9\u7684 `{manual_mode}` \u6267\u884c\u3002")

    dedup_suggestions = list(dict.fromkeys(suggestions))
    if conflicts:
        readiness = "conflict"
    elif missing_requirements:
        readiness = "needs_input"
    else:
        readiness = "ready"
    return {
        "detected_mode": detected_mode,
        "readiness": readiness,
        "missing_requirements": missing_requirements,
        "conflicts": conflicts,
        "suggestions": dedup_suggestions,
    }


def _serialize_draft(draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "draft_id": draft.get("draft_id"),
        "student_id": draft.get("student_id"),
        "vision_profile": draft.get("vision_profile"),
        "text_profile": draft.get("text_profile"),
        "manual_mode": draft.get("manual_mode"),
        "detected_mode": draft.get("detected_mode"),
        "readiness": draft.get("readiness"),
        "missing_requirements": draft.get("missing_requirements") or [],
        "conflicts": draft.get("conflicts") or [],
        "suggestions": draft.get("suggestions") or [],
        "pre_split_questions": draft.get("pre_split_questions") or [],
        "selected_answer_blocks": draft.get("selected_answer_blocks") or [],
        "file_stats": _draft_file_stats(draft),
        "created_at": draft.get("created_at"),
        "updated_at": draft.get("updated_at"),
    }
