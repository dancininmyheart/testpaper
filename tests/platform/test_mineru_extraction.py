from __future__ import annotations

import io
import json
import threading
import time
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

from backend.application.paper_project_artifacts import dedupe_review_images, persist_mineru_artifacts_to_disk
from backend.application.mineru_extraction import (
    LLM_QUESTION_PROMPT,
    MinerUExtractionService,
    PageCorrection,
    _is_blank_image,
)
from tools.mineru_vlm_markdown_extract import _build_question_extraction_prompt


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_pure_white_is_blank():
    img = Image.new("RGB", (300, 300), (255, 255, 255))
    assert _is_blank_image(_png_bytes(img)) is True


def test_pure_gray_is_blank():
    img = Image.new("RGB", (300, 300), (128, 128, 128))
    assert _is_blank_image(_png_bytes(img)) is True


def test_pure_black_is_blank():
    img = Image.new("RGB", (300, 300), (0, 0, 0))
    assert _is_blank_image(_png_bytes(img)) is True


def test_empty_bytes_returns_false_no_raise():
    assert _is_blank_image(b"") is False


def test_corrupt_bytes_returns_false_no_raise():
    assert _is_blank_image(b"\x00\x01not-an-image") is False


def test_geometric_circle_is_not_blank():
    img = Image.new("RGB", (300, 300), "white")
    ImageDraw.Draw(img).ellipse((60, 60, 240, 240), outline="black", width=4)
    assert _is_blank_image(_png_bytes(img)) is False


def test_diagonal_line_is_not_blank():
    img = Image.new("RGB", (300, 300), "white")
    ImageDraw.Draw(img).line((10, 10, 290, 290), fill="black", width=5)
    assert _is_blank_image(_png_bytes(img)) is False


def _archive_bytes(members: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, content in members.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            archive.writestr(name, data)
    return buf.getvalue()


class _FakeMinerUClient:
    def __init__(self, archive_bytes: bytes) -> None:
        self.archive_bytes = archive_bytes

    def run_file_archive(self, file_path: Path):
        return {"batch_id": "batch_1"}, self.archive_bytes


class _FakeVisionRuntime:
    def invoke_text(self, **kwargs):
        assert kwargs["data_urls"]
        return "```markdown\n# corrected\n1. 如图求角度。\n![图](images/diagram.png)\n```"


class _FakeTextRuntime:
    def invoke_json(self, **kwargs):
        assert "corrected" in kwargs["prompt"]
        return json.dumps(
            {
                "questions": [
                    {
                        "question_id": "Q1",
                        "question_no": "1",
                        "question_type": "solve",
                        "content_markdown": "1. 如图求角度。\n![图](images/diagram.png)",
                        "page_index": 0,
                        "image_refs": ["images/diagram.png"],
                        "sub_questions": [],
                    }
                ]
            },
            ensure_ascii=False,
        )


class _CountingTextRuntime:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def invoke_json(self, **kwargs):
        self.calls.append(kwargs)
        prompt = kwargs["prompt"]
        assert "# corrected page_0" in prompt
        assert "# corrected page_1" in prompt
        return json.dumps(
            {
                "questions": [
                    {
                        "question_id": "Q1",
                        "content_markdown": "1. page 0",
                        "page_index": 0,
                        "image_refs": [],
                    },
                    {
                        "question_id": "Q2",
                        "content_markdown": "2. page 1",
                        "page_index": 1,
                        "image_refs": [],
                    },
                ]
            },
            ensure_ascii=False,
        )


class _ArtifactTextRuntime:
    def invoke_json(self, **kwargs):
        assert "# corrected page_0" in kwargs["prompt"]
        return json.dumps(
            {
                "questions": [
                    {
                        "question_id": "Q1",
                        "content_markdown": "1. artifact",
                        "page_index": 0,
                        "image_refs": [],
                    }
                ],
                "debug_source": "artifact-test",
            },
            ensure_ascii=False,
        )


def test_mineru_service_uses_corrected_markdown_for_question_extraction(tmp_path: Path):
    page_image = tmp_path / "page.png"
    page_image.write_bytes(_png_bytes(Image.new("RGB", (80, 80), "white")))
    archive = _archive_bytes(
        {
            "result/full.md": "# raw\n![old](images/diagram.png)",
            "result/images/diagram.png": _png_bytes(Image.new("RGB", (40, 40), "white")),
        }
    )
    service = MinerUExtractionService.__new__(MinerUExtractionService)
    service.mineru_client = _FakeMinerUClient(archive)
    service.vision_runtime = _FakeVisionRuntime()
    service.text_runtime = _FakeTextRuntime()
    service.vision_profile = {"max_tokens": 2048, "detail": "high", "thinking": "disabled", "reasoning_effort": "low"}
    service.text_profile = {"max_tokens": 2048, "thinking": "disabled", "reasoning_effort": "low"}

    pages = service.step1_parse(
        [{"local_path": str(page_image), "file_name": "page.png"}]
    )
    questions = service.step2_llm_parse(pages)
    matched = service.step3_vlm_match(questions)

    assert pages[0]["full_text"].startswith("# corrected")
    assert pages[0]["raw_markdown"].startswith("# raw")
    assert pages[0]["images"][0][0] == "images/diagram.png"
    assert questions[0]["content"] == "1. 如图求角度。\n![图](images/diagram.png)"
    assert questions[0]["images_on_page"] == ["images/diagram.png"]
    assert matched[0]["matched_image_ids"] == ["images/diagram.png"]


def test_mineru_step2_extracts_all_pages_with_one_llm_call(tmp_path: Path):
    service = MinerUExtractionService.__new__(MinerUExtractionService)
    text_runtime = _CountingTextRuntime()
    service.text_runtime = text_runtime
    service.text_profile = {"max_tokens": 2048, "thinking": "disabled", "reasoning_effort": "low"}

    page_results = []
    for idx in range(2):
        raw_path = tmp_path / f"page_{idx}.md"
        corrected_path = tmp_path / f"page_{idx}.corrected.md"
        image_path = tmp_path / f"page_{idx}.png"
        raw_path.write_text(f"# raw page_{idx}", encoding="utf-8")
        corrected_path.write_text(f"# corrected page_{idx}", encoding="utf-8")
        image_path.write_bytes(_png_bytes(Image.new("RGB", (80, 80), "white")))
        page_results.append(
            {
                "page_index": idx,
                "full_text": f"# corrected page_{idx}",
                "raw_markdown_path": str(raw_path),
                "corrected_markdown_path": str(corrected_path),
                "source_image": str(image_path),
                "asset_paths": [],
                "corrected_markdown": f"# corrected page_{idx}",
                "images": [],
            }
        )

    questions = service.step2_llm_parse(page_results)

    assert len(text_runtime.calls) == 1
    assert [question["question_id"] for question in questions] == ["Q1", "Q2"]


def test_mineru_service_accepts_explicit_model_profiles(monkeypatch, tmp_path):
    config_path = tmp_path / "llm_config.json"
    config_path.write_text(
        json.dumps(
            {
                "defaults": {"profile": "vision_default"},
                "openai_profiles": {
                    "vision_default": {"text_profile": "text_default"},
                },
            }
        ),
        encoding="utf-8",
    )
    loaded_profiles: list[str | None] = []

    monkeypatch.setattr("backend.application.mineru_extraction.load_env_file", lambda path: None)
    monkeypatch.setattr("backend.application.mineru_extraction.MinerUStandardClient", lambda path: object())

    def fake_load_profile(path, profile_name):
        loaded_profiles.append(profile_name)
        return {"profile": profile_name, "model": profile_name or "default"}

    monkeypatch.setattr("backend.application.mineru_extraction._load_profile", fake_load_profile)
    monkeypatch.setattr("backend.application.mineru_extraction._build_runtime", lambda profile: profile)

    service = MinerUExtractionService(
        config_path,
        vision_profile_name="openai_vision_gemini_3_flash",
        text_profile_name="openai_text_gemini_3_flash",
    )

    assert loaded_profiles == ["openai_text_gemini_3_flash", "openai_vision_gemini_3_flash"]
    assert service.text_runtime["profile"] == "openai_text_gemini_3_flash"
    assert service.vision_runtime["profile"] == "openai_vision_gemini_3_flash"


def test_mineru_step2_returns_llm_artifact_for_inspection(tmp_path: Path):
    service = MinerUExtractionService.__new__(MinerUExtractionService)
    text_runtime = _ArtifactTextRuntime()
    service.text_runtime = text_runtime
    service.text_profile = {"max_tokens": 2048, "thinking": "disabled", "reasoning_effort": "low"}

    raw_path = tmp_path / "page_0.md"
    corrected_path = tmp_path / "page_0.corrected.md"
    image_path = tmp_path / "page_0.png"
    raw_path.write_text("# raw page_0", encoding="utf-8")
    corrected_path.write_text("# corrected page_0", encoding="utf-8")
    image_path.write_bytes(_png_bytes(Image.new("RGB", (80, 80), "white")))

    questions, artifact = service.step2_llm_parse_with_artifact([
        {
            "page_index": 0,
            "full_text": "# corrected page_0",
            "raw_markdown_path": str(raw_path),
            "corrected_markdown_path": str(corrected_path),
            "source_image": str(image_path),
            "asset_paths": [],
            "corrected_markdown": "# corrected page_0",
            "images": [],
        }
    ])

    assert questions[0]["question_id"] == "Q1"
    assert "# corrected page_0" in artifact["prompt"]
    assert artifact["parsed_payload"]["questions"][0]["question_id"] == "Q1"
    assert artifact["normalized_questions"][0]["question_id"] == "Q1"


def test_mineru_question_prompt_groups_by_parent_question():
    assert "Group by parent question" in LLM_QUESTION_PROMPT
    assert "Do not output sub-questions" in LLM_QUESTION_PROMPT
    assert "Keep sub_questions as []" in LLM_QUESTION_PROMPT


def test_mineru_artifact_question_prompt_groups_by_parent_question(tmp_path: Path):
    prompt = _build_question_extraction_prompt(
        [
            PageCorrection(
                source_image=tmp_path / "page.png",
                raw_markdown_path=tmp_path / "page.md",
                corrected_markdown_path=tmp_path / "page.corrected.md",
                asset_paths=[],
                markdown="1. 阅读材料。\n(1) 求值。\n(2) 证明。",
            )
        ]
    )

    assert "Group by parent question" in prompt
    assert "Do not output sub-questions" in prompt
    assert "keep sub_questions as []" in prompt


def test_mineru_normalization_folds_sub_questions_into_parent_content():
    questions = MinerUExtractionService._normalize_markdown_questions(
        [
            {
                "question_id": "Q1",
                "question_no": "1",
                "question_type": "solve",
                "content": "阅读材料，回答问题。",
                "page_index": 0,
                "sub_questions": [
                    {"sub_question_id": "Q1(1)", "sub_text": "求函数解析式。"},
                    {"sub_question_id": "Q1(2)", "content": "证明函数单调性。"},
                ],
            }
        ]
    )

    assert len(questions) == 1
    assert "阅读材料，回答问题。" in questions[0]["content"]
    assert "Q1(1)" in questions[0]["content"]
    assert "求函数解析式。" in questions[0]["content"]
    assert "Q1(2)" in questions[0]["content"]
    assert "证明函数单调性。" in questions[0]["content"]
    assert questions[0]["sub_questions"] == []
    assert questions[0]["raw"]["sub_questions"][0]["sub_text"] == "求函数解析式。"


def test_mineru_step1_runs_multiple_pages_in_parallel(monkeypatch, tmp_path: Path):
    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_correct_one_image(*, image_path, mineru_client, vision_runtime, vision_profile, output_dir):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.1)
            output_dir.mkdir(parents=True, exist_ok=True)
            raw_path = output_dir / f"{image_path.stem}.md"
            corrected_path = output_dir / f"{image_path.stem}.corrected.md"
            raw_path.write_text(f"# raw {image_path.stem}", encoding="utf-8")
            corrected_path.write_text(f"# corrected {image_path.stem}", encoding="utf-8")
            return PageCorrection(
                source_image=image_path,
                raw_markdown_path=raw_path,
                corrected_markdown_path=corrected_path,
                asset_paths=[],
                markdown=f"# corrected {image_path.stem}",
            )
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(
        "backend.application.mineru_extraction.correct_one_image",
        fake_correct_one_image,
    )

    page_paths = []
    for idx in range(3):
        page_image = tmp_path / f"page_{idx}.png"
        page_image.write_bytes(_png_bytes(Image.new("RGB", (80, 80), "white")))
        page_paths.append(page_image)

    service = MinerUExtractionService.__new__(MinerUExtractionService)
    service.mineru_client = object()
    service.vision_runtime = object()
    service.vision_profile = {"max_tokens": 2048, "detail": "high"}

    pages = service.step1_parse([
        {"local_path": str(page_path), "file_name": page_path.name}
        for page_path in page_paths
    ])

    assert max_active > 1
    assert [page["page_index"] for page in pages] == [0, 1, 2]
    assert [page["full_text"] for page in pages] == [
        "# corrected page_0",
        "# corrected page_1",
        "# corrected page_2",
    ]


def test_mineru_step1_retries_failed_page(monkeypatch, tmp_path: Path):
    attempts = 0

    def fake_correct_one_image(*, image_path, mineru_client, vision_runtime, vision_profile, output_dir):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("cdn read timeout")
        output_dir.mkdir(parents=True, exist_ok=True)
        raw_path = output_dir / f"{image_path.stem}.md"
        corrected_path = output_dir / f"{image_path.stem}.corrected.md"
        raw_path.write_text("# raw retried", encoding="utf-8")
        corrected_path.write_text("# corrected retried", encoding="utf-8")
        return PageCorrection(
            source_image=image_path,
            raw_markdown_path=raw_path,
            corrected_markdown_path=corrected_path,
            asset_paths=[],
            markdown="# corrected retried",
        )

    monkeypatch.setattr(
        "backend.application.mineru_extraction.correct_one_image",
        fake_correct_one_image,
    )

    page_image = tmp_path / "page_0.png"
    page_image.write_bytes(_png_bytes(Image.new("RGB", (80, 80), "white")))
    service = MinerUExtractionService.__new__(MinerUExtractionService)
    service.mineru_client = object()
    service.vision_runtime = object()
    service.vision_profile = {"max_tokens": 2048, "detail": "high"}
    service.mineru_page_max_attempts = 2

    pages = service.step1_parse([{"local_path": str(page_image), "file_name": page_image.name}])

    assert attempts == 2
    assert pages[0]["has_error"] is False
    assert pages[0]["retry_attempts"] == 2
    assert pages[0]["full_text"] == "# corrected retried"


class _SavedFile:
    category = "question_images"
    file_name = "diagram.png"
    local_path = "stored/diagram.png"
    content_type = "image/png"
    size_bytes = 9


class _FakeStorage:
    def __init__(self) -> None:
        self.saved: list[dict] = []

    def save_job_file(self, **kwargs):
        self.saved.append(kwargs)
        return _SavedFile()


class _FakePaperRepo:
    def __init__(self) -> None:
        self.questions: list[dict] = []
        self.files: list[dict] = []
        self.question_images: list[dict] = []

    def add_project_file(self, **kwargs):
        self.files.append(kwargs)
        return len(self.files)

    def save_question_image(self, **kwargs):
        self.question_images.append(kwargs)

    def save_questions(self, **kwargs):
        self.questions = kwargs["questions"]


def test_step4_save_uses_markdown_image_refs_when_matched_ids_are_absent():
    service = MinerUExtractionService.__new__(MinerUExtractionService)
    storage = _FakeStorage()
    repo = _FakePaperRepo()

    result = service.step4_save(
        project_id="project_1",
        questions=[
            {
                "question_id": "Q1",
                "content": "题目\n![图](images/diagram.png)",
                "page_index": 0,
                "image_refs": ["images/diagram.png"],
            }
        ],
        page_results=[
            {
                "page_index": 0,
                "images": [("images/diagram.png", b"image-bytes")],
            }
        ],
        storage=storage,
        paper_repo=repo,
    )

    assert result == {"question_count": 1, "total_images": 1, "matched_count": 1}
    assert storage.saved[0]["original_name"] == "images/diagram.png"
    assert repo.question_images[0]["question_id"] == "Q1"
    assert repo.questions[0]["image_refs"] == ["images/diagram.png"]


def test_step4_save_deduplicates_repeated_image_refs():
    service = MinerUExtractionService.__new__(MinerUExtractionService)
    storage = _FakeStorage()
    repo = _FakePaperRepo()

    result = service.step4_save(
        project_id="project_1",
        questions=[
            {
                "question_id": "Q1",
                "content": "题目\n![图](images/diagram.png)",
                "page_index": 0,
                "matched_image_ids": ["images/diagram.png", "diagram.png", "images/diagram.png"],
            }
        ],
        page_results=[
            {
                "page_index": 0,
                "images": [("images/diagram.png", b"image-bytes")],
            }
        ],
        storage=storage,
        paper_repo=repo,
    )

    assert result["total_images"] == 1
    assert result["matched_count"] == 1
    assert len(storage.saved) == 1
    assert repo.questions[0]["matched_image_ids"] == ["images/diagram.png"]


def test_step4_save_deduplicates_same_image_bytes_with_different_names():
    service = MinerUExtractionService.__new__(MinerUExtractionService)
    storage = _FakeStorage()
    repo = _FakePaperRepo()

    result = service.step4_save(
        project_id="project_1",
        questions=[
            {
                "question_id": "Q1",
                "content": "题目",
                "page_index": 0,
                "matched_image_ids": ["images/a.png", "images/b.png"],
            }
        ],
        page_results=[
            {
                "page_index": 0,
                "images": [("images/a.png", b"same-image-bytes"), ("images/b.png", b"same-image-bytes")],
            }
        ],
        storage=storage,
        paper_repo=repo,
    )

    assert result["total_images"] == 1
    assert result["matched_count"] == 1
    assert len(storage.saved) == 1
    assert repo.questions[0]["matched_image_ids"] == ["images/a.png"]


def test_review_image_payload_deduplicates_existing_same_content_files():
    class _Storage:
        def read_bytes(self, local_path: str) -> bytes:
            return {
                "stored/a.png": b"same-image-bytes",
                "stored/b.png": b"same-image-bytes",
                "stored/c.png": b"different-image-bytes",
            }[local_path]

    class _Ctx:
        storage = _Storage()

    images = dedupe_review_images(
        _Ctx(),
        [
            {"file_id": 1, "file_name": "a.png", "local_path": "stored/a.png", "sort_order": 0},
            {"file_id": 2, "file_name": "b.png", "local_path": "stored/b.png", "sort_order": 1},
            {"file_id": 3, "file_name": "c.png", "local_path": "stored/c.png", "sort_order": 2},
        ],
    )

    assert [image["id"] for image in images] == [1, 3]


def test_review_image_payload_deduplicates_existing_same_file_name_files():
    class _Storage:
        def read_bytes(self, local_path: str) -> bytes:
            return {
                "stored/a1.png": b"first-image-bytes",
                "stored/a2.png": b"second-image-bytes",
            }[local_path]

    class _Ctx:
        storage = _Storage()

    images = dedupe_review_images(
        _Ctx(),
        [
            {"file_id": 1, "file_name": "same.png", "local_path": "stored/a1.png", "sort_order": 0},
            {"file_id": 2, "file_name": "same.png", "local_path": "stored/a2.png", "sort_order": 1},
        ],
    )

    assert [image["id"] for image in images] == [1]


def test_persist_mineru_artifacts_writes_developer_files(tmp_path: Path):
    state = {
        "pages": [
            {
                "page_index": 0,
                "raw_markdown": "# raw",
                "corrected_markdown": "# corrected",
                "raw_markdown_path": "work/raw.md",
                "corrected_markdown_path": "work/corrected.md",
                "source_image": "paper/page.png",
                "asset_paths": ["work/images/diagram.png"],
                "image_names": ["images/diagram.png"],
                "has_error": False,
            }
        ],
        "llm_structured_output": {
            "prompt": "extract prompt",
            "raw_response": '{"questions":[]}',
            "parsed_payload": {"questions": []},
            "normalized_questions": [{"question_id": "Q1"}],
        },
        "questions": [{"question_id": "Q1"}],
    }

    manifest = persist_mineru_artifacts_to_disk(
        storage_root=tmp_path,
        project_id="project_1",
        state=state,
    )

    artifact_dir = Path(manifest["artifact_dir"])
    assert artifact_dir.name == "mineru_artifacts"
    assert (artifact_dir / "pages" / "page_000" / "raw.md").read_text(encoding="utf-8") == "# raw"
    assert (artifact_dir / "pages" / "page_000" / "corrected.md").read_text(encoding="utf-8") == "# corrected"
    assert (artifact_dir / "llm" / "prompt.txt").read_text(encoding="utf-8") == "extract prompt"
    assert json.loads((artifact_dir / "llm" / "parsed_payload.json").read_text(encoding="utf-8")) == {"questions": []}
    assert Path(manifest["manifest_path"]).is_file()


def test_project_review_prefers_mineru_artifact_content(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("APP_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("WORKER_ENABLED", "false")

    from backend.main import create_app

    app = create_app(start_worker=False)
    try:
        client = app.test_client()
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "teacher", "password": "teacher123"},
        )
        token = login.get_json()["data"]["token"]
        headers = {"Authorization": f"Bearer {token}"}

        ctx = app.config["ctx"]
        project_id = "project_1"
        ctx.paper_repo.create_project(
            project_id=project_id,
            title="MinerU review test",
            subject="math",
            grade="8",
            created_by=2,
        )
        ctx.paper_repo.save_questions(
            project_id=project_id,
            questions=[{"question_id": "Q1", "question_no": "1", "content": "old truncated"}],
        )

        artifact_dir = tmp_path / "mineru_artifacts"
        artifact_dir.mkdir()
        (artifact_dir / "questions.json").write_text(
            json.dumps(
                [
                    {
                        "question_id": "Q1",
                        "question_no": "1",
                        "question_type": "solve",
                        "content_markdown": "完整题干\n![图](images/diagram.png)",
                        "page_index": 0,
                        "image_refs": ["images/diagram.png"],
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        ctx.paper_repo.set_mineru_artifact_dir(project_id, str(artifact_dir))

        response = client.get(f"/api/v1/paper-projects/{project_id}/review", headers=headers)
    finally:
        app.config["ctx"].close()

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["source"] == "mineru"
    assert payload["questions"][0]["content"] == "完整题干\n![图](images/diagram.png)"
    assert payload["questions"][0]["image_refs"] == ["images/diagram.png"]


def test_mineru_project_review_includes_saved_reference_answers(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("APP_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("WORKER_ENABLED", "false")

    from backend.main import create_app

    app = create_app(start_worker=False)
    try:
        client = app.test_client()
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "teacher", "password": "teacher123"},
        )
        headers = {"Authorization": f"Bearer {login.get_json()['data']['token']}"}

        ctx = app.config["ctx"]
        project_id = "project_1"
        ctx.paper_repo.create_project(
            project_id=project_id,
            title="MinerU review reference answer test",
            subject="math",
            grade="8",
            created_by=2,
        )

        artifact_dir = tmp_path / "mineru_artifacts"
        artifact_dir.mkdir()
        (artifact_dir / "questions.json").write_text(
            json.dumps(
                [
                    {
                        "question_id": "Q1",
                        "question_no": "1",
                        "question_type": "fill",
                        "content_markdown": "question",
                        "page_index": 0,
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        ctx.paper_repo.set_mineru_artifact_dir(project_id, str(artifact_dir))
        ctx.paper_repo.save_reference_answers(
            project_id=project_id,
            answers=[
                {
                    "question_id": "Q1",
                    "answer_text": "saved answer",
                    "analysis": "saved analysis",
                    "steps": ["step 1"],
                    "source": "generated",
                }
            ],
        )

        response = client.get(f"/api/v1/paper-projects/{project_id}/review", headers=headers)
    finally:
        app.config["ctx"].close()

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["reference_answer_count"] == 1
    assert payload["questions"][0]["reference_answer"]["answer_text"] == "saved answer"
    assert payload["questions"][0]["reference_answer"]["analysis"] == "saved analysis"
    assert payload["questions"][0]["reference_answer"]["steps"] == ["step 1"]


def test_mineru_review_backfills_cached_artifact_images(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("APP_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("WORKER_ENABLED", "false")

    from backend.main import create_app

    app = create_app(start_worker=False)
    try:
        client = app.test_client()
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "teacher", "password": "teacher123"},
        )
        token = login.get_json()["data"]["token"]
        headers = {"Authorization": f"Bearer {token}"}

        ctx = app.config["ctx"]
        project_id = "project_1"
        ctx.paper_repo.create_project(
            project_id=project_id,
            title="MinerU cached image test",
            subject="math",
            grade="8",
            created_by=2,
        )

        artifact_dir = tmp_path / "mineru_artifacts"
        page_dir = artifact_dir / "pages" / "page_000"
        page_dir.mkdir(parents=True)
        image_path = tmp_path / "storage" / "jobs" / project_id / "inputs" / "mineru_page_images" / "001_diagram.jpg"
        image_path.parent.mkdir(parents=True)
        image_path.write_bytes(b"cached-image-bytes")
        (page_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "page_index": 0,
                    "cached_images": [
                        {
                            "name": "images/diagram.jpg",
                            "local_path": str(image_path),
                            "content_type": "image/jpeg",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (artifact_dir / "questions.json").write_text(
            json.dumps(
                [
                    {
                        "question_id": "Q1",
                        "question_no": "1",
                        "question_type": "fill",
                        "content_markdown": "棰樼洰\n![鍥綸(images/diagram.jpg)",
                        "page_index": 0,
                        "image_refs": ["images/diagram.jpg"],
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        ctx.paper_repo.set_mineru_artifact_dir(project_id, str(artifact_dir))

        response = client.get(f"/api/v1/paper-projects/{project_id}/mineru-review", headers=headers)
        payload = response.get_json()["data"]
        image = payload["questions"][0]["images"][0]
        content_response = client.get(
            f"/api/v1/paper-projects/{project_id}/files/{image['id']}/content",
            headers=headers,
        )
    finally:
        app.config["ctx"].close()

    assert response.status_code == 200
    assert image["file_name"] == "diagram.jpg"
    assert content_response.status_code == 200
    assert content_response.data == b"cached-image-bytes"


def test_mineru_review_route_deduplicates_question_images(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("APP_STORAGE_ROOT", str(tmp_path / "storage"))
    monkeypatch.setenv("WORKER_ENABLED", "false")

    from backend.main import create_app

    app = create_app(start_worker=False)
    try:
        client = app.test_client()
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "teacher", "password": "teacher123"},
        )
        token = login.get_json()["data"]["token"]
        headers = {"Authorization": f"Bearer {token}"}

        ctx = app.config["ctx"]
        project_id = "project_1"
        ctx.paper_repo.create_project(
            project_id=project_id,
            title="MinerU review dedupe test",
            subject="math",
            grade="8",
            created_by=2,
        )

        artifact_dir = tmp_path / "mineru_artifacts"
        artifact_dir.mkdir()
        (artifact_dir / "questions.json").write_text(
            json.dumps(
                [
                    {
                        "question_id": "Q1",
                        "question_no": "1",
                        "question_type": "fill",
                        "content_markdown": "题目",
                        "page_index": 0,
                        "image_refs": ["images/diagram.png"],
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        ctx.paper_repo.set_mineru_artifact_dir(project_id, str(artifact_dir))

        image_path_1 = tmp_path / "dup1.jpg"
        image_path_2 = tmp_path / "dup2.jpg"
        image_path_1.write_bytes(b"same-image-bytes")
        image_path_2.write_bytes(b"same-image-bytes")
        file_id_1 = ctx.paper_repo.add_project_file(
            project_id=project_id,
            category="question_images",
            file_name="diagram.jpg",
            local_path=str(image_path_1),
            content_type="image/jpeg",
            size_bytes=image_path_1.stat().st_size,
        )
        file_id_2 = ctx.paper_repo.add_project_file(
            project_id=project_id,
            category="question_images",
            file_name="diagram.jpg",
            local_path=str(image_path_2),
            content_type="image/jpeg",
            size_bytes=image_path_2.stat().st_size,
        )
        ctx.paper_repo.save_question_image(project_id=project_id, question_id="Q1", file_id=file_id_1)
        ctx.paper_repo.save_question_image(project_id=project_id, question_id="Q1", file_id=file_id_2)

        response = client.get(f"/api/v1/paper-projects/{project_id}/mineru-review", headers=headers)
    finally:
        app.config["ctx"].close()

    assert response.status_code == 200
    images = response.get_json()["data"]["questions"][0]["images"]
    assert images == [{"id": file_id_1, "file_name": "diagram.jpg", "sort_order": 0}]
