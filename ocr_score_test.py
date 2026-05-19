from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

from ocr_api import API_KEY, call_math_ocr


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def _iter_images(path: Path) -> Iterable[Path]:
    if path.is_file():
        if path.suffix.lower() in IMAGE_EXTS:
            yield path
        return
    for image_path in sorted(path.rglob("*")):
        if image_path.is_file() and image_path.suffix.lower() in IMAGE_EXTS:
            yield image_path


def _image_to_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _parse_score(text: str) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    if not text:
        return None, None, None
    # Match formats like 0/5, 0 / 5, or LaTeX \frac{0}{5}
    fraction_patterns = [
        r"(?P<score>\d+(?:\.\d+)?)\s*/\s*(?P<total>\d+(?:\.\d+)?)",
        r"\\frac\{(?P<score>\d+(?:\.\d+)?)\}\{(?P<total>\d+(?:\.\d+)?)\}",
    ]
    for pattern in fraction_patterns:
        match = re.search(pattern, text)
        if match:
            return (
                float(match.group("score")),
                float(match.group("total")),
                pattern,
            )
    return None, None, None


def _run_ocr(
    image_path: Path,
    api_key: str,
    prompt: Optional[str],
    timeout: int,
) -> Dict[str, object]:
    image_base64 = _image_to_base64(image_path)
    data = call_math_ocr(
        api_key=api_key,
        image_base64=image_base64,
        prompt=prompt,
        timeout=timeout,
    )
    text = data.get("result", "") if isinstance(data, dict) else ""
    score, total, pattern = _parse_score(text)
    return {
        "image": str(image_path),
        "ocr_text": text,
        "score": score,
        "total": total,
        "pattern": pattern,
        "raw_status": data.get("status") if isinstance(data, dict) else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test OCR score/total extraction on answer sheet images."
    )
    parser.add_argument(
        "--path",
        required=True,
        help="Image file or directory to test.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Max number of images to test (0 means no limit).",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Override API key; defaults to ocr_api.API_KEY.",
    )
    parser.add_argument(
        "--prompt",
        default=(
            "Extract the student's score and the total score shown in the image. "
            "If present, return it in the form score/total."
        ),
        help="Prompt to guide OCR output.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="OCR request timeout (seconds).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional JSON output path.",
    )
    args = parser.parse_args()

    target = Path(args.path)
    if not target.exists():
        raise SystemExit(f"path not found: {target}")

    api_key = args.api_key or API_KEY
    if not api_key:
        raise SystemExit("api_key is required (provide --api-key or set ocr_api.API_KEY)")

    results = []
    count = 0
    for image_path in _iter_images(target):
        results.append(_run_ocr(image_path, api_key, args.prompt, args.timeout))
        count += 1
        if args.limit > 0 and count >= args.limit:
            break

    for item in results:
        score = item.get("score")
        total = item.get("total")
        print(f"{item.get('image')}: score={score} total={total}")

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(
            json.dumps(results, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
