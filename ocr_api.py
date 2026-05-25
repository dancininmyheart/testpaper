import base64
import json
from pathlib import Path
import requests
from typing import Optional, Dict, Any, Iterable


BASE_URL = "http://152.136.59.78:8001"
OCR_PATH = "/ocr"
API_KEY = ""

class OCRError(Exception):
    """封装 OCR 接口相关错误的自定义异常。"""
    pass


def call_math_ocr(
    api_key: str,
    image_url: Optional[str] = None,
    image_base64: Optional[str] = None,
    prompt: Optional[str] = None,
    timeout: int = 120,
) -> Dict[str, Any]:
    """
    调用 OCR 图片公式识别接口，将图片中的公式转换为 LaTeX。

    参数
    ----------
    api_key : str
        接口调用所需的 api_key（必填）。
    image_url : str, optional
        图片的公网 URL。
    image_base64 : str, optional
        图片的 Base64 编码字符串。
    prompt : str, optional
        识别提示语。如果不传，服务端默认为“请帮我把图片中的公式转为LaTex”。
    timeout : int, optional
        请求超时时间（秒），默认 120 秒。

    返回
    ----------
    dict
        接口完整响应的 JSON 字典，一般包含：
        - request_id: 本次请求唯一 ID
        - result: 识别出的 LaTeX 字符串
        - wait_time: 排队等待时间
        - processing_time: 模型处理时间
        - status: 请求状态（"success" 表示成功）
        - image_format: 服务器识别出的图片格式

    异常
    ----------
    ValueError
        当 image_url 和 image_base64 都未提供时抛出。
    OCRError
        HTTP 状态码非 200，或接口返回的 status 非 "success" 时抛出。
    """
    if not image_url and not image_base64:
        raise ValueError("必须在 image_url 和 image_base64 中至少提供一个。")

    url = BASE_URL + OCR_PATH

    payload: Dict[str, Any] = {
        "api_key": api_key,
    }

    # 两个字段都可传，后端优先使用 image_url
    if image_url:
        payload["image_url"] = image_url
    if image_base64:
        payload["image_base64"] = image_base64
    if prompt:
        payload["prompt"] = prompt

    try:
        response = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as e:
        raise OCRError(f"请求 OCR 服务失败: {e}") from e

    if response.status_code != 200:
        # 文档中列举的常见错误码：400/401/500/503/504 等:contentReference[oaicite:1]{index=1}
        raise OCRError(
            f"OCR 接口返回非 200 状态码: {response.status_code}, "
            f"body={response.text}"
        )

    try:
        data = response.json()
    except ValueError as e:
        raise OCRError(f"响应不是合法 JSON: {response.text}") from e

    # 文档中说明成功时 status == "success"
    if data.get("status") != "success":
        raise OCRError(f"OCR 接口返回失败状态: {data}")

    return data


def _iter_image_files(root_dir: str) -> Iterable[Path]:
    root = Path(root_dir)
    exts = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in exts:
            yield path


def _image_to_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def ocr_answer_sheet_crops(
    root_dir: str,
    api_key: Optional[str] = None,
    prompt: Optional[str] = None,
    timeout: int = 120,
    overwrite: bool = False,
    output_name: str = "ocr_results.json",
) -> Dict[str, Any]:
    """
    OCR all images under root_dir and write one JSON per student folder.
    The JSON file is saved in the student directory (parent of front/back).
    """
    results_index: Dict[str, Any] = {}
    if not api_key:
        api_key = API_KEY
    grouped: Dict[Path, list[Path]] = {}
    for image_path in _iter_image_files(root_dir):
        parent = image_path.parent
        if parent.name.lower() in {"front", "back"} and parent.parent != parent:
            student_dir = parent.parent
        else:
            student_dir = parent
        grouped.setdefault(student_dir, []).append(image_path)

    for student_dir, images in grouped.items():
        output_path = student_dir / output_name
        if output_path.exists() and not overwrite:
            results_index[str(student_dir)] = {
                "skipped": True,
                "output": str(output_path),
                "reason": "output exists",
            }
            continue

        folder_result: Dict[str, Any] = {
            "directory": str(student_dir),
            "results": {},
        }
        total = len(images)
        for idx, image_path in enumerate(sorted(images), start=1):
            rel_key = (
                str(image_path.relative_to(student_dir))
                if student_dir in image_path.parents
                else image_path.name
            )
            try:
                print(f"[{idx}/{total}] OCR {rel_key} ...")
                image_base64 = _image_to_base64(image_path)
                data = call_math_ocr(
                    api_key=api_key,
                    image_base64=image_base64,
                    prompt=prompt,
                    timeout=timeout,
                )
                folder_result["results"][rel_key] = {
                    "status": "success",
                    "result": data.get("result"),
                    "raw": data,
                }
                print(f"[{idx}/{total}] OCR {rel_key} done")
            except Exception as exc:  # noqa: BLE001
                folder_result["results"][rel_key] = {
                    "status": "error",
                    "error": str(exc),
                }
                print(f"[{idx}/{total}] OCR {rel_key} failed: {exc}")

        output_path.write_text(
            json.dumps(folder_result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[student] saved {output_path}")
        results_index[str(student_dir)] = {
            "skipped": False,
            "output": str(output_path),
            "count": len(images),
        }

    return results_index


if __name__ == "__main__":
    # 使用示例：通过 image_url 调用
    API_KEY = "sk_9f3A2KxR7MZQwD8hP5YcLJtV4BNeU6mS"
    IMAGE_URL = "https://statics.aiecnu.net/ocr-math/20250917/efa4486e-4a3b-4d61-952e-c5c890601dc0.png"

    result = call_math_ocr(
        api_key=API_KEY,
        image_url=IMAGE_URL,
        # image_base64="...",  # 如果用 Base64，在这里填
        # prompt="请帮我把图片中的公式转为LaTex",
    )
    print("LaTeX 结果:")
    print(result["result"])
