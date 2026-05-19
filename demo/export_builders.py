from __future__ import annotations

import json
from io import BytesIO
from typing import Any, Dict, List, Optional

from demo.data_utils import _count_blocks_by_source, _extract_file_names, _now_iso

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas as reportlab_canvas
except Exception as exc:  # pragma: no cover - optional runtime dependency
    A4 = None  # type: ignore[assignment]
    pdfmetrics = None  # type: ignore[assignment]
    UnicodeCIDFont = None  # type: ignore[assignment]
    reportlab_canvas = None  # type: ignore[assignment]
    _REPORTLAB_IMPORT_ERROR = str(exc)
else:
    _REPORTLAB_IMPORT_ERROR = ""


def _build_request_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    paper_files = payload.get("paper_files")
    answer_sheet_files = payload.get("answer_sheet_files")
    combined_files = payload.get("combined_files")
    answer_key_files = payload.get("answer_key_files")
    selected_answer_blocks = payload.get("selected_answer_blocks") if isinstance(payload.get("selected_answer_blocks"), list) else []
    block_counts = _count_blocks_by_source([item for item in selected_answer_blocks if isinstance(item, dict)])
    paper_names = _extract_file_names(paper_files)
    answer_sheet_names = _extract_file_names(answer_sheet_files)
    combined_names = _extract_file_names(combined_files)
    answer_key_names = _extract_file_names(answer_key_files)
    pre_split_questions = payload.get("pre_split_questions")
    pre_split_question_ids: List[str] = []
    if isinstance(pre_split_questions, list):
        for item in pre_split_questions:
            if not isinstance(item, dict):
                continue
            qid = item.get("question_id")
            if isinstance(qid, str) and qid.strip():
                pre_split_question_ids.append(qid.strip())
    input_mode = str(payload.get("input_mode") or "")
    vision_profile = payload.get("vision_profile")
    text_profile = payload.get("text_profile")
    return {
        "student_id": str(payload.get("student_id") or "").strip(),
        "input_mode": input_mode,
        "vision_profile": vision_profile.strip() if isinstance(vision_profile, str) else "",
        "text_profile": text_profile.strip() if isinstance(text_profile, str) else "",
        "paper_file_count": len(paper_names),
        "paper_file_names": paper_names,
        "answer_sheet_file_count": len(answer_sheet_names),
        "answer_sheet_file_names": answer_sheet_names,
        "combined_file_count": len(combined_names),
        "combined_file_names": combined_names,
        "answer_key_file_count": len(answer_key_names),
        "answer_key_file_names": answer_key_names,
        "pre_split_question_count": len(pre_split_question_ids),
        "pre_split_question_ids": pre_split_question_ids,
        "selected_answer_block_count": len(selected_answer_blocks),
        "selected_answer_block_source_counts": block_counts,
    }


def _build_export_payload(request_payload: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    process = result.get("analysis_process")
    return {
        "meta": {
            "exported_at": _now_iso(),
            "schema_version": "demo_export_v1",
        },
        "request": _build_request_summary(request_payload),
        "analysis_process": process if isinstance(process, dict) else {},
        "analysis_result": result,
    }


def _pdf_safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _pdf_wrap_lines(text: str, max_chars: int) -> List[str]:
    source = text if isinstance(text, str) else _pdf_safe_text(text)
    lines: List[str] = []
    for raw_line in source.splitlines() or [""]:
        line = raw_line.strip()
        if not line:
            lines.append("")
            continue
        while len(line) > max_chars:
            lines.append(line[:max_chars])
            line = line[max_chars:]
        lines.append(line)
    return lines


def _build_export_pdf_bytes(request_payload: Dict[str, Any], result: Dict[str, Any]) -> bytes:
    if reportlab_canvas is None or A4 is None or pdfmetrics is None or UnicodeCIDFont is None:
        raise RuntimeError(f"pdf export requires reportlab: {_REPORTLAB_IMPORT_ERROR}")

    font_name = "Helvetica"
    try:
        if "STSong-Light" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        font_name = "STSong-Light"
    except Exception:
        font_name = "Helvetica"

    width, height = A4
    margin_left = 42.0
    margin_top = 42.0
    line_height = 15.0
    max_chars = 48

    buffer = BytesIO()
    pdf = reportlab_canvas.Canvas(buffer, pagesize=A4)
    y = height - margin_top

    def ensure_page() -> None:
        nonlocal y
        if y <= 48:
            pdf.showPage()
            y = height - margin_top

    def write_text(text: str, *, size: int = 11, gap_after: float = 0.0, max_line_chars: Optional[int] = None) -> None:
        nonlocal y
        pdf.setFont(font_name, size)
        for line in _pdf_wrap_lines(_pdf_safe_text(text), max_line_chars or max_chars):
            ensure_page()
            pdf.drawString(margin_left, y, line)
            y -= line_height
        if gap_after > 0:
            y -= gap_after

    request_summary = _build_request_summary(request_payload if isinstance(request_payload, dict) else {})
    mapping_report = result.get("mapping_report") if isinstance(result.get("mapping_report"), dict) else {}
    profile = result.get("student_profile") if isinstance(result.get("student_profile"), dict) else {}
    warnings_list = result.get("warnings") if isinstance(result.get("warnings"), list) else []
    answers = result.get("answer_trace_display")
    if not isinstance(answers, list):
        answers = result.get("answer_trace") if isinstance(result.get("answer_trace"), list) else []

    write_text("分析报告", size=18, gap_after=4, max_line_chars=24)
    write_text(f"导出时间: {_now_iso()}", size=10)
    write_text(f"学生ID: {_pdf_safe_text(result.get('student_id'))}", size=10)
    write_text(f"输入模式: {_pdf_safe_text(result.get('input_mode'))}", size=10, gap_after=4)

    write_text("请求摘要", size=14, gap_after=2, max_line_chars=28)
    write_text(f"试卷文件数量: {_pdf_safe_text(request_summary.get('paper_file_count'))}")
    write_text(f"答题卡文件数量: {_pdf_safe_text(request_summary.get('answer_sheet_file_count'))}")
    write_text(f"同卷文件数量: {_pdf_safe_text(request_summary.get('combined_file_count'))}")
    write_text(f"标准答案文件数量: {_pdf_safe_text(request_summary.get('answer_key_file_count'))}")
    write_text(f"试卷文件名: {_pdf_safe_text(request_summary.get('paper_file_names'))}", gap_after=4)

    write_text("结果概览", size=14, gap_after=2, max_line_chars=28)
    write_text(f"已映射题目: {_pdf_safe_text(mapping_report.get('mapped_questions'))} / {_pdf_safe_text(mapping_report.get('total_questions'))}")
    write_text(f"未匹配痕迹: {_pdf_safe_text(len(mapping_report.get('unmatched_traces') or []))}")
    write_text(f"结构化条目: {_pdf_safe_text(mapping_report.get('answer_structured_answer_count'))}")
    write_text(f"画像总结: {_pdf_safe_text(profile.get('summary'))}", gap_after=4)

    write_text("告警信息", size=14, gap_after=2, max_line_chars=28)
    if isinstance(warnings_list, list) and warnings_list:
        for idx, warning_text in enumerate(warnings_list[:40], start=1):
            write_text(f"{idx}. {_pdf_safe_text(warning_text)}")
    else:
        write_text("无")
    write_text("", gap_after=2)

    write_text("作答痕迹摘要", size=14, gap_after=2, max_line_chars=28)
    if isinstance(answers, list) and answers:
        for idx, item in enumerate(answers[:80], start=1):
            if not isinstance(item, dict):
                continue
            display_qid = item.get("display_question_id") or item.get("sub_question_id") or item.get("question_id")
            score = item.get("score")
            max_score = item.get("max_score")
            status = item.get("status")
            trace = item.get("trace") if isinstance(item.get("trace"), dict) else {}
            reason_code = trace.get("reason_code")
            write_text(
                f"{idx}. 题号={_pdf_safe_text(display_qid)} 状态={_pdf_safe_text(status)} 得分={_pdf_safe_text(score)}/{_pdf_safe_text(max_score)}",
                size=10,
            )
            answer_text = item.get("student_answer_text") if isinstance(item.get("student_answer_text"), str) else item.get("answer_text")
            if isinstance(answer_text, str) and answer_text.strip():
                write_text(f"   作答: {answer_text.strip()}", size=10, max_line_chars=60)
            if isinstance(reason_code, str) and reason_code.strip():
                write_text(f"   空痕迹原因码: {reason_code.strip()}", size=10)
    else:
        write_text("无")

    pdf.save()
    return buffer.getvalue()

