from __future__ import annotations

import base64
import re
from typing import List, Optional, Any

# Optional runtime dependencies
try:
    import numpy as np
except Exception as exc:  # pragma: no cover - optional runtime dependency
    np = None  # type: ignore[assignment]
    _NUMPY_IMPORT_ERROR = str(exc)
else:
    _NUMPY_IMPORT_ERROR = ""
try:
    import cv2
except Exception as exc:  # pragma: no cover - optional runtime dependency
    cv2 = None  # type: ignore[assignment]
    _CV2_IMPORT_ERROR = str(exc)
else:
    _CV2_IMPORT_ERROR = ""
try:
    import fitz  # type: ignore[import-not-found]
except Exception as exc:  # pragma: no cover - optional runtime dependency
    fitz = None  # type: ignore[assignment]
    _PYMUPDF_IMPORT_ERROR = str(exc)
else:
    _PYMUPDF_IMPORT_ERROR = ""

_DATA_URL_PATTERN = re.compile(r"^data:(?P<mime>[A-Za-z0-9.+/-]+);base64,(?P<data>.+)$", flags=re.S)


def _decode_data_url_payload(data_url: str) -> tuple[str, bytes]:
    if not isinstance(data_url, str):
        raise ValueError("data_url must be string")
    match = _DATA_URL_PATTERN.match(data_url.strip())
    if not match:
        raise ValueError("invalid data_url format")
    mime = match.group("mime").strip().lower()
    payload = match.group("data").strip()
    try:
        binary = base64.b64decode(payload, validate=False)
    except Exception as exc:
        raise ValueError(f"invalid data_url base64 payload: {exc}") from exc
    if not binary:
        raise ValueError("empty data_url payload")
    return mime, binary


def _decode_image_data_url(data_url: str) -> tuple[str, bytes]:
    mime, binary = _decode_data_url_payload(data_url)
    if not mime.startswith("image/"):
        raise ValueError("invalid data_url image format")
    subtype = mime.split("/", 1)[-1].strip().lower()
    return subtype, binary


def _image_suffix_from_mime(mime: str) -> str:
    subtype = mime.split("/")[-1].split("+")[0].strip().lower()
    mapping = {
        "jpeg": ".jpg",
        "jpg": ".jpg",
        "png": ".png",
        "webp": ".webp",
        "bmp": ".bmp",
        "tif": ".tif",
        "tiff": ".tiff",
    }
    return mapping.get(subtype, ".jpg")


def _image_bytes_to_data_url(image_bytes: bytes, mime: str = "jpeg") -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    normalized_mime = mime.strip().lower() if isinstance(mime, str) and mime.strip() else "jpeg"
    return f"data:image/{normalized_mime};base64,{encoded}"


def _pdf_bytes_to_image_data_urls(
    pdf_bytes: bytes,
    *,
    dpi: int = 144,
    max_pages: int = 0,
) -> List[str]:
    if fitz is None:
        raise RuntimeError(f"pdf render requires pymupdf: {_PYMUPDF_IMPORT_ERROR}")
    if not isinstance(pdf_bytes, (bytes, bytearray)) or not pdf_bytes:
        raise ValueError("pdf bytes is empty")
    doc = fitz.open(stream=bytes(pdf_bytes), filetype="pdf")
    try:
        page_count = int(getattr(doc, "page_count", 0) or 0)
        if page_count <= 0:
            return []
        target_pages = page_count if max_pages <= 0 else min(page_count, max_pages)
        zoom = max(72, int(dpi)) / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        output: List[str] = []
        for page_index in range(target_pages):
            page = doc.load_page(page_index)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            output.append(_image_bytes_to_data_url(pix.tobytes("jpeg", jpg_quality=80), "jpeg"))
        return output
    finally:
        doc.close()


def _mask_red_review_marks_data_url(data_url: str) -> str:
    if cv2 is None:
        raise RuntimeError(f"opencv unavailable: {_CV2_IMPORT_ERROR}")
    if np is None:
        raise RuntimeError(f"numpy unavailable: {_NUMPY_IMPORT_ERROR}")
    mime, image_bytes = _decode_image_data_url(data_url)
    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("failed to decode review mark image")
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    lower_red_1 = np.array([0, 60, 40], dtype=np.uint8)
    upper_red_1 = np.array([12, 255, 255], dtype=np.uint8)
    lower_red_2 = np.array([165, 60, 40], dtype=np.uint8)
    upper_red_2 = np.array([180, 255, 255], dtype=np.uint8)
    red_mask = cv2.inRange(hsv, lower_red_1, upper_red_1) | cv2.inRange(hsv, lower_red_2, upper_red_2)
    if np.count_nonzero(red_mask) == 0:
        return data_url
    cleaned = image.copy()
    cleaned[red_mask > 0] = 255
    ok, encoded = cv2.imencode(".jpg", cleaned, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("failed to encode review mark filtered image")
    output_mime = "jpeg" if mime in {"jpg", "jpeg"} else mime
    return _image_bytes_to_data_url(encoded.tobytes(), output_mime)


def _coerce_bbox_xyxy(value: Any) -> Optional[List[int]]:
    if isinstance(value, dict):
        if all(key in value for key in ("x1", "y1", "x2", "y2")):
            raw = [value.get("x1"), value.get("y1"), value.get("x2"), value.get("y2")]
        elif all(key in value for key in ("x", "y", "w", "h")):
            try:
                x = float(value.get("x"))
                y = float(value.get("y"))
                w = float(value.get("w"))
                h = float(value.get("h"))
            except Exception:
                return None
            raw = [x, y, x + w, y + h]
        else:
            return None
    elif isinstance(value, list) and len(value) == 4:
        raw = value
    else:
        return None
    try:
        x1, y1, x2, y2 = [int(round(float(item))) for item in raw]
    except Exception:
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]


def _clip_bbox_xyxy(bbox_xyxy: List[int], width: int, height: int) -> Optional[List[int]]:
    if len(bbox_xyxy) != 4:
        return None
    x1 = max(0, min(int(bbox_xyxy[0]), width))
    y1 = max(0, min(int(bbox_xyxy[1]), height))
    x2 = max(0, min(int(bbox_xyxy[2]), width))
    y2 = max(0, min(int(bbox_xyxy[3]), height))
    if x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]


def _bbox_iou(box_a: List[int], box_b: List[int]) -> float:
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    inter_w = max(0, inter_x2 - inter_x1)
    inter_h = max(0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter_area
    return inter_area / union if union > 0 else 0.0
