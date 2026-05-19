from __future__ import annotations

import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

from tools.mineru_vlm_markdown_extract import (
    collect_markdown_image_refs,
    extract_questions_with_artifact,
    extract_markdown_bundle,
    load_env_file,
    PageCorrection,
    parse_json_model_response,
    strip_markdown_model_response,
)


def _zip_bytes(members: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, content in members.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            archive.writestr(name, data)
    return buf.getvalue()


def test_extract_markdown_bundle_prefers_full_md_and_saves_assets(tmp_path: Path):
    archive_bytes = _zip_bytes(
        {
            "result/page.md": "# wrong",
            "result/full.md": "# title\n![plot](images/plot.png)\n",
            "result/images/plot.png": b"png-bytes",
            "result/content_list.json": "{}",
        }
    )

    bundle = extract_markdown_bundle(
        archive_bytes=archive_bytes,
        output_dir=tmp_path,
        stem="page_1",
    )

    assert bundle.markdown_path.read_text(encoding="utf-8").startswith("# title")
    assert [path.name for path in bundle.asset_paths] == ["plot.png"]
    assert (tmp_path / "page_1" / "images" / "plot.png").read_bytes() == b"png-bytes"


def test_collect_markdown_image_refs_keeps_local_and_remote_order(tmp_path: Path):
    md_path = tmp_path / "doc.md"
    local = tmp_path / "assets" / "geometry 1.jpg"
    local.parent.mkdir()
    local.write_bytes(b"image")
    markdown = """
    ![local](assets/geometry%201.jpg)
    <img src="https://example.test/chart.png" />
    ![missing](assets/missing.jpg)
    ![duplicate](assets/geometry%201.jpg)
    """

    refs = collect_markdown_image_refs(markdown=markdown, markdown_path=md_path)

    assert [ref.source for ref in refs] == ["assets/geometry%201.jpg", "https://example.test/chart.png"]
    assert refs[0].path == local
    assert refs[1].url == "https://example.test/chart.png"


def test_strip_markdown_model_response_removes_single_fenced_block():
    raw = "```markdown\n# corrected\n![a](img.png)\n```"

    assert strip_markdown_model_response(raw) == "# corrected\n![a](img.png)"


def test_parse_json_model_response_accepts_fenced_json():
    payload = [{"question_id": "Q1", "image_refs": ["img.png"]}]
    raw = "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"

    assert parse_json_model_response(raw) == payload


class _FakeQuestionRuntime:
    def invoke_json(self, **kwargs):
        return json.dumps(
            {
                "questions": [
                    {
                        "question_id": "Q1",
                        "content_markdown": "1. test",
                        "page_index": 0,
                        "image_refs": ["images/a.png"],
                    }
                ],
                "source": "unit-test",
            },
            ensure_ascii=False,
        )


def test_extract_questions_with_artifact_preserves_prompt_raw_and_parsed(tmp_path: Path):
    corrected = tmp_path / "page.corrected.md"
    raw = tmp_path / "page.md"
    image = tmp_path / "page.png"
    corrected.write_text("# corrected\n1. test", encoding="utf-8")
    raw.write_text("# raw", encoding="utf-8")
    image.write_bytes(b"image")
    correction = PageCorrection(
        source_image=image,
        raw_markdown_path=raw,
        corrected_markdown_path=corrected,
        asset_paths=[],
        markdown=corrected.read_text(encoding="utf-8"),
    )

    artifact = extract_questions_with_artifact(
        page_corrections=[correction],
        text_runtime=_FakeQuestionRuntime(),
        text_profile={"max_tokens": 2048},
    )

    assert "page_index=0" in artifact.prompt
    assert '"source": "unit-test"' in artifact.raw_response
    assert artifact.parsed_payload["source"] == "unit-test"
    assert artifact.questions[0]["question_id"] == "Q1"


def test_load_env_file_reads_values_without_overriding_existing(tmp_path: Path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "MINERU_API_KEY=from_file",
                "ARK_API_KEY=\"quoted value\"",
                "EXISTING_KEY=from_file",
                "# comment",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("MINERU_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.setenv("EXISTING_KEY", "from_shell")

    loaded = load_env_file(env_path)

    assert loaded == {"MINERU_API_KEY": "from_file", "ARK_API_KEY": "quoted value"}
    assert __import__("os").environ["MINERU_API_KEY"] == "from_file"
    assert __import__("os").environ["ARK_API_KEY"] == "quoted value"
    assert __import__("os").environ["EXISTING_KEY"] == "from_shell"


def test_cli_script_can_import_project_root_modules():
    result = subprocess.run(
        [sys.executable, "tools/mineru_vlm_markdown_extract.py", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Parse one or more images with MinerU VLM" in result.stdout
