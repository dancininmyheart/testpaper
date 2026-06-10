from __future__ import annotations

import sys
from pathlib import Path

_EXAM_GEN_DIR = Path(__file__).resolve().parent.parent.parent / "Test_to_Test_Paper_Generation"
if str(_EXAM_GEN_DIR) not in sys.path:
    sys.path.insert(0, str(_EXAM_GEN_DIR))

from backend.api.routers.paper_projects import _ensure_generated_pdf_current


class FakePaperRepo:
    def __init__(self) -> None:
        self.updated: dict[str, str] = {}

    def update_project_data(self, project_id: str, **kwargs: str) -> None:
        self.updated.update(kwargs)


def test_generated_pdf_refreshes_old_cached_pdf_without_html_sidecar(tmp_path: Path, monkeypatch):
    md_path = tmp_path / "generated_exam.md"
    pdf_path = tmp_path / "generated_exam.pdf"
    md_path.write_text("# Exam\n\nSolve $x^2=1$.", encoding="utf-8")
    pdf_path.write_bytes(b"old raw latex pdf")

    def fake_render(markdown: str, output: Path) -> None:
        assert "$x^2=1$" in markdown
        output.write_bytes(b"new katex rendered pdf")
        output.with_suffix(".html").write_text("<span class=\"katex\"></span>", encoding="utf-8")

    monkeypatch.setattr("backend.application.exam_generation_service._ensure_in_syspath", lambda: None)
    monkeypatch.setattr("exam_generator.pdf_export.render_markdown_to_pdf", fake_render)

    repo = FakePaperRepo()
    result = _ensure_generated_pdf_current(
        "project-1",
        repo,
        {
            "generated_paper_path": str(md_path),
            "generated_paper_pdf_path": str(pdf_path),
        },
    )

    assert result == pdf_path
    assert pdf_path.read_bytes() == b"new katex rendered pdf"
    assert repo.updated["generated_paper_pdf_path"] == str(pdf_path)


def test_generated_pdf_refreshes_when_html_is_newer_than_pdf(tmp_path: Path, monkeypatch):
    md_path = tmp_path / "generated_exam.md"
    pdf_path = tmp_path / "generated_exam.pdf"
    html_path = tmp_path / "generated_exam.html"
    md_path.write_text("# Exam\n\nSolve $x^2=1$.", encoding="utf-8")
    pdf_path.write_bytes(b"old raw latex pdf")
    html_path.write_text("<html>new sidecar</html>", encoding="utf-8")

    newer = pdf_path.stat().st_mtime + 10
    import os

    os.utime(html_path, (newer, newer))

    def fake_render(markdown: str, output: Path) -> None:
        output.write_bytes(b"new katex rendered pdf")
        output.with_suffix(".html").write_text("<span class=\"katex\"></span>", encoding="utf-8")

    monkeypatch.setattr("backend.application.exam_generation_service._ensure_in_syspath", lambda: None)
    monkeypatch.setattr("exam_generator.pdf_export.render_markdown_to_pdf", fake_render)

    repo = FakePaperRepo()
    result = _ensure_generated_pdf_current(
        "project-1",
        repo,
        {
            "generated_paper_path": str(md_path),
            "generated_paper_pdf_path": str(pdf_path),
        },
    )

    assert result == pdf_path
    assert pdf_path.read_bytes() == b"new katex rendered pdf"
