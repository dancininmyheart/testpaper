from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from PIL import Image


Box = Tuple[int, int, int, int]


def _parse_bbox_text(text: str, fmt: str) -> Box:
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must have 4 comma-separated numbers")
    numbers = [float(part) for part in parts]
    return _to_xyxy(numbers, fmt)


def _to_xyxy(values: List[float], fmt: str) -> Box:
    if fmt == "xyxy":
        x1, y1, x2, y2 = values
    elif fmt == "xywh":
        x, y, w, h = values
        x1, y1, x2, y2 = x, y, x + w, y + h
    else:
        raise ValueError(f"unsupported bbox format: {fmt}")
    return round(x1), round(y1), round(x2), round(y2)


def _clip_box(box: Box, width: int, height: int) -> Box:
    x1, y1, x2, y2 = box
    x1 = max(0, min(x1, width))
    y1 = max(0, min(y1, height))
    x2 = max(0, min(x2, width))
    y2 = max(0, min(y2, height))
    return x1, y1, x2, y2


def _normalize_box(box: Box) -> Box:
    x1, y1, x2, y2 = box
    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


def _expand_box(box: Box, margin: int) -> Box:
    if margin <= 0:
        return box
    x1, y1, x2, y2 = box
    return x1 - margin, y1 - margin, x2 + margin, y2 + margin


def _is_valid_box(box: Box) -> bool:
    x1, y1, x2, y2 = box
    return x2 > x1 and y2 > y1


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_bbox_records(payload: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield item
        return
    if isinstance(payload, dict):
        boxes = payload.get("boxes")
        if isinstance(boxes, list):
            for item in boxes:
                if isinstance(item, dict):
                    yield item
            return
        yield payload


def _record_to_box(record: Dict[str, Any], default_fmt: str) -> Tuple[Optional[str], Box]:
    label = record.get("label") if isinstance(record.get("label"), str) else None
    fmt = record.get("format") if isinstance(record.get("format"), str) else default_fmt

    if isinstance(record.get("bbox"), list) and len(record["bbox"]) == 4:
        values = [float(v) for v in record["bbox"]]
        return label, _to_xyxy(values, fmt)

    keys_xyxy = ("x1", "y1", "x2", "y2")
    if all(key in record for key in keys_xyxy):
        values = [float(record[key]) for key in keys_xyxy]
        return label, _to_xyxy(values, "xyxy")

    keys_xywh = ("x", "y", "w", "h")
    if all(key in record for key in keys_xywh):
        values = [float(record[key]) for key in keys_xywh]
        return label, _to_xyxy(values, "xywh")

    raise ValueError(f"invalid bbox record: {record}")


def _build_output_path(output_dir: Path, image_path: Path, index: int, label: Optional[str], ext: str) -> Path:
    safe_label = ""
    if label:
        safe_label = "_" + "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in label.strip())
    return output_dir / f"{image_path.stem}_{index:03d}{safe_label}.{ext}"


def _save_crop(image: Image.Image, box: Box, output_path: Path) -> None:
    crop = image.crop(box)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    crop.save(output_path)


def crop_records(
    *,
    image_path: Path,
    records: List[Tuple[Optional[str], Box]],
    output_dir: Path,
    margin: int = 0,
    ext: str = "png",
    output_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    if not image_path.is_file():
        raise FileNotFoundError(f"image not found: {image_path}")
    image = Image.open(image_path)
    width, height = image.size
    results: List[Dict[str, Any]] = []
    for index, (label, raw_box) in enumerate(records, start=1):
        box = _normalize_box(raw_box)
        box = _expand_box(box, margin)
        box = _clip_box(box, width, height)
        if not _is_valid_box(box):
            raise ValueError(f"invalid bbox after clipping: {raw_box}")
        if output_path is not None and len(records) == 1:
            save_path = output_path
        else:
            save_path = _build_output_path(output_dir, image_path, index, label, ext.lstrip("."))
        _save_crop(image, box, save_path)
        results.append(
            {
                "index": index,
                "label": label,
                "box": {"x1": box[0], "y1": box[1], "x2": box[2], "y2": box[3]},
                "output": str(save_path),
            }
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Crop image regions by bounding box.")
    parser.add_argument("--image", required=True, help="Input image path.")
    parser.add_argument("--bbox", help="Single bbox, e.g. 100,200,500,800")
    parser.add_argument("--bbox-json", help="JSON file containing one or more bboxes.")
    parser.add_argument("--format", choices=["xyxy", "xywh"], default="xyxy", help="BBox coordinate format.")
    parser.add_argument("--margin", type=int, default=0, help="Expand bbox by N pixels on each side.")
    parser.add_argument("--output", help="Output path for single bbox crop.")
    parser.add_argument("--output-dir", default="test\\bbox_crops", help="Output directory for batch crops.")
    parser.add_argument("--ext", default="png", help="Output image extension, e.g. png/jpg.")
    args = parser.parse_args()

    if not args.bbox and not args.bbox_json:
        raise SystemExit("either --bbox or --bbox-json is required")

    image_path = Path(args.image)
    if not image_path.is_file():
        raise SystemExit(f"image not found: {image_path}")

    image = Image.open(image_path)
    width, height = image.size

    records: List[Tuple[Optional[str], Box]] = []
    if args.bbox:
        records.append((None, _parse_bbox_text(args.bbox, args.format)))

    if args.bbox_json:
        payload = _load_json(Path(args.bbox_json))
        for record in _iter_bbox_records(payload):
            records.append(_record_to_box(record, args.format))

    if not records:
        raise SystemExit("no bbox records found")

    output_dir = Path(args.output_dir)
    results = crop_records(
        image_path=image_path,
        records=records,
        output_dir=output_dir,
        margin=args.margin,
        ext=args.ext,
        output_path=Path(args.output) if args.output else None,
    )
    for item in results:
        print(json.dumps(item, ensure_ascii=False))
    print(json.dumps({"saved": len(results), "image_size": {"width": width, "height": height}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
