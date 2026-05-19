from __future__ import annotations

import io
import base64
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from langchain_runtime import LangChainAgentRuntime
from mineru_client import MinerUStandardClient
from tools.mineru_vlm_markdown_extract import (
    PageCorrection,
    correct_one_image,
    extract_questions_with_artifact,
    load_env_file,
)


def _load_profile(config_path: Path, profile_name: str | None) -> dict[str, Any]:
    """Load an LLM profile from llm_config.json."""
    from llm_knowledge_tagger import _load_llm_profile
    return _load_llm_profile(config_path, profile_name)


def _build_runtime(profile: dict[str, Any]) -> LangChainAgentRuntime:
    """Create a LangChainAgentRuntime from a profile dict."""
    return LangChainAgentRuntime(
        base_url=str(profile.get("base_url", "")).rstrip("/"),
        api_key=str(profile.get("api_key", "")),
        model=str(profile.get("model", "")),
        timeout=int(profile.get("timeout_sec", 120)),
        max_retries=int(profile.get("max_retries", 0)),
        backoff_base_sec=float(profile.get("backoff_base_sec", 1.0)),
        min_interval_sec=float(profile.get("min_interval_sec", 0.0)),
        use_responses_api=bool(profile.get("use_responses_api", False)),
        output_version=profile.get("output_version"),
    )


def _encode_image_data_url(content: bytes, mime: str = "image/jpeg") -> str:
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _is_blank_image(content: bytes) -> bool:
    """True for blank / single-tone / decorative crops that shouldn't attach to questions."""
    if not content:
        return False
    try:
        from PIL import Image as PILImage
        import numpy as np
    except ImportError:
        return False
    try:
        img = PILImage.open(io.BytesIO(content))
        img.thumbnail((256, 256))
        gray = img.convert("L")
        arr = np.asarray(gray, dtype=np.uint8)
        if arr.size == 0:
            return False
        std = float(arr.std())
        counts = np.bincount(arr.ravel(), minlength=256)
        top_ratio = float(counts.max()) / float(arr.size)
    except Exception:
        return False
    return std < 8.0 or top_ratio > 0.985


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _extract_image_name_from_block(block: dict) -> str:
    """Extract the image filename from a MinerU image block."""
    content = block.get("content")
    if not isinstance(content, dict):
        return ""
    image_source = content.get("image_source")
    if not isinstance(image_source, dict):
        return ""
    path = image_source.get("path", "")
    if not isinstance(path, str):
        return ""
    return Path(path).name


def _format_bbox(block: dict) -> str:
    """Format block bbox as compact y-range string, e.g. '(y:34-99)'."""
    bbox = block.get("bbox")
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return ""
    y1 = int(bbox[1])
    y2 = int(bbox[3])
    return f"(y:{y1}-{y2})"


def _extract_mineru_text(content_list_v2: list) -> str:
    """Extract readable text from MinerU content_list_v2 (flat list of block dicts).

    Annotates each block with its vertical position (y-range from bbox) so the
    LLM can use spatial proximity to associate images with nearby questions.
    """
    lines: list[str] = []

    def _extract_text_from_value(val: object) -> str:
        """Recursively find text strings inside nested dicts/lists."""
        if isinstance(val, str):
            return val.strip()
        if isinstance(val, list):
            return " ".join(s for item in val if (s := _extract_text_from_value(item)))
        if isinstance(val, dict):
            for key in ("content", "text", "paragraph_content"):
                if key in val:
                    v = val[key]
                    if isinstance(v, str):
                        return v.strip()
                    if isinstance(v, list):
                        return " ".join(s for item in v if (s := _extract_text_from_value(item)))
            return " ".join(s for v in val.values() if (s := _extract_text_from_value(v)))
        return ""

    def _process_block(block: dict) -> None:
        block_type = block.get("type", "unknown")
        content = block.get("content")
        text = _extract_text_from_value(content)
        if not text or len(text) <= 1:
            return
        bbox_suffix = _format_bbox(block)
        if block_type == "image" and not any('一' <= c <= '鿿' for c in text):
            img_name = _extract_image_name_from_block(block)
            if img_name:
                lines.append(f"[image: {img_name} {bbox_suffix}]")
            else:
                lines.append(f"[image {bbox_suffix}]")
        else:
            lines.append(f"[{block_type}] {text} {bbox_suffix}")

    for item in content_list_v2:
        if isinstance(item, list):
            for block in item:
                if isinstance(block, dict):
                    _process_block(block)
        elif isinstance(item, dict):
            _process_block(item)

    return "\n".join(lines)


def _crop_images_from_page(
    page_image_bytes: bytes,
    content_list_v2: list,
    layout: dict | None = None,
) -> list[tuple[str, bytes]]:
    """Crop question images from the original page image using bbox coordinates.

    MinerU's ZIP archive contains blank/near-blank image crops (likely a
    rendering or coordinate-mapping bug in the API).  Instead we read the bbox
    from content_list_v2 and crop directly from the original page image bytes.
    """
    images: list[tuple[str, bytes]] = []
    try:
        from PIL import Image as PILImage
    except ImportError:
        return images

    page = None  # lazy-load PIL image

    # If layout.json provides page dimensions, compute scale from PDF points.
    scale_x: float | None = None
    scale_y: float | None = None
    if isinstance(layout, dict):
        pdf_info = layout.get("pdf_info")
        if isinstance(pdf_info, list) and pdf_info:
            pi = pdf_info[0] if isinstance(pdf_info[0], dict) else {}
            pw = pi.get("page_width")
            ph = pi.get("page_height")
        else:
            pw, ph = None, None
        # fallback: derive from min/max bbox in preproc_blocks
        if not pw or not ph:
            max_x = 0
            max_y = 0
            for block in pdf_info if isinstance(pdf_info, list) else []:
                b = block.get("bbox") if isinstance(block, dict) else None
                if isinstance(b, (list, tuple)) and len(b) >= 4:
                    max_x = max(max_x, b[2])
                    max_y = max(max_y, b[3])
            pw = pw or max_x
            ph = ph or max_y
        if pw and ph and pw > 0 and ph > 0:
            page = PILImage.open(io.BytesIO(page_image_bytes))
            scale_x = page.width / pw
            scale_y = page.height / ph

    # If we couldn't get a reliable scale from layout, compute from
    # content_list_v2 bbox extents.
    if scale_x is None or scale_y is None:
        page = PILImage.open(io.BytesIO(page_image_bytes))
        max_x = 0
        max_y = 0
        for item in content_list_v2:
            blocks = item if isinstance(item, list) else [item]
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                bbox = block.get("bbox")
                if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                    max_x = max(max_x, bbox[2])
                    max_y = max(max_y, bbox[3])
        if max_x > 0 and max_y > 0:
            scale_x = page.width / max_x
            scale_y = page.height / max_y

    if scale_x is None or scale_y is None:
        return images

    # Collect image blocks with their names and bboxes
    for item in content_list_v2:
        blocks = item if isinstance(item, list) else [item]
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "image":
                continue
            bbox = block.get("bbox")
            if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
                continue
            img_name = _extract_image_name_from_block(block)
            if not img_name:
                continue

            # Scale bbox to original image pixel coordinates
            x1 = max(0, int(bbox[0] * scale_x))
            y1 = max(0, int(bbox[1] * scale_y))
            x2 = min(page.width, max(x1 + 1, int(bbox[2] * scale_x)))
            y2 = min(page.height, max(y1 + 1, int(bbox[3] * scale_y)))

            if x2 <= x1 or y2 <= y1:
                continue

            try:
                crop = page.crop((x1, y1, x2, y2))
                if crop.mode in ("RGBA", "P", "LA"):
                    crop = crop.convert("RGB")
                buf = io.BytesIO()
                crop.save(buf, format="JPEG", quality=92)
                img_bytes = buf.getvalue()
                if _is_blank_image(img_bytes):
                    continue
                images.append((img_name, img_bytes))
            except Exception:
                continue

    return images


LLM_QUESTION_PROMPT = """你正在分析一份试卷的 OCR 识别结果。下面是试卷每页的文本内容（含类型标记和纵向位置）。
请识别出试卷中的所有题目，并按格式输出 JSON 数组。

每道题必须包含：
- question_id: 题号（如 Q1, Q2）
- question_type: 题型（choice/fill/solve/essay/other）
- content: 完整的题目文本（含选项 A/B/C/D，移除其中的 [image: ...] 标记和位置标注）
- max_score: 满分（如果能推断出来，否则 null）
- page_index: 题目所在的页码（从 0 开始）
- sub_questions: 子题列表（如果没有则空数组）
- images_on_page: 该题关联的图片文件名列表

每行末尾的 (y:35-99) 是该块在页面上的纵向位置（像素坐标），数字越大越靠下。
[image: filename.jpg (y:100-150)] 标记表示在页面的 y=100 到 y=150 位置有一张配图。
图片与题目纵向位置重叠或相邻时，通常表示该图片属于该题。
请从 [image: ...] 标记中提取真实的图片文件名填入 images_on_page。
必须使用标记中的真实文件名，不要编造名称。

每页文本内容：
{page_texts}

只返回 JSON 数组，不要其他内容：
[
  {{
    "question_id": "Q1",
    "question_type": "choice",
    "content": "题目完整文本（已移除标记和位置）",
    "max_score": 5,
    "page_index": 0,
    "sub_questions": [],
    "images_on_page": ["a48912a4e480a81d9fe.jpg"]
  }}
]"""


VLM_MATCH_PROMPT = """以下是试卷中的一道题：

{question_content}

以下是该页 MinerU 提取的候选配图（按顺序编号 0、1、2…）。
请判断哪些配图是这道题的真实插图（题干所需的图形、函数曲线、几何图、表格、坐标系、实物示意图等）。

必须拒绝（不要返回索引）的情况：
1. 空白图、纯色图（全白、全灰、全黑、纯背景）；
2. 装饰性元素（边框、分割线、花纹、底纹）；
3. 印章、学校 / 出版社 logo、水印；
4. 答题卡条码、二维码、考号填涂区；
5. 页眉、页脚、页码、装订线；
6. 与题干内容明显无关的配图（属于其他题）。

如不确定一张图是否相关，倾向于拒绝。

只返回 JSON，不要其他文字。格式严格如下：
{{"related_image_indices": [0, 2]}}
若没有任何相关配图，返回 {{"related_image_indices": []}}"""


class MinerUExtractionService:
    """Orchestrate MinerU + LLM + VLM for question extraction and image matching."""

    def __init__(
        self,
        config_path: Path,
        *,
        vision_profile_name: str | None = None,
        text_profile_name: str | None = None,
    ):
        self.config_path = config_path
        load_env_file(config_path.parent / ".env")
        self.mineru_client = MinerUStandardClient(config_path)

        # Load LLM profiles
        resolved_text_profile_name = text_profile_name or self._resolve_text_profile_name()
        self.text_profile = _load_profile(config_path, resolved_text_profile_name)
        self.vision_profile = _load_profile(config_path, vision_profile_name)
        self.text_runtime = _build_runtime(self.text_profile)
        self.vision_runtime = _build_runtime(self.vision_profile)
        self.mineru_parallel_workers = 4

    def _resolve_text_profile_name(self) -> str | None:
        """Resolve the text profile name from config defaults."""
        try:
            raw = self.config_path.read_text(encoding="utf-8")
            cfg = json.loads(raw)
        except Exception:
            return None
        defaults = cfg.get("defaults", {})
        profile_name = defaults.get("profile", "vision_tagger")
        profiles = cfg.get("openai_profiles", {})
        profile = profiles.get(profile_name, {})
        return profile.get("text_profile") or "text_analysis"

    @staticmethod
    def _coerce_positive_int(value: Any, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    def _run_mineru_on_page(self, page_idx: int, pf: dict, *, isolated_client: bool) -> dict:
        """Run MinerU Markdown parsing and VLM correction for one page."""
        local_path = str(pf.get("local_path") or "")
        if not local_path:
            return {
                "page_index": page_idx, "full_text": "[error] missing local_path",
                "raw_markdown": "",
                "corrected_markdown": "",
                "images": [], "has_error": True,
            }

        mineru_client = self.mineru_client
        owns_client = False
        config_path = getattr(self, "config_path", None)
        max_attempts = self._coerce_positive_int(getattr(self, "mineru_page_max_attempts", 3), 3)
        attempts_made = 0

        try:
            if isolated_client and isinstance(config_path, Path):
                mineru_client = MinerUStandardClient(config_path)
                owns_client = True

            image_path = Path(local_path)
            for attempt in range(1, max_attempts + 1):
                attempts_made = attempt
                try:
                    correction = correct_one_image(
                        image_path=image_path,
                        mineru_client=mineru_client,
                        vision_runtime=self.vision_runtime,
                        vision_profile=self.vision_profile,
                        output_dir=image_path.parent.parent / "mineru_markdown",
                    )
                    break
                except Exception:
                    if attempt >= max_attempts:
                        raise
        except Exception as exc:
            return {
                "page_index": page_idx, "full_text": f"[error] {exc}",
                "raw_markdown": "",
                "corrected_markdown": "",
                "images": [], "has_error": True,
                "retry_attempts": attempts_made,
            }
        finally:
            if owns_client:
                mineru_client.close()

        images: list[tuple[str, bytes]] = []
        for asset_path in correction.asset_paths:
            try:
                name = asset_path.relative_to(correction.raw_markdown_path.parent).as_posix()
            except ValueError:
                name = asset_path.name
            try:
                images.append((name, asset_path.read_bytes()))
            except OSError:
                continue
        try:
            raw_markdown = correction.raw_markdown_path.read_text(encoding="utf-8")
        except OSError:
            raw_markdown = ""

        return {
            "page_index": page_idx,
            "full_text": correction.markdown,
            "raw_markdown": raw_markdown,
            "corrected_markdown": correction.markdown,
            "raw_markdown_path": str(correction.raw_markdown_path),
            "corrected_markdown_path": str(correction.corrected_markdown_path),
            "source_image": str(correction.source_image),
            "asset_paths": [str(path) for path in correction.asset_paths],
            "images": images,
            "has_error": False,
            "retry_attempts": attempts_made,
        }

    def _run_mineru_on_pages(self, paper_files: list[dict]) -> list[dict]:
        """Step 1: Run per-page MinerU+VLM work in parallel, then return pages in order."""
        page_jobs = [(page_idx, pf) for page_idx, pf in enumerate(paper_files) if str(pf.get("local_path") or "")]
        if len(page_jobs) <= 1:
            return [self._run_mineru_on_page(page_idx, pf, isolated_client=False) for page_idx, pf in page_jobs]

        max_workers = min(len(page_jobs), max(1, int(getattr(self, "mineru_parallel_workers", 4) or 4)))
        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(self._run_mineru_on_page, page_idx, pf, isolated_client=True)
                for page_idx, pf in page_jobs
            ]
            for future in as_completed(futures):
                results.append(future.result())
        return sorted(results, key=lambda item: int(item.get("page_index", 0)))

    @staticmethod
    def _page_corrections_from_results(page_results: list[dict]) -> list[PageCorrection]:
        corrections: list[PageCorrection] = []
        for pr in page_results:
            page_index = int(pr.get("page_index") or 0)
            corrected_path = Path(str(pr.get("corrected_markdown_path") or f"page_{page_index}.corrected.md"))
            raw_path = Path(str(pr.get("raw_markdown_path") or corrected_path))
            source_image = Path(str(pr.get("source_image") or f"page_{page_index}.png"))
            asset_paths = [
                Path(str(path))
                for path in pr.get("asset_paths", [])
                if isinstance(path, (str, Path))
            ]
            corrections.append(
                PageCorrection(
                    source_image=source_image,
                    raw_markdown_path=raw_path,
                    corrected_markdown_path=corrected_path,
                    asset_paths=asset_paths,
                    markdown=str(pr.get("corrected_markdown") or pr.get("full_text") or ""),
                )
            )
        return corrections

    @staticmethod
    def _fold_sub_questions_into_content(content: str, sub_questions: Any) -> str:
        if not isinstance(sub_questions, list):
            return content

        merged = content.rstrip()
        seen = {merged} if merged else set()
        for sub_question in sub_questions:
            label = ""
            text = ""
            if isinstance(sub_question, str):
                text = sub_question.strip()
            elif isinstance(sub_question, dict):
                for key in ("sub_text", "content_markdown", "content", "problem_text", "text"):
                    value = sub_question.get(key)
                    if isinstance(value, str) and value.strip():
                        text = value.strip()
                        break
                for key in ("sub_question_id", "question_id", "question_no", "id"):
                    value = sub_question.get(key)
                    if isinstance(value, str) and value.strip():
                        label = value.strip()
                        break

            if label and text and label not in text:
                text = f"{label} {text}"
            if not text or text in seen or text in merged:
                continue
            seen.add(text)
            merged = f"{merged}\n{text}" if merged else text
        return merged

    @staticmethod
    def _normalize_markdown_questions(raw_questions: list[dict]) -> list[dict]:
        normalized: list[dict] = []
        for idx, item in enumerate(raw_questions, start=1):
            if not isinstance(item, dict):
                continue
            q = dict(item)
            q.setdefault("question_id", f"Q{idx}")
            q.setdefault("question_no", str(idx))
            q.setdefault("question_type", "other")
            content = q.get("content_markdown") or q.get("content") or q.get("problem_text") or ""
            q["content"] = str(content)
            q["content"] = MinerUExtractionService._fold_sub_questions_into_content(
                q["content"],
                q.get("sub_questions"),
            )
            image_refs = q.get("image_refs") or q.get("images_on_page") or q.get("matched_image_ids") or []
            if not isinstance(image_refs, list):
                image_refs = []
            image_refs = _dedupe_strings([str(ref) for ref in image_refs if isinstance(ref, str)])
            q["image_refs"] = image_refs
            q["images_on_page"] = image_refs
            q["matched_image_ids"] = image_refs
            q["sub_questions"] = []
            # Merge options into content if present (choice/fill-in questions)
            options = q.get("options")
            if isinstance(options, dict) and options:
                for key in sorted(str(k) for k in options.keys()):
                    opt_text = str(options[key]).strip()
                    line = f"{key}. {opt_text}"
                    if opt_text and line not in q["content"]:
                        q["content"] = q["content"] + "\n" + line
            q.setdefault("raw", dict(item))
            normalized.append(q)
        return normalized

    def _llm_parse_questions_with_artifact(self, page_results: list[dict]) -> tuple[list[dict], dict[str, Any]]:
        """Step 2: Extract structured questions and retain LLM inspection artifacts."""
        if any("corrected_markdown" in pr or "corrected_markdown_path" in pr for pr in page_results):
            try:
                artifact = extract_questions_with_artifact(
                    page_corrections=self._page_corrections_from_results(page_results),
                    text_runtime=self.text_runtime,
                    text_profile=self.text_profile,
                )
            except Exception as exc:
                raise RuntimeError(f"LLM question parsing failed: {exc}") from exc
            questions = self._normalize_markdown_questions(artifact.questions if isinstance(artifact.questions, list) else [])
            return questions, {
                "prompt": artifact.prompt,
                "raw_response": artifact.raw_response,
                "parsed_payload": artifact.parsed_payload,
                "normalized_questions": questions,
            }

        # Legacy fallback for callers still passing OCR text only.
        # Build page texts for the prompt
        page_texts_parts: list[str] = []
        all_images_on_pages: dict[int, list[str]] = {}
        for pr in page_results:
            pi = pr["page_index"]
            page_texts_parts.append(f"===== 第 {pi} 页 =====")
            page_texts_parts.append(pr["full_text"])
            img_names = [name for name, _ in pr.get("images", [])]
            all_images_on_pages[pi] = img_names
            if img_names:
                page_texts_parts.append(f"[page images: {', '.join(img_names)}]")

        prompt_text = LLM_QUESTION_PROMPT.format(page_texts="\n".join(page_texts_parts))
        max_tokens = int(self.text_profile.get("max_tokens", 8192))
        try:
            raw = self.text_runtime.invoke_json(
                prompt=prompt_text,
                data_urls=[],
                max_tokens=max_tokens,
                enable_thinking=False,
                thinking=None,
                reasoning_effort=None,
                detail=None,
            )
            questions = json.loads(raw)
            if not isinstance(questions, list):
                questions = []
        except Exception as exc:
            raise RuntimeError(f"LLM question parsing failed: {exc}") from exc

        # Attach image bytes reference for VLM matching
        img_by_page_and_name: dict[int, dict[str, bytes]] = {}
        for pr in page_results:
            pi = pr["page_index"]
            img_by_page_and_name[pi] = {}
            for name, img_bytes in pr.get("images", []):
                img_by_page_and_name[pi][name] = img_bytes

        for q in questions:
            pi = q.get("page_index", 0)
            image_names = q.get("images_on_page", [])
            q["_candidate_images"] = []
            for name in image_names:
                if name in img_by_page_and_name.get(pi, {}):
                    q["_candidate_images"].append({
                        "name": name,
                        "bytes": img_by_page_and_name[pi][name],
                    })

        return questions, {
            "prompt": prompt_text,
            "raw_response": raw,
            "parsed_payload": {"questions": questions},
            "normalized_questions": questions,
        }

    def _llm_parse_questions(self, page_results: list[dict]) -> list[dict]:
        """Step 2: Extract structured questions from corrected Markdown pages."""
        questions, _artifact = self._llm_parse_questions_with_artifact(page_results)
        return questions

    def step1_parse(self, paper_files: list[dict]) -> list[dict]:
        """Run MinerU on each paper page. Returns page results."""
        return self._run_mineru_on_pages(paper_files)

    def step2_llm_parse(self, page_results: list[dict]) -> list[dict]:
        """LLM text -> structured questions."""
        return self._llm_parse_questions(page_results)

    def step2_llm_parse_with_artifact(self, page_results: list[dict]) -> tuple[list[dict], dict[str, Any]]:
        """LLM text -> structured questions plus inspectable raw artifacts."""
        return self._llm_parse_questions_with_artifact(page_results)

    def step3_vlm_match(self, questions: list[dict]) -> list[dict]:
        """Compatibility step: Markdown correction already places image refs."""
        for q in questions:
            image_refs = q.get("matched_image_ids") or q.get("image_refs") or q.get("images_on_page") or []
            if not isinstance(image_refs, list):
                image_refs = []
            normalized = _dedupe_strings([str(ref) for ref in image_refs if isinstance(ref, str)])
            q["image_refs"] = normalized
            q["images_on_page"] = normalized
            q["matched_image_ids"] = normalized
            q.pop("_candidate_images", None)
        return questions

    def step4_save(
        self,
        *,
        project_id: str,
        questions: list[dict],
        page_results: list[dict],
        storage: Any,
        paper_repo: Any,
    ) -> dict[str, Any]:
        """Save all results to DB: questions, images, mappings."""
        total_images = 0
        matched_count = 0
        img_lookup: dict[int, dict[str, bytes]] = {}
        canonical_names: dict[int, dict[str, str]] = {}
        for pr in page_results:
            pi = pr["page_index"]
            img_lookup[pi] = {}
            canonical_names[pi] = {}
            for name, ib in pr.get("images", []):
                canonical = str(name)
                basename = Path(canonical).name
                img_lookup[pi][canonical] = ib
                img_lookup[pi][basename] = ib
                canonical_names[pi][canonical] = canonical
                canonical_names[pi][basename] = canonical
        for q in questions:
            pi = q.get("page_index", 0)
            image_names = q.get("matched_image_ids") or q.get("image_refs") or q.get("images_on_page") or []
            if not isinstance(image_names, list):
                image_names = []
            normalized_names: list[str] = []
            for image_name in image_names:
                if not isinstance(image_name, str):
                    continue
                canonical = canonical_names.get(pi, {}).get(image_name) or canonical_names.get(pi, {}).get(Path(image_name).name)
                if canonical:
                    normalized_names.append(canonical)
            normalized_names = _dedupe_strings(normalized_names)
            seen_hashes: set[str] = set()
            content_unique_names: list[str] = []
            for img_name in normalized_names:
                img_bytes = img_lookup.get(pi, {}).get(img_name)
                if img_bytes is None:
                    img_bytes = img_lookup.get(pi, {}).get(Path(str(img_name)).name)
                if img_bytes is None:
                    continue
                digest = hashlib.sha256(img_bytes).hexdigest()
                if digest in seen_hashes:
                    continue
                seen_hashes.add(digest)
                content_unique_names.append(img_name)
            normalized_names = content_unique_names
            q["image_refs"] = normalized_names
            q["images_on_page"] = normalized_names
            q["matched_image_ids"] = normalized_names

            for sort_idx, img_name in enumerate(normalized_names):
                img_bytes = img_lookup.get(pi, {}).get(img_name)
                if img_bytes is None:
                    img_bytes = img_lookup.get(pi, {}).get(Path(str(img_name)).name)
                if img_bytes is None:
                    continue
                saved = storage.save_job_file(
                    job_id=project_id, category="question_images",
                    original_name=img_name, content=img_bytes,
                    content_type="image/png" if img_name.lower().endswith(".png") else "image/jpeg",
                    index=total_images + 1,
                )
                file_id = paper_repo.add_project_file(
                    project_id=project_id, category=saved.category,
                    file_name=saved.file_name, local_path=saved.local_path,
                    content_type=saved.content_type, size_bytes=saved.size_bytes,
                )
                total_images += 1
                paper_repo.save_question_image(
                    project_id=project_id,
                    question_id=q.get("question_id", ""),
                    file_id=file_id, page_index=pi, sort_order=sort_idx,
                )
                matched_count += 1
        paper_repo.save_questions(project_id=project_id, questions=questions)
        # Status transition is the caller's responsibility (see ADR-0006).
        return {"question_count": len(questions), "total_images": total_images, "matched_count": matched_count}

    def _vlm_match_images(self, questions: list[dict]) -> list[dict]:
        """Step 3: Use VLM to match images to questions."""
        detail = str(self.vision_profile.get("detail") or "low")
        max_tokens = int(self.vision_profile.get("max_tokens", 4096))

        for q in questions:
            candidates = q.get("_candidate_images", [])
            if not candidates:
                q["matched_image_ids"] = []
                continue

            # Build data URLs for VLM
            data_urls = []
            for img in candidates:
                mime = "image/png" if str(img["name"]).lower().endswith(".png") else "image/jpeg"
                data_urls.append(_encode_image_data_url(img["bytes"], mime))

            prompt_text = VLM_MATCH_PROMPT.format(question_content=q.get("content", ""))

            try:
                raw = self.vision_runtime.invoke_json(
                    prompt=prompt_text,
                    data_urls=data_urls,
                    max_tokens=max_tokens,
                    enable_thinking=False,
                    thinking=None,
                    reasoning_effort=None,
                    detail=detail,
                )
                result = json.loads(raw)
                indices = result.get("related_image_indices", [])
                q["matched_image_ids"] = [candidates[i]["name"] for i in indices if i < len(candidates)]
            except Exception:
                q["matched_image_ids"] = []

        return questions

    def extract_questions_with_images(
        self,
        *,
        project_id: str,
        paper_files: list[dict],
        storage: Any,
        paper_repo: Any,
    ) -> dict[str, Any]:
        """Full pipeline: MinerU → LLM → VLM → save results."""
        # Step 1: MinerU
        page_results = self._run_mineru_on_pages(paper_files)
        if not page_results:
            raise ValueError("no paper pages processed")

        # Step 2: LLM parse questions
        questions = self._llm_parse_questions(page_results)

        # Step 3: VLM match images
        questions = self._vlm_match_images(questions)

        # Step 4: Save results
        total_images = 0
        matched_count = 0

        for q in questions:
            pi = q.get("page_index", 0)
            # Save matched images
            matched_names = q.get("matched_image_ids", [])
            for sort_idx, img_name in enumerate(matched_names):
                # Find the image bytes from page results
                img_bytes = None
                for pr in page_results:
                    if pr["page_index"] == pi:
                        for name, ib in pr.get("images", []):
                            if name == img_name:
                                img_bytes = ib
                                break
                if img_bytes is None:
                    continue

                saved = storage.save_job_file(
                    job_id=project_id,
                    category="question_images",
                    original_name=img_name,
                    content=img_bytes,
                    content_type="image/jpeg" if not img_name.lower().endswith(".png") else "image/png",
                    index=total_images + 1,
                )
                file_id = paper_repo.add_project_file(
                    project_id=project_id,
                    category=saved.category,
                    file_name=saved.file_name,
                    local_path=saved.local_path,
                    content_type=saved.content_type,
                    size_bytes=saved.size_bytes,
                )
                total_images += 1

                paper_repo.save_question_image(
                    project_id=project_id,
                    question_id=q.get("question_id", f"Q{q.get('page_index', 0) + 1}"),
                    file_id=file_id,
                    page_index=pi,
                    sort_order=sort_idx,
                )
                matched_count += 1

        # Save questions
        paper_repo.save_questions(project_id=project_id, questions=questions)
        # Status transition is the caller's responsibility (see ADR-0006).

        return {
            "question_count": len(questions),
            "total_images": total_images,
            "matched_count": matched_count,
        }
LLM_QUESTION_PROMPT = (
    "Group by parent question/main problem only. One JSON item must represent one parent question.\n"
    "Do not output sub-questions like (1)/(2) as independent question items.\n"
    "Put all sub-question text into content in original order. Keep sub_questions as [].\n\n"
    + LLM_QUESTION_PROMPT
)
