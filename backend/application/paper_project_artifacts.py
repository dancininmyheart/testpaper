from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote


class MinerUArtifactError(Exception):
    """Raised when persisted MinerU artifacts cannot be read as expected."""


class MinerUArtifactNotFound(MinerUArtifactError):
    """Raised when a required MinerU artifact file is missing."""


def safe_artifact_part(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return cleaned.strip("._") or "project"


def ascii_header_filename(file_name: str) -> str:
    raw = Path(str(file_name or "file")).name or "file"
    cleaned = []
    for ch in raw:
        if 32 <= ord(ch) <= 126 and ch not in {'"', "\\", ";"}:
            cleaned.append(ch)
        else:
            cleaned.append("_")
    fallback = "".join(cleaned).strip(" ._")
    if not fallback:
        suffix = Path(raw).suffix
        fallback = f"file{suffix}" if suffix and all(ord(ch) < 128 for ch in suffix) else "file"
    return fallback


def content_disposition_header(file_name: str, *, disposition: str = "inline") -> str:
    fallback = ascii_header_filename(file_name)
    encoded = quote(Path(str(file_name or fallback)).name, safe="")
    return f'{disposition}; filename="{fallback}"; filename*=UTF-8\'\'{encoded}'


def write_text_artifact(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json_artifact(path: Path, payload: Any) -> None:
    write_text_artifact(path, json.dumps(payload, ensure_ascii=False, indent=2))


def read_mineru_artifact_questions(artifact_dir: str) -> list[dict[str, Any]]:
    questions_path = Path(artifact_dir) / "questions.json"
    if not questions_path.is_file():
        raise MinerUArtifactNotFound("questions.json not found in mineru artifacts")

    try:
        questions_raw = json.loads(questions_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise MinerUArtifactError(f"failed to read questions.json: {exc}") from exc

    if not isinstance(questions_raw, list):
        raise MinerUArtifactError("questions.json is not a valid array")
    return [q for q in questions_raw if isinstance(q, dict)]


def guess_content_type(file_name: str) -> str:
    suffix = Path(str(file_name or "")).suffix.lower().lstrip(".")
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "gif": "image/gif",
        "pdf": "application/pdf",
    }.get(suffix, "application/octet-stream")


def mineru_image_ref_keys(value: str) -> set[str]:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return set()
    normalized = raw.lstrip("./")
    name = Path(normalized).name
    keys = {raw, normalized}
    if name:
        keys.add(name)
        keys.add(f"images/{name}")
    return {key for item in keys for key in (item, item.lower()) if key}


def load_mineru_cached_image_lookup(artifact_dir: str) -> dict[str, dict[str, str]]:
    """Map MinerU markdown image refs to cached image files from page metadata."""
    root = Path(artifact_dir)
    lookup: dict[str, dict[str, str]] = {}
    pages_dir = root / "pages"
    if not pages_dir.is_dir():
        return lookup

    def add_image(*, name: str, local_path: str, content_type: str | None = None) -> None:
        if not local_path:
            return
        file_name = Path(str(name or local_path)).name
        info = {
            "name": str(name or file_name),
            "file_name": file_name,
            "local_path": str(local_path),
            "content_type": str(content_type or guess_content_type(file_name)),
        }
        for key in mineru_image_ref_keys(str(name or file_name)):
            lookup.setdefault(key, info)
        for key in mineru_image_ref_keys(file_name):
            lookup.setdefault(key, info)

    for metadata_path in sorted(pages_dir.glob("page_*/metadata.json")):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        cached_images = metadata.get("cached_images") if isinstance(metadata, dict) else None
        if isinstance(cached_images, list):
            for image in cached_images:
                if not isinstance(image, dict):
                    continue
                add_image(
                    name=str(image.get("name") or ""),
                    local_path=str(image.get("local_path") or ""),
                    content_type=image.get("content_type"),
                )
        asset_paths = metadata.get("asset_paths") if isinstance(metadata, dict) else None
        if isinstance(asset_paths, list):
            image_names = metadata.get("image_names") if isinstance(metadata.get("image_names"), list) else []
            for index, asset_path in enumerate(asset_paths):
                name = str(image_names[index]) if index < len(image_names) else Path(str(asset_path)).name
                add_image(name=name, local_path=str(asset_path))
    return lookup


def same_local_path(left: str, right: str) -> bool:
    if str(left or "") == str(right or ""):
        return True
    try:
        return Path(left).resolve() == Path(right).resolve()
    except Exception:
        return False


def ensure_mineru_review_image_file(
    ctx: Any,
    *,
    project_id: str,
    image: dict[str, str],
    files: list[dict[str, Any]],
) -> int | None:
    local_path = str(image.get("local_path") or "")
    if not local_path:
        return None
    for file in files:
        if same_local_path(str(file.get("local_path") or ""), local_path):
            try:
                return int(file.get("id"))
            except (TypeError, ValueError):
                return None

    try:
        size_bytes = Path(local_path).stat().st_size
    except OSError:
        try:
            size_bytes = len(ctx.storage.read_bytes(local_path))
        except Exception:
            return None

    file_name = Path(str(image.get("file_name") or image.get("name") or local_path)).name
    content_type = image.get("content_type") or guess_content_type(file_name)
    file_id = ctx.paper_repo.add_project_file(
        project_id=project_id,
        category="question_images",
        file_name=file_name,
        local_path=local_path,
        content_type=content_type,
        size_bytes=size_bytes,
    )
    files.append({
        "id": file_id,
        "project_id": project_id,
        "category": "question_images",
        "file_name": file_name,
        "local_path": local_path,
        "content_type": content_type,
        "size_bytes": size_bytes,
    })
    return int(file_id)


def int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def dedupe_review_images(ctx: Any, images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    seen_names: set[str] = set()
    output: list[dict[str, Any]] = []
    for img in images:
        file_name = str(img.get("file_name") or "")
        if file_name and file_name in seen_names:
            continue
        if file_name:
            seen_names.add(file_name)
        local_path = str(img.get("local_path") or "")
        key = ""
        if local_path:
            try:
                content = ctx.storage.read_bytes(local_path)
                key = f"sha256:{hashlib.sha256(content).hexdigest()}"
            except Exception:
                key = ""
        if not key:
            file_id = img.get("file_id")
            key = f"id:{file_id}" if file_id is not None else f"name:{str(img.get('file_name') or '')}"
        if key in seen:
            continue
        seen.add(key)
        output.append({
            "id": img.get("file_id"),
            "file_name": file_name,
            "sort_order": img.get("sort_order", 0),
        })
    return output


def build_mineru_review_payload(ctx: Any, project_id: str, questions_raw: list[dict[str, Any]]) -> dict[str, Any]:
    question_images = ctx.paper_repo.get_question_images(project_id)
    ref_answers = ctx.paper_repo.get_reference_answers(project_id)
    files = ctx.paper_repo.list_project_files(project_id)
    artifact_dir = ctx.paper_repo.get_mineru_artifact_dir(project_id)
    artifact_images = load_mineru_cached_image_lookup(artifact_dir) if artifact_dir else {}
    answer_by_qid: dict[str, dict] = {}
    for answer in ref_answers:
        qid = str(answer.get("question_id") or "")
        if qid:
            answer_by_qid[qid] = {
                "answer_text": answer.get("answer_text", ""),
                "analysis": answer.get("analysis", ""),
                "final_answer": answer.get("final_answer"),
                "steps": answer.get("steps", []),
                "source": answer.get("source", ""),
            }
    images_by_qid: dict[str, list[dict]] = {}
    for img in question_images:
        qid = str(img.get("question_id") or "")
        images_by_qid.setdefault(qid, []).append(dict(img))

    for q in questions_raw:
        qid = str(q.get("question_id") or "")
        if not qid:
            continue
        image_refs = q.get("image_refs", []) or q.get("matched_image_ids", [])
        if not isinstance(image_refs, list):
            continue
        target_images = images_by_qid.setdefault(qid, [])
        for ref in image_refs:
            image = None
            for key in mineru_image_ref_keys(str(ref)):
                image = artifact_images.get(key)
                if image:
                    break
            if not image:
                continue
            file_id = ensure_mineru_review_image_file(
                ctx,
                project_id=project_id,
                image=image,
                files=files,
            )
            if file_id is None:
                continue
            if any(int(existing.get("file_id") or 0) == file_id for existing in target_images):
                continue
            sort_order = len(target_images)
            ctx.paper_repo.save_question_image(
                project_id=project_id,
                question_id=qid,
                file_id=file_id,
                page_index=int_or_zero(q.get("page_index")),
                sort_order=sort_order,
            )
            target_images.append({
                "question_id": qid,
                "file_id": file_id,
                "file_name": image.get("file_name") or Path(str(image.get("name") or "")).name,
                "local_path": image.get("local_path"),
                "content_type": image.get("content_type"),
                "sort_order": sort_order,
            })

    images_by_qid = {
        qid: dedupe_review_images(ctx, images)
        for qid, images in images_by_qid.items()
    }
    paper_page_files = [f for f in files if str(f.get("category") or "") == "paper_files"]

    questions_out = []
    for q in questions_raw:
        qid = str(q.get("question_id") or "")
        page_idx = q.get("page_index", 0)
        if not isinstance(page_idx, int):
            page_idx = 0
        paper_file = paper_page_files[page_idx] if page_idx < len(paper_page_files) else None

        content = str(q.get("content_markdown") or q.get("content") or "")

        options = q.get("options")
        if isinstance(options, dict) and options:
            for key in sorted(str(k) for k in options.keys()):
                opt_text = str(options[key]).strip()
                line = f"{key}. {opt_text}"
                if opt_text and line not in content:
                    content += "\n" + line

        questions_out.append({
            "question_id": qid,
            "question_no": q.get("question_no", ""),
            "question_type": q.get("question_type", "unknown"),
            "content": content,
            "max_score": q.get("max_score"),
            "page_index": page_idx,
            "skill_tags": q.get("skill_tags", []),
            "image_refs": q.get("image_refs", []) or q.get("matched_image_ids", []),
            "paper_page_file_id": paper_file.get("id") if paper_file else None,
            "images": images_by_qid.get(qid, []),
            "reference_answer": answer_by_qid.get(qid),
        })

    return {
        "project_id": project_id,
        "question_count": len(questions_out),
        "reference_answer_count": len(ref_answers),
        "questions": questions_out,
        "files": {
            "paper_pages": [
                {"id": f.get("id"), "file_name": f.get("file_name"), "page_index": idx}
                for idx, f in enumerate(paper_page_files)
            ],
            "answer_key_pages": [],
        },
        "source": "mineru",
    }


def persist_mineru_artifacts_to_disk(
    *,
    storage_root: Path,
    project_id: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Write MinerU debug artifacts to a stable developer-readable project folder."""
    artifact_dir = storage_root / "jobs" / safe_artifact_part(project_id) / "mineru_artifacts"
    pages_dir = artifact_dir / "pages"
    llm_dir = artifact_dir / "llm"

    page_entries: list[dict[str, Any]] = []
    pages = state.get("pages", [])
    iter_pages = pages if isinstance(pages, list) else []
    for page in iter_pages:
        if not isinstance(page, dict):
            continue
        page_index = int(page.get("page_index") or 0)
        page_dir = pages_dir / f"page_{page_index:03d}"
        raw_path = page_dir / "raw.md"
        corrected_path = page_dir / "corrected.md"
        metadata_path = page_dir / "metadata.json"
        write_text_artifact(raw_path, str(page.get("raw_markdown") or ""))
        write_text_artifact(corrected_path, str(page.get("corrected_markdown") or page.get("full_text") or ""))
        metadata = {
            "page_index": page_index,
            "raw_markdown_path": page.get("raw_markdown_path", ""),
            "corrected_markdown_path": page.get("corrected_markdown_path", ""),
            "source_image": page.get("source_image", ""),
            "asset_paths": page.get("asset_paths", []),
            "image_names": page.get("image_names", []),
            "cached_images": page.get("cached_images", []),
            "has_error": page.get("has_error", False),
        }
        write_json_artifact(metadata_path, metadata)
        page_entries.append({
            "page_index": page_index,
            "raw_markdown_file": str(raw_path),
            "corrected_markdown_file": str(corrected_path),
            "metadata_file": str(metadata_path),
        })

    llm_artifact = state.get("llm_structured_output") or {}
    llm_files: dict[str, str] = {}
    if isinstance(llm_artifact, dict) and llm_artifact:
        prompt_path = llm_dir / "prompt.txt"
        raw_response_path = llm_dir / "raw_response.txt"
        parsed_payload_path = llm_dir / "parsed_payload.json"
        normalized_questions_path = llm_dir / "normalized_questions.json"
        write_text_artifact(prompt_path, str(llm_artifact.get("prompt") or ""))
        write_text_artifact(raw_response_path, str(llm_artifact.get("raw_response") or ""))
        write_json_artifact(parsed_payload_path, llm_artifact.get("parsed_payload") or {})
        write_json_artifact(normalized_questions_path, llm_artifact.get("normalized_questions") or [])
        llm_files = {
            "prompt_file": str(prompt_path),
            "raw_response_file": str(raw_response_path),
            "parsed_payload_file": str(parsed_payload_path),
            "normalized_questions_file": str(normalized_questions_path),
        }

    questions_path = artifact_dir / "questions.json"
    write_json_artifact(questions_path, state.get("questions", []))
    manifest = {
        "project_id": project_id,
        "artifact_dir": str(artifact_dir),
        "pages": page_entries,
        "llm": llm_files,
        "questions_file": str(questions_path),
    }
    manifest_path = artifact_dir / "manifest.json"
    manifest["manifest_path"] = str(manifest_path)
    write_json_artifact(manifest_path, manifest)
    return manifest


def build_cached_image_lookup(state: dict, storage) -> dict[int, dict[str, bytes]]:
    """Build per-page image lookup from cached MinerU images in state."""
    img_lookup: dict[int, dict[str, bytes]] = {}
    for p in state.get("pages", []):
        pi = p["page_index"]
        img_lookup[pi] = {}
        for ci in p.get("cached_images", []):
            try:
                img_lookup[pi][ci["name"]] = storage.read_bytes(ci["local_path"])
            except (FileNotFoundError, OSError):
                pass
    return img_lookup


def build_page_results_from_cache(state: dict, storage) -> list[dict]:
    """Build page_results with image bytes from cached MinerU images."""
    page_results: list[dict] = []
    for p in state.get("pages", []):
        images: list[tuple[str, bytes]] = []
        for ci in p.get("cached_images", []):
            try:
                images.append((ci["name"], storage.read_bytes(ci["local_path"])))
            except (FileNotFoundError, OSError):
                pass
        page_results.append({
            "page_index": p["page_index"],
            "images": images,
        })
    return page_results
