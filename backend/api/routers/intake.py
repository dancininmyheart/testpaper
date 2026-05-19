from __future__ import annotations

from flask import Blueprint, Response, request

from backend.api.deps import (
    INTAKE_FILE_FIELDS,
    ApiError,
    _analyze_draft,
    _coerce_dict_list,
    _extract_pre_split_questions_from_report,
    _get_ctx,
    _get_intake_store,
    _json_response,
    _make_issue,
    _normalize_mode,
    _parse_json_body,
    _parse_student_ids,
    _read_uploads,
    _require_draft_access,
    _require_job_access,
    _require_user,
    _serialize_draft,
)
from backend.application.analysis_service import JobCreateInput

bp = Blueprint("intake", __name__)


@bp.post("/api/v1/intake/drafts")
def intake_create_draft() -> Response:
    ctx = _get_ctx()
    store = _get_intake_store()
    user, _ = _require_user("teacher", "admin")
    body = _parse_json_body()
    student_id = str(body.get("student_id") or "").strip()
    vision_profile = str(body.get("vision_profile") or "").strip() or None
    text_profile = str(body.get("text_profile") or "").strip() or None
    manual_mode = _normalize_mode(body.get("manual_mode"), field="manual_mode")
    pre_split_questions = _coerce_dict_list(body.get("pre_split_questions"), "pre_split_questions")
    selected_answer_blocks = _coerce_dict_list(body.get("selected_answer_blocks"), "selected_answer_blocks")
    draft = store.create(
        created_by=user.id,
        student_id=student_id,
        vision_profile=vision_profile,
        text_profile=text_profile,
        manual_mode=manual_mode,
        pre_split_questions=pre_split_questions,
        selected_answer_blocks=selected_answer_blocks,
    )
    analysis = _analyze_draft(draft)
    draft = store.replace_analysis(draft["draft_id"], **analysis)
    ctx.audit_service.log(
        actor_user_id=user.id,
        action="intake_draft_created",
        target_type="intake_draft",
        target_id=draft["draft_id"],
        detail={"manual_mode": manual_mode or "", "student_id": student_id},
    )
    return _json_response(_serialize_draft(draft), status_code=201)


@bp.get("/api/v1/intake/drafts/<draft_id>")
def intake_get_draft(draft_id: str) -> Response:
    store = _get_intake_store()
    user, _ = _require_user("teacher", "admin")
    _require_draft_access(user=user, draft_id=draft_id)
    analysis = _analyze_draft(store.get(draft_id) or {})
    draft = store.replace_analysis(draft_id, **analysis)
    return _json_response(_serialize_draft(draft))


@bp.post("/api/v1/intake/drafts/<draft_id>/files")
def intake_upload_files(draft_id: str) -> Response:
    store = _get_intake_store()
    user, _ = _require_user("teacher", "admin")
    _require_draft_access(user=user, draft_id=draft_id)
    replace = str(request.form.get("replace", "")).strip().lower() in {"1", "true", "yes", "y", "on"}
    groups = {field: _read_uploads(field) for field in INTAKE_FILE_FIELDS}
    file_count = sum(len(items) for items in groups.values())
    if file_count == 0:
        raise ApiError(status_code=400, message="no files uploaded")
    draft = store.add_files(draft_id, upload_groups=groups, replace=replace)
    analysis = _analyze_draft(draft)
    draft = store.replace_analysis(draft_id, **analysis)
    return _json_response(_serialize_draft(draft))


@bp.post("/api/v1/intake/drafts/<draft_id>/detect")
def intake_detect(draft_id: str) -> Response:
    store = _get_intake_store()
    user, _ = _require_user("teacher", "admin")
    _require_draft_access(user=user, draft_id=draft_id)
    body = _parse_json_body()
    payload: dict[str, object] = {}
    if "student_id" in body:
        payload["student_id"] = str(body.get("student_id") or "").strip()
    if "vision_profile" in body:
        payload["vision_profile"] = str(body.get("vision_profile") or "").strip() or None
    if "text_profile" in body:
        payload["text_profile"] = str(body.get("text_profile") or "").strip() or None
    if "manual_mode" in body:
        payload["manual_mode"] = _normalize_mode(body.get("manual_mode"), field="manual_mode")
    if "pre_split_questions" in body:
        payload["pre_split_questions"] = _coerce_dict_list(body.get("pre_split_questions"), "pre_split_questions")
    if "selected_answer_blocks" in body:
        payload["selected_answer_blocks"] = _coerce_dict_list(body.get("selected_answer_blocks"), "selected_answer_blocks")
    draft = store.update_fields(draft_id, payload=payload)
    analysis = _analyze_draft(draft)
    draft = store.replace_analysis(draft_id, **analysis)
    return _json_response(_serialize_draft(draft))


@bp.post("/api/v1/intake/drafts/<draft_id>/submit")
def intake_submit(draft_id: str) -> Response:
    ctx = _get_ctx()
    store = _get_intake_store()
    user, _ = _require_user("teacher", "admin")
    _require_draft_access(user=user, draft_id=draft_id)
    body = _parse_json_body()

    payload: dict[str, object] = {}
    if "manual_mode" in body:
        payload["manual_mode"] = _normalize_mode(body.get("manual_mode"), field="manual_mode")
    if "student_id" in body:
        payload["student_id"] = str(body.get("student_id") or "").strip()
    if "vision_profile" in body:
        payload["vision_profile"] = str(body.get("vision_profile") or "").strip() or None
    if "text_profile" in body:
        payload["text_profile"] = str(body.get("text_profile") or "").strip() or None
    if "pre_split_questions" in body:
        payload["pre_split_questions"] = _coerce_dict_list(body.get("pre_split_questions"), "pre_split_questions")
    if "selected_answer_blocks" in body:
        payload["selected_answer_blocks"] = _coerce_dict_list(body.get("selected_answer_blocks"), "selected_answer_blocks")
    if payload:
        store.update_fields(draft_id, payload=payload)

    analysis = _analyze_draft(store.get(draft_id) or {})
    draft = store.replace_analysis(draft_id, **analysis)
    if draft.get("readiness") != "ready":
        raise ApiError(status_code=400, message="draft is not ready")

    student_id = str(draft.get("student_id") or "").strip()
    if not student_id:
        raise ApiError(status_code=400, message="student_id is required")
    request_model = JobCreateInput(
        student_id=student_id,
        input_mode=str(draft.get("detected_mode") or ""),
        vision_profile=draft.get("vision_profile"),
        text_profile=draft.get("text_profile"),
        pre_split_questions=draft.get("pre_split_questions") or [],
        selected_answer_blocks=draft.get("selected_answer_blocks") or [],
    )
    upload_groups = {
        field: list((draft.get("upload_groups") or {}).get(field) or [])
        for field in INTAKE_FILE_FIELDS
    }
    try:
        job_id = ctx.analysis_service.create_job(
            request=request_model,
            upload_groups=upload_groups,
            created_by=user.id,
        )
    except ValueError as exc:
        raise ApiError(status_code=400, message=str(exc)) from exc

    continuous = bool(body.get("continuous", False))
    if continuous:
        draft = store.reset_for_continuous_submit(draft_id)
    else:
        analysis = _analyze_draft(store.get(draft_id) or {})
        draft = store.replace_analysis(draft_id, **analysis)

    ctx.audit_service.log(
        actor_user_id=user.id,
        action="intake_draft_submitted",
        target_type="intake_draft",
        target_id=draft_id,
        detail={"job_id": job_id, "input_mode": request_model.input_mode, "continuous": continuous},
    )
    return _json_response({"job_id": job_id, "status": "queued", "draft": _serialize_draft(draft)})


@bp.post("/api/v1/intake/drafts/<draft_id>/submit-batch")
def intake_submit_batch(draft_id: str) -> Response:
    ctx = _get_ctx()
    store = _get_intake_store()
    user, _ = _require_user("teacher", "admin")
    _require_draft_access(user=user, draft_id=draft_id)
    body = _parse_json_body()

    payload: dict[str, object] = {}
    if "manual_mode" in body:
        payload["manual_mode"] = _normalize_mode(body.get("manual_mode"), field="manual_mode")
    if "vision_profile" in body:
        payload["vision_profile"] = str(body.get("vision_profile") or "").strip() or None
    if "text_profile" in body:
        payload["text_profile"] = str(body.get("text_profile") or "").strip() or None
    if "pre_split_questions" in body:
        payload["pre_split_questions"] = _coerce_dict_list(body.get("pre_split_questions"), "pre_split_questions")
    if "selected_answer_blocks" in body:
        payload["selected_answer_blocks"] = _coerce_dict_list(body.get("selected_answer_blocks"), "selected_answer_blocks")
    if payload:
        store.update_fields(draft_id, payload=payload)

    draft = store.get(draft_id)
    if draft is None:
        raise ApiError(status_code=404, message="intake draft not found")
    student_ids = _parse_student_ids(body)
    upload_groups = draft.get("upload_groups") if isinstance(draft.get("upload_groups"), dict) else {}
    answer_sheets = list(upload_groups.get("answer_sheet_files") or [])
    if len(answer_sheets) != len(student_ids):
        raise ApiError(
            status_code=400,
            message=f"answer_sheet_files count ({len(answer_sheets)}) must equal student_ids count ({len(student_ids)})",
        )

    template_job_id = str(body.get("template_job_id") or "").strip()
    detected_mode = str(draft.get("detected_mode") or "")
    vision_profile = draft.get("vision_profile")
    text_profile = draft.get("text_profile")
    selected_answer_blocks = draft.get("selected_answer_blocks") or []

    shared_paper_files = list(upload_groups.get("paper_files") or [])
    shared_answer_key_files = list(upload_groups.get("answer_key_files") or [])
    shared_combined_files = list(upload_groups.get("combined_files") or [])
    pre_split_questions = list(draft.get("pre_split_questions") or [])

    if template_job_id:
        template_job = _require_job_access(user, template_job_id)
        if str(template_job.get("status") or "") != "succeeded":
            raise ApiError(status_code=400, message="template_job_id must be succeeded")
        template_report = ctx.analysis_service.get_report(template_job_id)
        pre_split_questions = _extract_pre_split_questions_from_report(template_report)

        template_files = ctx.analysis_service.repo.list_job_files(template_job_id)
        template_key_files: list[tuple[str, bytes, str | None]] = []
        for item in template_files:
            category = str(item.get("category") or "")
            if category != "answer_key_files":
                continue
            local_path = str(item.get("local_path") or "")
            if not local_path:
                continue
            file_name = str(item.get("file_name") or "answer_key.bin")
            content_type = item.get("content_type")
            content = ctx.analysis_service.storage.read_bytes(local_path)
            template_key_files.append((file_name, content, content_type))
        if template_key_files:
            shared_answer_key_files = template_key_files

        detected_mode = "pre_split_questions"
        shared_paper_files = []
        shared_combined_files = []
        selected_answer_blocks = []

    if detected_mode not in {
        "paper_answer_with_key",
        "paper_answer_auto_key",
        "paper_same_page",
        "pre_split_questions",
    }:
        raise ApiError(status_code=400, message="draft mode is invalid for batch submit")

    if detected_mode == "pre_split_questions" and not pre_split_questions:
        raise ApiError(
            status_code=400,
            message="pre_split_questions is required for batch pre_split mode; provide template_job_id or pre_split_questions",
        )
    if detected_mode == "paper_answer_with_key" and not shared_answer_key_files:
        raise ApiError(
            status_code=400,
            message="paper_answer_with_key batch mode requires shared answer_key_files or template_job_id",
        )

    job_ids: list[str] = []
    for index, student_id in enumerate(student_ids):
        answer_sheet = answer_sheets[index]
        per_job_groups = {
            "paper_files": list(shared_paper_files),
            "answer_sheet_files": [answer_sheet],
            "combined_files": list(shared_combined_files),
            "answer_key_files": list(shared_answer_key_files),
        }
        request_model = JobCreateInput(
            student_id=student_id,
            input_mode=detected_mode,
            vision_profile=vision_profile,
            text_profile=text_profile,
            pre_split_questions=list(pre_split_questions),
            selected_answer_blocks=list(selected_answer_blocks),
        )
        try:
            job_id = ctx.analysis_service.create_job(
                request=request_model,
                upload_groups=per_job_groups,
                created_by=user.id,
            )
        except ValueError as exc:
            raise ApiError(status_code=400, message=f"batch create failed at index {index}: {exc}") from exc
        job_ids.append(job_id)

    ctx.audit_service.log(
        actor_user_id=user.id,
        action="intake_draft_batch_submitted",
        target_type="intake_draft",
        target_id=draft_id,
        detail={"job_count": len(job_ids), "input_mode": detected_mode, "template_job_id": template_job_id},
    )
    return _json_response(
        {
            "job_ids": job_ids,
            "job_count": len(job_ids),
            "status": "queued",
            "effective_mode": detected_mode,
            "template_job_id": template_job_id or None,
        }
    )
