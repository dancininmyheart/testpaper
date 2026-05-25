from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langchain_runtime import LangChainAgentRuntime
from llm_knowledge_tagger import _load_llm_profile
from mineru_client import MinerUStandardClient


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "llm_config.json"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs" / "mineru_vlm_markdown"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


@dataclass(frozen=True)
class MarkdownBundle:
    markdown_path: Path
    asset_paths: list[Path]
    archive_files: list[str]


@dataclass(frozen=True)
class MarkdownImageRef:
    source: str
    path: Path | None = None
    url: str | None = None


@dataclass(frozen=True)
class PageCorrection:
    source_image: Path
    raw_markdown_path: Path
    corrected_markdown_path: Path
    asset_paths: list[Path]
    markdown: str


@dataclass(frozen=True)
class QuestionExtractionArtifact:
    prompt: str
    raw_response: str
    parsed_payload: dict[str, Any]
    questions: list[dict[str, Any]]


def _safe_stem(path: Path) -> str:
    stem = path.stem.strip() or "image"
    return re.sub(r"[^\w.-]+", "_", stem, flags=re.UNICODE).strip("._") or "image"


def _is_image_path(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_SUFFIXES


def _safe_member_path(output_dir: Path, member_name: str) -> Path:
    normalized = member_name.replace("\\", "/").lstrip("/")
    target = (output_dir / normalized).resolve()
    root = output_dir.resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"unsafe archive member path: {member_name}")
    return target


def _pick_markdown_member(names: Iterable[str]) -> str:
    markdown_names = sorted(name for name in names if name.lower().endswith(".md"))
    if not markdown_names:
        raise ValueError("MinerU archive does not contain a markdown file")
    full_md = [name for name in markdown_names if Path(name).name.lower() == "full.md"]
    return sorted(full_md or markdown_names, key=lambda item: (len(Path(item).parts), len(item)))[0]


def extract_markdown_bundle(*, archive_bytes: bytes, output_dir: Path, stem: str) -> MarkdownBundle:
    page_dir = output_dir / stem
    page_dir.mkdir(parents=True, exist_ok=True)
    archive_files: list[str] = []
    asset_paths: list[Path] = []

    with zipfile.ZipFile(__import__("io").BytesIO(archive_bytes), "r") as archive:
        names = archive.namelist()
        markdown_member = _pick_markdown_member(names)
        file_names = [name.replace("\\", "/").lstrip("/") for name in names if not name.endswith("/")]
        first_parts = {name.split("/", 1)[0] for name in file_names if "/" in name}
        strip_prefix = next(iter(first_parts)) if len(first_parts) == 1 and len(first_parts) < len(file_names) else ""
        markdown_target: Path | None = None
        for name in names:
            if name.endswith("/"):
                continue
            archive_files.append(name)
            output_name = name.replace("\\", "/").lstrip("/")
            if strip_prefix and output_name.startswith(f"{strip_prefix}/"):
                output_name = output_name[len(strip_prefix) + 1 :]
            target = _safe_member_path(page_dir, output_name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
            if name == markdown_member:
                markdown_target = target
            if _is_image_path(target):
                asset_paths.append(target)

    if markdown_target is None:
        raise ValueError("selected markdown file was not extracted")
    return MarkdownBundle(
        markdown_path=markdown_target,
        asset_paths=sorted(asset_paths),
        archive_files=sorted(archive_files),
    )


_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*]\(([^)\n]+)\)")
_HTML_IMAGE_RE = re.compile(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"'][^>]*>", re.IGNORECASE)


def _clean_markdown_image_target(raw: str) -> str:
    text = raw.strip()
    if len(text) >= 2 and text[0] == "<" and text[-1] == ">":
        text = text[1:-1].strip()
    title_match = re.match(r"^(\S+)(?:\s+[\"'].*[\"'])$", text)
    return title_match.group(1) if title_match else text


def _is_remote_ref(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https", "data"}


def collect_markdown_image_refs(*, markdown: str, markdown_path: Path) -> list[MarkdownImageRef]:
    refs: list[MarkdownImageRef] = []
    seen: set[str] = set()
    raw_refs = [match.group(1) for match in _MARKDOWN_IMAGE_RE.finditer(markdown)]
    raw_refs.extend(match.group(1) for match in _HTML_IMAGE_RE.finditer(markdown))
    for raw in raw_refs:
        source = _clean_markdown_image_target(raw)
        key = source.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        if _is_remote_ref(source):
            refs.append(MarkdownImageRef(source=source, url=source))
            continue
        candidate = (markdown_path.parent / unquote(source)).resolve()
        if candidate.exists() and candidate.is_file() and _is_image_path(candidate):
            refs.append(MarkdownImageRef(source=source, path=candidate))
    return refs


def strip_markdown_model_response(raw: str) -> str:
    text = raw.strip()
    match = re.fullmatch(r"```(?:markdown|md)?\s*\n(.*)\n```", text, flags=re.IGNORECASE | re.DOTALL)
    return (match.group(1) if match else text).strip()


def parse_json_model_response(raw: str) -> Any:
    text = raw.strip()
    match = re.fullmatch(r"```(?:json)?\s*\n(.*)\n```", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        text = match.group(1).strip()
    return json.loads(text)


def image_to_data_url(path: Path) -> str:
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def load_env_file(env_path: Path) -> dict[str, str]:
    if not env_path.exists() or not env_path.is_file():
        return {}
    loaded: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value
        loaded[key] = value
    return loaded


def _build_runtime(profile: dict[str, Any]) -> LangChainAgentRuntime:
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


def _resolve_text_profile_name(config_path: Path, vision_profile_name: str | None, explicit_text_profile: str | None) -> str | None:
    if explicit_text_profile:
        return explicit_text_profile
    payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
    profiles = payload.get("openai_profiles", {})
    defaults = payload.get("defaults", {})
    if not vision_profile_name and isinstance(defaults, dict):
        vision_profile_name = defaults.get("profile")
    if isinstance(profiles, dict) and isinstance(vision_profile_name, str):
        vision_profile = profiles.get(vision_profile_name, {})
        if isinstance(vision_profile, dict) and isinstance(vision_profile.get("text_profile"), str):
            return vision_profile["text_profile"]
    return vision_profile_name


def _asset_label(markdown_path: Path, asset_path: Path) -> str:
    try:
        return asset_path.relative_to(markdown_path.parent).as_posix()
    except ValueError:
        return asset_path.name


def _prepare_image_inputs(
    *,
    source_image: Path,
    markdown_path: Path,
    markdown: str,
    asset_paths: list[Path],
) -> tuple[list[str], list[str]]:
    data_urls = [image_to_data_url(source_image)]
    labels = [f"0: original page image ({source_image.name})"]
    seen_assets: set[Path] = set()

    for ref in collect_markdown_image_refs(markdown=markdown, markdown_path=markdown_path):
        index = len(data_urls)
        if ref.url is not None:
            data_urls.append(ref.url)
            labels.append(f"{index}: markdown image reference {ref.source}")
        elif ref.path is not None and ref.path not in seen_assets:
            seen_assets.add(ref.path)
            data_urls.append(image_to_data_url(ref.path))
            labels.append(f"{index}: markdown image reference {ref.source}")

    for asset_path in asset_paths:
        if asset_path in seen_assets:
            continue
        index = len(data_urls)
        seen_assets.add(asset_path)
        rel = _asset_label(markdown_path, asset_path)
        data_urls.append(image_to_data_url(asset_path))
        labels.append(f"{index}: extracted MinerU image asset {rel}")

    return data_urls, labels


def _build_markdown_correction_prompt(*, markdown: str, image_labels: list[str]) -> str:
    labels = "\n".join(f"- {label}" for label in image_labels)
    return f"""You are correcting one Markdown page parsed from a Chinese exam image.

Inputs:
{labels}

Task:
1. Use the original page image as the source of truth.
2. Fix missing, garbled, or wrongly recognized text, formulas, options, question numbers, and section titles in the Markdown.
3. Move each Markdown image reference to the exact question it belongs to. Use only existing image paths already present in the Markdown or extracted asset labels.
4. Remove image references that are blank, decorative, or unrelated to any question.
5. Preserve normal Markdown syntax and relative image paths.

Return only the corrected Markdown content. Do not return explanations, JSON, code fences, or extra text.

Current Markdown:
```markdown
{markdown}
```"""


def _build_question_extraction_prompt(page_corrections: list[PageCorrection]) -> str:
    sections: list[str] = []
    for index, correction in enumerate(page_corrections):
        sections.append(
            "\n".join(
                [
                    f"===== page_index={index} source_image={correction.source_image.name} source_md={correction.corrected_markdown_path.name} =====",
                    correction.markdown,
                ]
            )
        )
    joined = "\n\n".join(sections)
    return f"""Extract structured exam questions from the corrected Markdown pages below.

Return only a JSON object with this shape:
{{
  "questions": [
    {{
      "question_id": "Q1",
      "question_no": "1",
      "question_type": "choice|fill|solve|essay|other",
      "content_markdown": "full question stem in Markdown, preserving image references",
      "options": {{"A": "...", "B": "..."}},
      "max_score": null,
      "page_index": 0,
      "source_image": "original image filename",
      "source_markdown": "corrected markdown filename",
      "image_refs": ["relative/or/remote/image/path.png"],
      "sub_questions": []
    }}
  ]
}}

Rules:
- Preserve all image references that belong to a question in both content_markdown and image_refs.
- Do not invent image paths.
- Split independent numbered questions into separate items.
- Group by parent question/main problem only. Do not output sub-questions like (1)/(2) as independent question items.
- Put sub-question text into the parent question's content_markdown in original order and keep sub_questions as [].
- Return valid JSON only.

Corrected pages:
{joined}"""


def correct_one_image(
    *,
    image_path: Path,
    mineru_client: MinerUStandardClient,
    vision_runtime: LangChainAgentRuntime,
    vision_profile: dict[str, Any],
    output_dir: Path,
) -> PageCorrection:
    stem = _safe_stem(image_path)
    _mineru_bundle, archive_bytes = mineru_client.run_file_archive(image_path)
    markdown_bundle = extract_markdown_bundle(
        archive_bytes=archive_bytes,
        output_dir=output_dir,
        stem=stem,
    )
    raw_markdown = markdown_bundle.markdown_path.read_text(encoding="utf-8")
    data_urls, labels = _prepare_image_inputs(
        source_image=image_path,
        markdown_path=markdown_bundle.markdown_path,
        markdown=raw_markdown,
        asset_paths=markdown_bundle.asset_paths,
    )
    prompt = _build_markdown_correction_prompt(markdown=raw_markdown, image_labels=labels)
    corrected = vision_runtime.invoke_text(
        prompt=prompt,
        data_urls=data_urls,
        max_tokens=int(vision_profile.get("max_tokens", 12000)),
        enable_thinking=False,
        thinking=vision_profile.get("thinking"),
        reasoning_effort=vision_profile.get("reasoning_effort"),
        detail=vision_profile.get("detail") or "high",
    )
    corrected_markdown = strip_markdown_model_response(corrected)
    corrected_path = markdown_bundle.markdown_path.parent / f"{stem}.corrected.md"
    corrected_path.write_text(corrected_markdown, encoding="utf-8")
    return PageCorrection(
        source_image=image_path,
        raw_markdown_path=markdown_bundle.markdown_path,
        corrected_markdown_path=corrected_path,
        asset_paths=markdown_bundle.asset_paths,
        markdown=corrected_markdown,
    )


def extract_questions_with_artifact(
    *,
    page_corrections: list[PageCorrection],
    text_runtime: LangChainAgentRuntime,
    text_profile: dict[str, Any],
) -> QuestionExtractionArtifact:
    prompt = _build_question_extraction_prompt(page_corrections)
    raw = text_runtime.invoke_json(
        prompt=prompt,
        data_urls=[],
        max_tokens=int(text_profile.get("max_tokens", 12000)),
        enable_thinking=False,
        thinking=text_profile.get("thinking"),
        reasoning_effort=text_profile.get("reasoning_effort"),
        detail=None,
    )
    parsed = parse_json_model_response(raw)
    if isinstance(parsed, list):
        parsed_payload = {"questions": parsed}
        questions = parsed
    elif isinstance(parsed, dict) and isinstance(parsed.get("questions"), list):
        parsed_payload = parsed
        questions = parsed["questions"]
    else:
        raise ValueError("question extraction did not return a JSON object with questions")
    return QuestionExtractionArtifact(
        prompt=prompt,
        raw_response=raw,
        parsed_payload=parsed_payload,
        questions=questions,
    )


def extract_questions(
    *,
    page_corrections: list[PageCorrection],
    text_runtime: LangChainAgentRuntime,
    text_profile: dict[str, Any],
) -> dict[str, Any]:
    artifact = extract_questions_with_artifact(
        page_corrections=page_corrections,
        text_runtime=text_runtime,
        text_profile=text_profile,
    )
    if set(artifact.parsed_payload.keys()) == {"questions"}:
        return {"questions": artifact.questions}
    if isinstance(artifact.parsed_payload, dict) and isinstance(artifact.parsed_payload.get("questions"), list):
        return artifact.parsed_payload
    raise ValueError("question extraction did not return a JSON object with questions")


def run_pipeline(
    *,
    images: list[Path],
    config_path: Path,
    output_dir: Path,
    env_file: Path | None,
    mineru_profile: str | None,
    vision_profile_name: str | None,
    text_profile_name: str | None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    load_env_file(env_file or (config_path.parent / ".env"))
    mineru_client = MinerUStandardClient(config_path, mineru_profile)
    vision_profile = _load_llm_profile(config_path, vision_profile_name)
    resolved_text_profile = _resolve_text_profile_name(config_path, vision_profile_name, text_profile_name)
    text_profile = _load_llm_profile(config_path, resolved_text_profile)
    vision_runtime = _build_runtime(vision_profile)
    text_runtime = _build_runtime(text_profile)

    try:
        corrections = [
            correct_one_image(
                image_path=image.resolve(),
                mineru_client=mineru_client,
                vision_runtime=vision_runtime,
                vision_profile=vision_profile,
                output_dir=output_dir,
            )
            for image in images
        ]
    finally:
        mineru_client.close()

    structured = extract_questions(
        page_corrections=corrections,
        text_runtime=text_runtime,
        text_profile=text_profile,
    )
    questions_path = output_dir / "questions.json"
    questions_path.write_text(json.dumps(structured, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "questions_path": str(questions_path),
        "question_count": len(structured.get("questions", [])),
        "pages": [
            {
                "source_image": str(item.source_image),
                "raw_markdown_path": str(item.raw_markdown_path),
                "corrected_markdown_path": str(item.corrected_markdown_path),
                "asset_count": len(item.asset_paths),
            }
            for item in corrections
        ],
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def _existing_image(path_text: str) -> Path:
    path = Path(path_text).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise argparse.ArgumentTypeError(f"image not found: {path}")
    if not _is_image_path(path):
        raise argparse.ArgumentTypeError(f"unsupported image suffix: {path}")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parse one or more images with MinerU VLM, correct Markdown with a VLM, then extract structured questions."
    )
    parser.add_argument("images", nargs="+", type=_existing_image, help="One or more local image files.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to llm_config.json.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for Markdown and JSON outputs.")
    parser.add_argument("--env-file", default=None, help="Path to .env; defaults to the config file directory.")
    parser.add_argument("--mineru-profile", default=None, help="MinerU profile name; defaults to defaults.mineru_profile.")
    parser.add_argument("--vision-profile", default=None, help="Vision model profile; defaults to defaults.profile.")
    parser.add_argument("--text-profile", default=None, help="Text model profile; defaults to the vision profile's text_profile.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config_path = Path(args.config).expanduser().resolve()
    if not config_path.exists():
        raise SystemExit(f"config not found: {config_path}")
    summary = run_pipeline(
        images=args.images,
        config_path=config_path,
        output_dir=Path(args.output_dir).expanduser().resolve(),
        env_file=Path(args.env_file).expanduser().resolve() if args.env_file else None,
        mineru_profile=args.mineru_profile,
        vision_profile_name=args.vision_profile,
        text_profile_name=args.text_profile,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
