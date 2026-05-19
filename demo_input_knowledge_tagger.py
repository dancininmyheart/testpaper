from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from demo_server import (
    DemoService,
    _attach_question_metadata,
    _merge_question_items,
    _normalize_question_item,
    _question_sort_key,
)
from llm_knowledge_tagger import _extract_points_from_nodes

QUESTION_START_PATTERN = re.compile(r"^\s*(\d{1,3})\s*(?:[\.．、]|[)）])\s*(.*)$")
IMAGE_MIME_BY_SUFFIX = {
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".bmp": "bmp",
    ".webp": "webp",
    ".tif": "tiff",
    ".tiff": "tiff",
}


def _load_json(path: Path) -> Any:
    raw = path.read_text(encoding="utf-8-sig")
    return json.loads(raw)


def _to_data_url(image_bytes: bytes, mime: str) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:image/{mime};base64,{encoded}"


def _load_image_as_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in IMAGE_MIME_BY_SUFFIX:
        raise ValueError(f"unsupported image format: {path}")
    mime = IMAGE_MIME_BY_SUFFIX[suffix]
    return _to_data_url(path.read_bytes(), mime)


def _load_pdf_as_data_urls(path: Path, *, dpi: int = 180, max_pages: int = 0) -> List[str]:
    try:
        import fitz  # PyMuPDF
    except Exception as exc:  # pragma: no cover - runtime dependency
        raise RuntimeError("PDF input requires PyMuPDF (fitz). Please install: pip install pymupdf") from exc

    doc = fitz.open(path)
    try:
        page_count = doc.page_count
        if page_count <= 0:
            return []
        target_count = page_count if max_pages <= 0 else min(page_count, max_pages)
        zoom = max(72, int(dpi)) / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        urls: List[str] = []
        for page_index in range(target_count):
            page = doc.load_page(page_index)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            urls.append(_to_data_url(pix.tobytes("jpeg", jpg_quality=80), "jpeg"))
        return urls
    finally:
        doc.close()


def _extract_question_list(payload: Any) -> List[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []

    for key in ("questions", "question_analysis", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return value

    analysis_result = payload.get("analysis_result")
    if isinstance(analysis_result, dict):
        nested = _extract_question_list(analysis_result)
        if nested:
            return nested

    return []


def _split_questions_from_text(text: str) -> List[Dict[str, Any]]:
    normalized_text = text.lstrip("\ufeff")
    lines = normalized_text.splitlines()
    blocks: List[Dict[str, Any]] = []
    current_no: Optional[str] = None
    current_lines: List[str] = []

    def flush_block() -> None:
        if current_no is None:
            return
        content = "\n".join(line for line in current_lines if line.strip()).strip()
        if not content:
            return
        blocks.append(
            {
                "question_id": current_no,
                "raw_question_id": current_no,
                "question_type": "unknown",
                "problem_text": content[:200],
                "problem_text_full": content,
                "sub_questions": [],
            }
        )

    for line in lines:
        line = line.lstrip("\ufeff")
        matched = QUESTION_START_PATTERN.match(line)
        if matched:
            flush_block()
            current_no = matched.group(1)
            first_line = matched.group(2).strip()
            current_lines = [first_line] if first_line else []
            continue
        if current_no is not None:
            current_lines.append(line.strip())

    flush_block()

    if blocks:
        return blocks

    compact = text.strip()
    if not compact:
        return []
    return [
        {
            "question_id": "1",
            "raw_question_id": "1",
            "question_type": "unknown",
            "problem_text": compact[:200],
            "problem_text_full": compact,
            "sub_questions": [],
        }
    ]


def _coerce_question_dict(item: Any, index: int) -> Optional[Dict[str, Any]]:
    if isinstance(item, str):
        text = item.strip()
        if not text:
            return None
        return {
            "question_id": str(index + 1),
            "raw_question_id": str(index + 1),
            "question_type": "unknown",
            "problem_text": text[:200],
            "problem_text_full": text,
            "sub_questions": [],
        }

    if not isinstance(item, dict):
        return None

    candidate = dict(item)
    qid = candidate.get("question_id")
    if not isinstance(qid, str) or not qid.strip():
        raw_qid = candidate.get("raw_question_id")
        if isinstance(raw_qid, str) and raw_qid.strip():
            candidate["question_id"] = raw_qid.strip()
        else:
            candidate["question_id"] = str(index + 1)
            candidate["raw_question_id"] = str(index + 1)

    problem_text = candidate.get("problem_text")
    problem_text_full = candidate.get("problem_text_full")
    if not isinstance(problem_text, str) or not problem_text.strip():
        for key in ("text", "question_text", "content"):
            value = candidate.get(key)
            if isinstance(value, str) and value.strip():
                candidate["problem_text"] = value.strip()[:200]
                break
    if not isinstance(problem_text_full, str) or not problem_text_full.strip():
        if isinstance(candidate.get("problem_text"), str) and candidate["problem_text"].strip():
            candidate["problem_text_full"] = candidate["problem_text"].strip()
    if not isinstance(candidate.get("question_type"), str):
        candidate["question_type"] = "unknown"
    if not isinstance(candidate.get("sub_questions"), list):
        candidate["sub_questions"] = []
    return candidate


def _normalize_questions(raw_items: List[Any]) -> List[Dict[str, Any]]:
    question_by_id: Dict[str, Dict[str, Any]] = {}
    for idx, item in enumerate(raw_items):
        candidate = _coerce_question_dict(item, idx)
        if candidate is None:
            continue
        page_index = candidate.get("paper_page_index") if isinstance(candidate.get("paper_page_index"), int) else 0
        normalized = _normalize_question_item(candidate, page_index=page_index)
        if normalized is None:
            continue
        qid = normalized["question_id"]
        existing = question_by_id.get(qid)
        question_by_id[qid] = normalized if existing is None else _merge_question_items(existing, normalized)
    ordered = sorted(question_by_id.values(), key=_question_sort_key)
    return _attach_question_metadata(ordered)


def _build_tag_name_map(service: DemoService) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for node in service.nodes:
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        if not isinstance(node_id, str) or not node_id.strip():
            continue
        short_name = node.get("short_name")
        if not isinstance(short_name, str) or not short_name.strip():
            name = node.get("name")
            if isinstance(name, str) and name.strip():
                short_name = name
            else:
                short_name = node_id
        mapping[node_id] = short_name.strip()
    return mapping


def _project_output_questions(questions: List[Dict[str, Any]], tag_name_map: Dict[str, str]) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    for question in questions:
        tags = question.get("skill_tags") if isinstance(question.get("skill_tags"), list) else []
        clean_tags = [tag for tag in tags if isinstance(tag, str) and tag.strip()]
        output.append(
            {
                "question_id": question.get("question_id"),
                "question_type": question.get("question_type"),
                "problem_text": question.get("problem_text"),
                "problem_text_full": question.get("problem_text_full"),
                "sub_questions": question.get("sub_questions") if isinstance(question.get("sub_questions"), list) else [],
                "skill_tags": clean_tags,
                "skill_tag_details": [
                    {
                        "id": tag,
                        "name": tag_name_map.get(tag, tag),
                    }
                    for tag in clean_tags
                ],
            }
        )
    return output


def _parse_non_image_inputs(args: argparse.Namespace) -> Tuple[List[Any], str]:
    if args.questions_json:
        payload = _load_json(Path(args.questions_json))
        return _extract_question_list(payload), "questions_json"
    if args.paper_text_file:
        raw_text = Path(args.paper_text_file).read_text(encoding="utf-8")
        return _split_questions_from_text(raw_text), "paper_text_file"
    if args.paper_text:
        return _split_questions_from_text(args.paper_text), "paper_text"
    return [], "unknown"


def _extract_questions_from_images_or_pdf(
    service: DemoService,
    args: argparse.Namespace,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], List[str]]:
    warnings: List[str] = []
    paper_urls: List[str] = []

    if args.paper_pdf:
        pdf_path = Path(args.paper_pdf)
        if not pdf_path.exists():
            raise FileNotFoundError(f"pdf not found: {pdf_path}")
        paper_urls = _load_pdf_as_data_urls(pdf_path, dpi=args.pdf_dpi, max_pages=args.pdf_max_pages)
    elif args.paper_image:
        image_paths = [Path(item) for item in args.paper_image]
        missing = [str(path) for path in image_paths if not path.exists()]
        if missing:
            raise FileNotFoundError(f"image not found: {missing}")
        paper_urls = [_load_image_as_data_url(path) for path in image_paths]

    if not paper_urls:
        raise ValueError("no valid image pages prepared from --paper-pdf/--paper-image")

    question_candidates = _extract_points_from_nodes(service.nodes)
    questions, question_stats, missing_from_step1, question_repair_rounds, repaired_count = (
        service._run_question_analysis_parallel(
            paper_urls,
            question_candidates,
            warnings,
        )
    )
    extraction_stats = dict(question_stats)
    extraction_stats.update(
        {
            "paper_page_count": len(paper_urls),
            "missing_from_step1_count": len(missing_from_step1),
            "missing_from_step1": missing_from_step1,
            "question_repair_rounds": question_repair_rounds,
            "repaired_questions_count": repaired_count,
        }
    )
    return questions, extraction_stats, warnings


def _run(args: argparse.Namespace) -> Dict[str, Any]:
    input_mode = "unknown"
    raw_items: List[Any] = []
    extraction_stats: Optional[Dict[str, Any]] = None
    warnings: List[str] = []

    if args.paper_pdf or args.paper_image:
        service_for_extract = DemoService(
            config_path=Path(args.config),
            profile_name=args.profile,
            keyword_path=Path(args.key_word),
            mock_mode=False,
        )
        normalized_questions, extraction_stats, extract_warnings = _extract_questions_from_images_or_pdf(
            service_for_extract,
            args,
        )
        warnings.extend(extract_warnings)
        input_mode = "paper_pdf" if args.paper_pdf else "paper_image"
    else:
        raw_items, input_mode = _parse_non_image_inputs(args)
        normalized_questions = _normalize_questions(raw_items)

    if args.max_questions > 0:
        normalized_questions = _attach_question_metadata(normalized_questions[: args.max_questions])

    if not normalized_questions:
        raise ValueError("no valid questions found from input")

    if args.parse_only:
        return {
            "mode": "parse_only",
            "input_mode": input_mode,
            "input_question_count": len(raw_items) if raw_items else len(normalized_questions),
            "normalized_question_count": len(normalized_questions),
            "questions": _project_output_questions(normalized_questions, {}),
            "warnings": warnings,
            "question_extraction_stats": extraction_stats,
            "stats": {
                "question_count": len(normalized_questions),
                "tagged_question_count": 0,
                "group_count": 0,
                "group_pass_chunks": 0,
                "refine_pass_chunks": 0,
                "filtered_candidate_count_avg": 0,
            },
        }

    service = DemoService(
        config_path=Path(args.config),
        profile_name=args.profile,
        keyword_path=Path(args.key_word),
        mock_mode=False,
    )

    tagged_questions, stats = service._tag_questions_with_text_llm(normalized_questions, warnings)
    tag_name_map = _build_tag_name_map(service)

    return {
        "mode": "knowledge_tagging",
        "input_mode": input_mode,
        "input_question_count": len(raw_items) if raw_items else len(normalized_questions),
        "normalized_question_count": len(normalized_questions),
        "questions": _project_output_questions(tagged_questions, tag_name_map),
        "warnings": warnings,
        "question_extraction_stats": extraction_stats,
        "stats": stats,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Demo: recognize knowledge points for input paper questions using demo_server knowledge-tagging flow."
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--questions-json", help="Path to JSON containing `questions`/`question_analysis` list or a raw list.")
    input_group.add_argument("--paper-text-file", help="Path to plain text paper content. Questions are split by lines like `1.` `2)` `3、`.")
    input_group.add_argument("--paper-text", help="Inline plain text paper content.")
    input_group.add_argument("--paper-pdf", help="Path to paper PDF. The demo will render pages and run question extraction first.")
    input_group.add_argument("--paper-image", nargs="+", help="One or more paper image paths. Supports png/jpg/jpeg/bmp/webp/tif/tiff.")

    parser.add_argument("--config", default="llm_config.json", help="LLM config path (default: llm_config.json).")
    parser.add_argument("--profile", default=None, help="Profile name in llm_config.json (default uses config defaults.profile).")
    parser.add_argument("--key-word", default="key_word.json", help="Knowledge graph path (default: key_word.json).")
    parser.add_argument("--max-questions", type=int, default=0, help="Only keep first N normalized questions (0 means all).")
    parser.add_argument("--pdf-dpi", type=int, default=180, help="PDF render DPI when using --paper-pdf (default: 180).")
    parser.add_argument("--pdf-max-pages", type=int, default=0, help="Max pages to read from PDF (0 means all).")
    parser.add_argument("--parse-only", action="store_true", help="Only parse/normalize input questions without calling LLM.")
    parser.add_argument("--output", default=None, help="Optional output JSON file path.")
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    result = _run(args)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.write_text(text, encoding="utf-8")
        print(f"saved result to: {output_path}")
    else:
        print(text)


if __name__ == "__main__":
    main()
