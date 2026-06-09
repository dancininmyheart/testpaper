from __future__ import annotations

import html
from pathlib import Path

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
except ImportError as e:
    A4 = None
    SimpleDocTemplate = None
    Paragraph = None
    Spacer = None
    getSampleStyleSheet = None
    ParagraphStyle = None
    pdfmetrics = None
    UnicodeCIDFont = None
    _IMPORT_ERROR = e
else:
    _IMPORT_ERROR = None


def render_markdown_to_pdf(markdown: str, pdf_path: Path) -> None:
    """Render basic markdown document to PDF using ReportLab Platypus."""
    if _IMPORT_ERROR is not None:
        raise RuntimeError(f"pdf export requires reportlab: {_IMPORT_ERROR}")

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
        bottomMargin=42
    )
    
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        'ChineseBody', parent=styles['Normal'], fontName=font_name, fontSize=10, leading=14, spaceAfter=6
    )
    h1_style = ParagraphStyle(
        'ChineseH1', parent=styles['Heading1'], fontName=font_name, fontSize=18, leading=22, spaceAfter=12, spaceBefore=12
    )
    h2_style = ParagraphStyle(
        'ChineseH2', parent=styles['Heading2'], fontName=font_name, fontSize=14, leading=18, spaceAfter=8, spaceBefore=8
    )

    story = []
    lines = markdown.split('\n')
    in_code_block = False
    
    for line in lines:
        stripped = line.strip()
        
        # Avoid rendering raw SVG XML tags to reportlab paragraph since it doesn't parse it well.
        if "<svg" in line or "</svg>" in line:
            story.append(Paragraph("<b>[几何图形，请在Web端查看]</b>", body_style))
            continue
            
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
            
        if in_code_block:
            escaped = html.escape(line)
            story.append(Paragraph(f"<font face='Courier'>{escaped}</font>", body_style))
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
