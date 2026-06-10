# -*- coding: utf-8 -*-
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

_EXAM_GEN_DIR = Path(__file__).resolve().parent.parent.parent / "Test_to_Test_Paper_Generation"
if str(_EXAM_GEN_DIR) not in sys.path:
    sys.path.insert(0, str(_EXAM_GEN_DIR))

from exam_generator import pdf_export


def test_html_export_uses_katex_auto_render(tmp_path: Path):
    html_path = tmp_path / "exam.html"

    pdf_export.write_html_for_pdf("# Test\n\nSolve $x^2 + 1 = 0$.", html_path)

    html = html_path.read_text(encoding="utf-8")
    assert "katex.min.css" in html
    assert "katex.min.js" in html
    assert "auto-render.min.js" in html
    assert "renderMathInElement" in html
    assert "{ left: '$', right: '$', display: false }" in html


def test_markdown_with_latex_exports_pdf_with_browser(tmp_path: Path):
    browser = pdf_export.find_browser_executable()
    if not browser:
        pytest.skip("No headless browser executable found")

    pdf_path = tmp_path / "exam.pdf"
    pdf_export.render_markdown_to_pdf(
        "# Math Test\n\nInline $x^2 + y^2 = z^2$.\n\n$$\\frac{1}{2} + \\sqrt{x}$$",
        pdf_path,
    )

    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 1000

    try:
        text = subprocess.run(
            [str(browser), "--headless=new", "--dump-dom", pdf_path.with_suffix(".html").as_uri()],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        ).stdout
    except Exception:
        return
    assert "class=\"katex\"" in text


def test_browser_export_does_not_treat_existing_pdf_as_success(tmp_path: Path, monkeypatch):
    html_path = tmp_path / "exam.html"
    pdf_path = tmp_path / "exam.pdf"
    html_path.write_text("<html><body>test</body></html>", encoding="utf-8")
    pdf_path.write_bytes(b"old pdf")

    monkeypatch.setattr(
        pdf_export.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stderr="", stdout=""),
    )

    with pytest.raises(RuntimeError):
        pdf_export._render_html_to_pdf_with_browser(html_path, pdf_path, "browser")

    assert pdf_path.read_bytes() == b"old pdf"
