# -*- coding: utf-8 -*-
from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
from pathlib import Path

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
except ImportError as e:
    A4 = None
    SimpleDocTemplate = None
    Paragraph = None
    Spacer = None
    getSampleStyleSheet = None
    ParagraphStyle = None
    pdfmetrics = None
    UnicodeCIDFont = None
    _REPORTLAB_IMPORT_ERROR = e
else:
    _REPORTLAB_IMPORT_ERROR = None


_REPO_ROOT = Path(__file__).resolve().parents[2]
_MATH_PATTERN = re.compile(
    r"(?<!\\)\$\$.*?(?<!\\)\$\$|(?<!\\)\$[^$\n]+(?<!\\)\$|\\\(|\\\[",
    re.DOTALL,
)


def render_markdown_to_pdf(markdown: str, pdf_path: Path) -> None:
    """Render generated Markdown to PDF.

    Math-heavy generated exams use a browser path:
    Markdown -> local HTML -> KaTeX auto-render -> headless browser PDF.
    Plain text can still fall back to the old ReportLab path so lightweight
    tests and non-math exports do not require a browser.
    """
    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    html_path = pdf_path.with_suffix(".html")
    write_html_for_pdf(markdown, html_path)

    browser = find_browser_executable()
    if browser:
        _render_html_to_pdf_with_browser(html_path, pdf_path, browser)
        return

    if _contains_math(markdown):
        raise RuntimeError(
            "PDF export with LaTeX formulas requires a headless browser. "
            "Install Microsoft Edge/Chrome or set PDF_BROWSER_PATH."
        )

    _render_basic_markdown_to_pdf(markdown, pdf_path)


def write_html_for_pdf(markdown: str, html_path: Path) -> None:
    html_path = Path(html_path)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(_build_html_document(markdown), encoding="utf-8")


def find_browser_executable() -> str:
    env_path = os.getenv("PDF_BROWSER_PATH", "").strip()
    if env_path and Path(env_path).is_file():
        return env_path

    for name in (
        "msedge",
        "chrome",
        "chromium",
        "google-chrome",
        "chromium-browser",
    ):
        found = shutil.which(name)
        if found:
            return found

    for candidate in (
        Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
        Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
        Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
    ):
        if candidate.is_file():
            return str(candidate)

    return ""


def _contains_math(markdown: str) -> bool:
    return bool(_MATH_PATTERN.search(markdown or ""))


def _find_katex_dist() -> Path:
    for candidate in (
        _REPO_ROOT / "node_modules" / "katex" / "dist",
        _REPO_ROOT / "frontend" / "node_modules" / "katex" / "dist",
    ):
        if (candidate / "katex.min.css").is_file() and (candidate / "katex.min.js").is_file():
            return candidate
    raise RuntimeError(
        "KaTeX assets not found. Run npm install in the repo root or frontend directory."
    )


def _build_html_document(markdown: str) -> str:
    katex_dist = _find_katex_dist()
    katex_css = (katex_dist / "katex.min.css").as_uri()
    katex_js = (katex_dist / "katex.min.js").as_uri()
    auto_render_js = (katex_dist / "contrib" / "auto-render.min.js").as_uri()
    if not (katex_dist / "contrib" / "auto-render.min.js").is_file():
        raise RuntimeError("KaTeX auto-render asset not found.")

    body = _markdown_to_body_html(markdown)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Generated Exam</title>
  <link rel="stylesheet" href="{katex_css}">
  <style>
    @page {{ size: A4; margin: 18mm 16mm; }}
    * {{ box-sizing: border-box; }}
    body {{
      color: #111827;
      font-family: "Microsoft YaHei", "Noto Sans CJK SC", "PingFang SC", Arial, sans-serif;
      font-size: 13px;
      line-height: 1.72;
      margin: 0;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}
    h1, h2, h3 {{ color: #0f172a; line-height: 1.35; margin: 0 0 10px; }}
    h1 {{ font-size: 24px; text-align: center; margin-bottom: 18px; }}
    h2 {{ font-size: 18px; border-bottom: 1px solid #e5e7eb; padding-bottom: 6px; margin-top: 22px; }}
    h3 {{ font-size: 15px; margin-top: 16px; }}
    p {{ margin: 0 0 9px; }}
    ul, ol {{ margin: 0 0 10px 22px; padding: 0; }}
    li {{ margin: 0 0 5px; }}
    pre {{
      background: #f8fafc;
      border: 1px solid #e5e7eb;
      border-radius: 6px;
      padding: 10px;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    code {{ font-family: Consolas, "Courier New", monospace; font-size: 12px; }}
    .katex {{ font-size: 1.05em; }}
    .katex-display {{ margin: 0.65em 0; overflow: visible; }}
    .svg-block {{ margin: 10px 0; text-align: center; break-inside: avoid; }}
    .svg-block svg {{ max-width: 100%; height: auto; }}
    img {{ max-width: 100%; }}
  </style>
</head>
<body>
{body}
  <script defer src="{katex_js}"></script>
  <script defer src="{auto_render_js}"></script>
  <script>
    window.addEventListener('load', function () {{
      renderMathInElement(document.body, {{
        delimiters: [
          {{ left: '$$', right: '$$', display: true }},
          {{ left: '$', right: '$', display: false }},
          {{ left: '\\\\(', right: '\\\\)', display: false }},
          {{ left: '\\\\[', right: '\\\\]', display: true }}
        ],
        throwOnError: false,
        ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code']
      }});
      document.body.dataset.katexReady = 'true';
    }});
  </script>
</body>
</html>
"""


def _markdown_to_body_html(markdown: str) -> str:
    blocks: list[str] = []
    list_type: str | None = None
    in_code_block = False
    code_lines: list[str] = []
    in_svg_block = False
    svg_lines: list[str] = []

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            blocks.append(f"</{list_type}>")
            list_type = None

    def close_code() -> None:
        nonlocal code_lines
        if code_lines:
            blocks.append(f"<pre><code>{html.escape(chr(10).join(code_lines))}</code></pre>")
            code_lines = []

    for line in markdown.splitlines():
        stripped = line.strip()

        if in_code_block:
            if stripped.startswith("```"):
                in_code_block = False
                close_code()
            else:
                code_lines.append(line)
            continue

        if in_svg_block:
            svg_lines.append(line)
            if "</svg>" in line:
                blocks.append(f"<div class=\"svg-block\">{chr(10).join(svg_lines)}</div>")
                svg_lines = []
                in_svg_block = False
            continue

        if stripped.startswith("```"):
            close_list()
            in_code_block = True
            code_lines = []
            continue

        if stripped.startswith("<svg"):
            close_list()
            svg_lines = [line]
            if "</svg>" in line:
                blocks.append(f"<div class=\"svg-block\">{line}</div>")
                svg_lines = []
            else:
                in_svg_block = True
            continue

        if not stripped:
            close_list()
            continue

        heading = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading:
            close_list()
            level = len(heading.group(1))
            blocks.append(f"<h{level}>{_inline_html(heading.group(2))}</h{level}>")
            continue

        unordered = re.match(r"^[-*]\s+(.+)$", stripped)
        if unordered:
            if list_type != "ul":
                close_list()
                blocks.append("<ul>")
                list_type = "ul"
            blocks.append(f"<li>{_inline_html(unordered.group(1))}</li>")
            continue

        ordered = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        if ordered:
            if list_type != "ol":
                close_list()
                blocks.append("<ol>")
                list_type = "ol"
            blocks.append(f"<li>{_inline_html(ordered.group(1))}</li>")
            continue

        close_list()
        blocks.append(f"<p>{_inline_html(line)}</p>")

    close_list()
    if in_code_block:
        close_code()
    if in_svg_block and svg_lines:
        blocks.append(f"<div class=\"svg-block\">{chr(10).join(svg_lines)}</div>")
    return "\n".join(blocks)


def _inline_html(text: str) -> str:
    image_match = re.fullmatch(r"\s*!\[([^\]]*)]\(([^)\n]+)\)\s*", text)
    if image_match:
        alt = html.escape(image_match.group(1), quote=True)
        src = html.escape(image_match.group(2), quote=True)
        return f"<img src=\"{src}\" alt=\"{alt}\">"

    escaped = html.escape(text)
    escaped = re.sub(r"`([^`]+)`", lambda m: f"<code>{m.group(1)}</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", lambda m: f"<strong>{m.group(1)}</strong>", escaped)
    return escaped


def _render_html_to_pdf_with_browser(html_path: Path, pdf_path: Path, browser: str) -> None:
    temp_pdf_path = pdf_path.with_name(f"{pdf_path.stem}.rendering{pdf_path.suffix}")
    if temp_pdf_path.exists():
        temp_pdf_path.unlink()

    base_args = [
        str(browser),
        "--disable-gpu",
        "--disable-extensions",
        "--allow-file-access-from-files",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=1500",
        "--no-pdf-header-footer",
        "--print-to-pdf-no-header",
        f"--print-to-pdf={temp_pdf_path}",
        html_path.as_uri(),
    ]

    errors: list[str] = []
    for headless_flag in ("--headless=new", "--headless"):
        cmd = [base_args[0], headless_flag, *base_args[1:]]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
        )
        if result.returncode == 0 and temp_pdf_path.is_file() and temp_pdf_path.stat().st_size > 0:
            temp_pdf_path.replace(pdf_path)
            return
        errors.append((result.stderr or result.stdout or "").strip())

    detail = " | ".join(e for e in errors if e)
    raise RuntimeError(f"browser PDF export failed{': ' + detail if detail else ''}")


def _render_basic_markdown_to_pdf(markdown: str, pdf_path: Path) -> None:
    if _REPORTLAB_IMPORT_ERROR is not None:
        raise RuntimeError(f"pdf export requires reportlab: {_REPORTLAB_IMPORT_ERROR}")

    font_name = "STSong-Light"
    try:
        if "STSong-Light" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    except Exception:
        font_name = "Helvetica"

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        rightMargin=42,
        leftMargin=42,
        topMargin=42,
        bottomMargin=42,
    )

    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "ChineseBody", parent=styles["Normal"], fontName=font_name, fontSize=10, leading=14, spaceAfter=6
    )
    h1_style = ParagraphStyle(
        "ChineseH1", parent=styles["Heading1"], fontName=font_name, fontSize=18, leading=22, spaceAfter=12, spaceBefore=12
    )
    h2_style = ParagraphStyle(
        "ChineseH2", parent=styles["Heading2"], fontName=font_name, fontSize=14, leading=18, spaceAfter=8, spaceBefore=8
    )

    story = []
    in_code_block = False

    for line in markdown.split("\n"):
        stripped = line.strip()

        if "<svg" in line or "</svg>" in line:
            story.append(Paragraph("<b>[SVG diagram, view in web preview]</b>", body_style))
            continue

        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue

        if in_code_block:
            story.append(Paragraph(f"<font face='Courier'>{html.escape(line)}</font>", body_style))
            continue

        if stripped.startswith("# "):
            story.append(Paragraph(html.escape(stripped[2:]), h1_style))
        elif stripped.startswith("## "):
            story.append(Paragraph(html.escape(stripped[3:]), h2_style))
        elif stripped.startswith("### "):
            story.append(Paragraph(f"<b>{html.escape(stripped[4:])}</b>", body_style))
        elif stripped:
            story.append(Paragraph(html.escape(line), body_style))
        else:
            story.append(Spacer(1, 10))

    doc.build(story)
