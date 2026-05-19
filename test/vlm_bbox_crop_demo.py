from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from bbox_crop_tool import Box, crop_records
from llm_image_demo import DEFAULT_CONFIG_PATH, call_vlm_with_image, load_llm_profile, parse_model_text


def _extract_json_like(text: str) -> Any:
    text = text.strip()
    if not text:
        raise ValueError("model response is empty")
    fenced = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    candidates = fenced + [text]
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        for start, end in (("{", "}"), ("[", "]")):
            start_idx = candidate.find(start)
            end_idx = candidate.rfind(end)
            if start_idx >= 0 and end_idx > start_idx:
                snippet = candidate[start_idx : end_idx + 1]
                try:
                    return json.loads(snippet)
                except json.JSONDecodeError:
                    continue
    raise ValueError("failed to parse JSON from model response")


def _build_prompt(*, width: int, height: int, user_prompt: Optional[str], max_regions: int) -> str:
    task = user_prompt.strip() if isinstance(user_prompt, str) and user_prompt.strip() else "找出图中少量题目的区域"
    return (
        "你是一个图片区域定位助手。请根据用户要求，在图片中找出对应区域，并只返回 JSON。\n"
        f"图片宽高: width={width}, height={height}\n"
        "坐标规则:\n"
        "1. 原点在左上角\n"
        "2. 返回整数像素坐标\n"
        "3. bbox 格式固定为 [x1, y1, x2, y2]\n"
        "4. 坐标必须落在图片范围内\n"
        "5. x2 > x1, y2 > y1\n"
        f"6. 最多返回 {max_regions} 个区域\n"
        "JSON 格式固定如下:\n"
        "{\n"
        '  "boxes": [\n'
        "    {\n"
        '      "label": "q1",\n'
        '      "bbox": [100, 120, 500, 760],\n'
        '      "confidence": 0.92,\n'
        '      "reason": "题号和作答区域清晰可见"\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "不要输出 markdown，不要解释，不要输出多余文字。\n"
        f"用户要求: {task}"
    )


def _coerce_box(raw_bbox: Any) -> Box:
    if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
        raise ValueError(f"invalid bbox: {raw_bbox}")
    values = [round(float(v)) for v in raw_bbox]
    x1, y1, x2, y2 = values
    return x1, y1, x2, y2


def _normalize_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        for key in ("boxes", "regions", "questions", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                items = value
                break
        else:
            items = [payload]
    else:
        raise ValueError("unexpected JSON payload from model")

    records: List[Dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        if not isinstance(label, str) or not label.strip():
            label = f"region_{index}"
        raw_bbox = item.get("bbox")
        if raw_bbox is None and all(key in item for key in ("x1", "y1", "x2", "y2")):
            raw_bbox = [item["x1"], item["y1"], item["x2"], item["y2"]]
        box = _coerce_box(raw_bbox)
        records.append(
            {
                "label": label.strip(),
                "bbox": [box[0], box[1], box[2], box[3]],
                "format": "xyxy",
                "confidence": item.get("confidence"),
                "reason": item.get("reason"),
            }
        )
    if not records:
        raise ValueError("no bbox records found in model output")
    return records


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Use VLM to detect bounding boxes and crop them.")
    parser.add_argument("--image", required=True, help="Input image path")
    parser.add_argument("--prompt", default="找出图片中的前3道题作答区域", help="Prompt describing target regions")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to llm_config.json")
    parser.add_argument("--profile", default=None, help="Profile name in openai_profiles")
    parser.add_argument("--max-regions", type=int, default=5, help="Maximum number of regions to ask the VLM to return")
    parser.add_argument("--margin", type=int, default=0, help="Expand bbox by N pixels on each side before cropping")
    parser.add_argument("--output-dir", default="test\\vlm_bbox_crops", help="Directory for crop outputs")
    parser.add_argument("--ext", default="png", help="Crop image extension")
    parser.add_argument("--save-bbox-json", default=None, help="Optional path to save normalized bbox JSON")
    parser.add_argument("--save-raw-json", default=None, help="Optional path to save raw VLM response JSON")
    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.is_file():
        raise SystemExit(f"image not found: {image_path}")
    width, height = Image.open(image_path).size

    profile = load_llm_profile(Path(args.config), args.profile)
    prompt = _build_prompt(width=width, height=height, user_prompt=args.prompt, max_regions=args.max_regions)
    response = call_vlm_with_image(profile, image_path, prompt)
    text = parse_model_text(response)
    payload = _extract_json_like(text)
    records = _normalize_payload(payload)

    crop_input: List[Tuple[Optional[str], Box]] = []
    for item in records:
        crop_input.append((item["label"], _coerce_box(item["bbox"])))

    crop_results = crop_records(
        image_path=image_path,
        records=crop_input,
        output_dir=Path(args.output_dir),
        margin=args.margin,
        ext=args.ext,
    )

    normalized_output = {
        "image": str(image_path),
        "image_size": {"width": width, "height": height},
        "prompt": args.prompt,
        "profile": profile["name"],
        "model": profile["model"],
        "boxes": records,
        "crops": crop_results,
    }

    if args.save_bbox_json:
        _save_json(Path(args.save_bbox_json), normalized_output)
    if args.save_raw_json:
        _save_json(Path(args.save_raw_json), response)

    print(json.dumps(normalized_output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
