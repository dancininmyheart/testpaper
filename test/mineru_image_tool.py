from __future__ import annotations

import argparse
import json
import os
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional

import requests

AGENT_BASE_URL = "https://mineru.net/api/v1/agent"
STANDARD_BASE_URL = "https://mineru.net/api/v4"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "mineru_output"
DEFAULT_CONFIG_PATH = Path(r"D:\project\testpaper\llm_config.json")
DEFAULT_AGENT_LANGUAGE = "ch"
DEFAULT_MODE = "standard"
DEFAULT_STANDARD_MODEL = "vlm"
DEFAULT_POLL_INTERVAL = 3.0
DEFAULT_TIMEOUT = 300.0
SUPPORTED_IMAGE_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".jp2",
    ".webp",
    ".gif",
    ".bmp",
}


class MinerUError(RuntimeError):
    """MinerU API 调用失败。"""


def _build_session(use_env_proxy: bool) -> requests.Session:
    session = requests.Session()
    session.trust_env = use_env_proxy
    return session


def _ensure_file_exists(file_path: Path) -> Path:
    resolved = file_path.expanduser().resolve()
    if not resolved.exists() or not resolved.is_file():
        raise SystemExit(f"文件不存在: {resolved}")
    return resolved


def _load_mineru_settings_from_config(config_path: Path, profile_name: Optional[str]) -> Dict[str, Any]:
    resolved = _ensure_file_exists(config_path)
    payload = json.loads(resolved.read_text(encoding="utf-8"))

    defaults = payload.get("defaults")
    if not profile_name and isinstance(defaults, dict):
        default_profile = defaults.get("mineru_profile")
        if not isinstance(default_profile, str) or not default_profile.strip():
            default_profile = defaults.get("profile")
        if isinstance(default_profile, str) and default_profile.strip():
            profile_name = default_profile.strip()

    mineru_block = payload.get("mineru")
    if isinstance(mineru_block, dict):
        profiles = mineru_block.get("profiles")
        if isinstance(profiles, dict) and profiles:
            if not profile_name:
                raise SystemExit(f"未找到默认 MinerU profile，请传 --profile 指定。配置文件: {resolved}")
            profile = profiles.get(profile_name)
            if not isinstance(profile, dict):
                raise SystemExit(f"配置文件中不存在 MinerU profile: {profile_name}")

            api_key = profile.get("api_key")
            if not isinstance(api_key, str) or not api_key.strip():
                raise SystemExit(f"MinerU profile {profile_name} 缺少 api_key")
            return {
                "profile_name": profile_name,
                "api_key": api_key.strip(),
                "base_url": str(profile.get("base_url") or "").strip(),
                "model_version": str(profile.get("model_version") or "").strip(),
                "language": str(profile.get("language") or "").strip(),
                "use_env_proxy": bool(profile.get("use_env_proxy", False)),
            }

    profiles = payload.get("openai_profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise SystemExit(f"配置文件缺少 mineru.profiles 或 openai_profiles: {resolved}")
    if not profile_name:
        raise SystemExit(f"未找到默认 profile，请传 --profile 指定。配置文件: {resolved}")

    profile = profiles.get(profile_name)
    if not isinstance(profile, dict):
        raise SystemExit(f"配置文件中不存在 profile: {profile_name}")

    api_key = profile.get("api_key")
    if not isinstance(api_key, str) or not api_key.strip():
        raise SystemExit(f"profile {profile_name} 缺少 api_key")
    return {
        "profile_name": profile_name,
        "api_key": api_key.strip(),
        "base_url": "",
        "model_version": "",
        "language": "",
        "use_env_proxy": False,
    }


def _guess_output_stem(file_path: Optional[Path], source_url: Optional[str], explicit_name: Optional[str]) -> str:
    if file_path is not None:
        return file_path.stem
    if explicit_name:
        return Path(explicit_name).stem
    if source_url:
        candidate = source_url.rstrip("/").split("/")[-1]
        if candidate:
            return Path(candidate).stem or "mineru_result"
    return "mineru_result"


def _json_or_error(response: requests.Response) -> Dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        detail = response.text.strip()
        if len(detail) > 500:
            detail = detail[:500] + "...(truncated)"
        raise MinerUError(f"响应不是合法 JSON, status={response.status_code}, body={detail}") from exc

    if response.status_code >= 400:
        raise MinerUError(
            f"HTTP 请求失败, status={response.status_code}, "
            f"msg={payload.get('msg')!r}, trace_id={payload.get('trace_id')!r}"
        )

    code = payload.get("code")
    if code not in (0, None):
        raise MinerUError(
            f"接口返回失败, code={code}, msg={payload.get('msg')!r}, trace_id={payload.get('trace_id')!r}"
        )
    return payload


def _request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    timeout: float,
) -> Dict[str, Any]:
    response = session.request(method=method, url=url, headers=headers, json=json_body, timeout=timeout)
    return _json_or_error(response)


def _download_text(session: requests.Session, url: str, timeout: float) -> str:
    response = session.get(url, timeout=timeout)
    if response.status_code >= 400:
        raise MinerUError(f"下载 Markdown 失败, status={response.status_code}, url={url}")
    response.encoding = response.encoding or "utf-8"
    return response.text


def _download_binary(session: requests.Session, url: str, destination: Path, timeout: float) -> Path:
    response = session.get(url, timeout=timeout, stream=True)
    if response.status_code >= 400:
        raise MinerUError(f"下载文件失败, status={response.status_code}, url={url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as fh:
        for chunk in response.iter_content(chunk_size=1024 * 256):
            if chunk:
                fh.write(chunk)
    return destination


def _save_json(destination: Path, payload: Dict[str, Any]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_agent_by_url(
    session: requests.Session,
    *,
    source_url: str,
    file_name: Optional[str],
    language: str,
    page_range: Optional[str],
    timeout: float,
) -> str:
    payload: Dict[str, Any] = {"url": source_url, "language": language}
    if file_name:
        payload["file_name"] = file_name
    if page_range:
        payload["page_range"] = page_range

    data = _request_json(
        session,
        "POST",
        f"{AGENT_BASE_URL}/parse/url",
        headers={"Content-Type": "application/json"},
        json_body=payload,
        timeout=timeout,
    )
    return str(data["data"]["task_id"])


def parse_agent_by_file(
    session: requests.Session,
    *,
    file_path: Path,
    language: str,
    page_range: Optional[str],
    timeout: float,
) -> str:
    payload: Dict[str, Any] = {"file_name": file_path.name, "language": language}
    if page_range:
        payload["page_range"] = page_range

    create_result = _request_json(
        session,
        "POST",
        f"{AGENT_BASE_URL}/parse/file",
        headers={"Content-Type": "application/json"},
        json_body=payload,
        timeout=timeout,
    )

    task_id = str(create_result["data"]["task_id"])
    file_url = str(create_result["data"]["file_url"])

    with file_path.open("rb") as fh:
        upload_response = session.put(file_url, data=fh, timeout=timeout)
    if upload_response.status_code not in (200, 201):
        raise MinerUError(f"文件上传失败, status={upload_response.status_code}, task_id={task_id}")
    return task_id


def poll_agent_result(
    session: requests.Session,
    *,
    task_id: str,
    timeout: float,
    poll_interval: float,
) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = _request_json(
            session,
            "GET",
            f"{AGENT_BASE_URL}/parse/{task_id}",
            timeout=timeout,
        )
        data = result.get("data", {})
        state = data.get("state")
        if state == "done":
            return result
        if state == "failed":
            raise MinerUError(
                f"Agent 解析失败, err_code={data.get('err_code')}, err_msg={data.get('err_msg')!r}, task_id={task_id}"
            )
        print(f"[agent] task_id={task_id} state={state}")
        time.sleep(poll_interval)

    raise MinerUError(f"Agent 轮询超时, task_id={task_id}, timeout={timeout}s")


def create_standard_task_by_url(
    session: requests.Session,
    *,
    token: str,
    source_url: str,
    model_version: str,
    language: str,
    is_ocr: bool,
    enable_formula: bool,
    enable_table: bool,
    page_ranges: Optional[str],
    data_id: Optional[str],
    no_cache: bool,
    cache_tolerance: int,
    timeout: float,
) -> str:
    payload: Dict[str, Any] = {
        "url": source_url,
        "model_version": model_version,
        "language": language,
        "is_ocr": is_ocr,
        "enable_formula": enable_formula,
        "enable_table": enable_table,
        "no_cache": no_cache,
        "cache_tolerance": cache_tolerance,
    }
    if page_ranges:
        payload["page_ranges"] = page_ranges
    if data_id:
        payload["data_id"] = data_id

    result = _request_json(
        session,
        "POST",
        f"{STANDARD_BASE_URL}/extract/task",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        json_body=payload,
        timeout=timeout,
    )
    return str(result["data"]["task_id"])


def create_standard_batch_by_file(
    session: requests.Session,
    *,
    token: str,
    file_path: Path,
    model_version: str,
    language: str,
    is_ocr: bool,
    enable_formula: bool,
    enable_table: bool,
    page_ranges: Optional[str],
    data_id: Optional[str],
    timeout: float,
) -> str:
    file_item: Dict[str, Any] = {"name": file_path.name, "is_ocr": is_ocr}
    if page_ranges:
        file_item["page_ranges"] = page_ranges
    if data_id:
        file_item["data_id"] = data_id

    payload: Dict[str, Any] = {
        "files": [file_item],
        "model_version": model_version,
        "language": language,
        "enable_formula": enable_formula,
        "enable_table": enable_table,
    }

    result = _request_json(
        session,
        "POST",
        f"{STANDARD_BASE_URL}/file-urls/batch",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        json_body=payload,
        timeout=timeout,
    )

    batch_id = str(result["data"]["batch_id"])
    file_urls = result["data"].get("file_urls")
    if not isinstance(file_urls, list) or not file_urls:
        raise MinerUError(f"未拿到上传链接, batch_id={batch_id}")

    with file_path.open("rb") as fh:
        upload_response = session.put(str(file_urls[0]), data=fh, timeout=timeout)
    if upload_response.status_code not in (200, 201):
        raise MinerUError(f"标准接口文件上传失败, status={upload_response.status_code}, batch_id={batch_id}")
    return batch_id


def poll_standard_task(
    session: requests.Session,
    *,
    token: str,
    task_id: str,
    timeout: float,
    poll_interval: float,
) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout
    headers = {"Authorization": f"Bearer {token}"}
    while time.monotonic() < deadline:
        result = _request_json(
            session,
            "GET",
            f"{STANDARD_BASE_URL}/extract/task/{task_id}",
            headers=headers,
            timeout=timeout,
        )
        data = result.get("data", {})
        state = data.get("state")
        if state == "done":
            return result
        if state == "failed":
            raise MinerUError(f"标准接口解析失败, err_msg={data.get('err_msg')!r}, task_id={task_id}")
        print(f"[standard] task_id={task_id} state={state}")
        time.sleep(poll_interval)

    raise MinerUError(f"标准接口轮询超时, task_id={task_id}, timeout={timeout}s")


def poll_standard_batch(
    session: requests.Session,
    *,
    token: str,
    batch_id: str,
    timeout: float,
    poll_interval: float,
) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout
    headers = {"Authorization": f"Bearer {token}"}
    while time.monotonic() < deadline:
        result = _request_json(
            session,
            "GET",
            f"{STANDARD_BASE_URL}/extract-results/batch/{batch_id}",
            headers=headers,
            timeout=timeout,
        )
        data = result.get("data", {})
        extract_results = data.get("extract_result")
        if isinstance(extract_results, list) and extract_results:
            first = extract_results[0]
            state = first.get("state")
            if state == "done":
                return result
            if state == "failed":
                raise MinerUError(f"标准接口批量解析失败, err_msg={first.get('err_msg')!r}, batch_id={batch_id}")
        else:
            state = None
        print(f"[standard] batch_id={batch_id} state={state}")
        time.sleep(poll_interval)

    raise MinerUError(f"标准接口批量轮询超时, batch_id={batch_id}, timeout={timeout}s")


def _extract_zip_if_needed(zip_path: Path, extract_dir: Path) -> Optional[Path]:
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(extract_dir)
    full_md = next((path for path in extract_dir.rglob("full.md")), None)
    return full_md


def run_agent_mode(args: argparse.Namespace, session: requests.Session) -> Dict[str, Any]:
    file_path = Path(args.file).resolve() if args.file else None
    if file_path is not None:
        task_id = parse_agent_by_file(
            session,
            file_path=file_path,
            language=args.language,
            page_range=args.page_range,
            timeout=args.request_timeout,
        )
    else:
        task_id = parse_agent_by_url(
            session,
            source_url=args.url,
            file_name=args.file_name,
            language=args.language,
            page_range=args.page_range,
            timeout=args.request_timeout,
        )

    result = poll_agent_result(
        session,
        task_id=task_id,
        timeout=args.poll_timeout,
        poll_interval=args.poll_interval,
    )
    data = result["data"]
    markdown_url = str(data["markdown_url"])
    markdown_text = _download_text(session, markdown_url, timeout=args.request_timeout)

    stem = _guess_output_stem(file_path, args.url, args.file_name)
    output_dir = Path(args.output_dir).resolve()
    markdown_path = output_dir / f"{stem}.md"
    json_path = output_dir / f"{stem}.agent.result.json"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown_text, encoding="utf-8")
    _save_json(json_path, result)

    return {
        "mode": "agent",
        "task_id": task_id,
        "state": data.get("state"),
        "markdown_url": markdown_url,
        "markdown_path": str(markdown_path),
        "result_json_path": str(json_path),
    }


def run_standard_mode(args: argparse.Namespace, session: requests.Session) -> Dict[str, Any]:
    config_settings = _load_mineru_settings_from_config(Path(args.config), args.profile)
    token = args.token or config_settings["api_key"] or os.getenv("MINERU_API_TOKEN")
    if not token:
        raise SystemExit("标准接口需要 --token，或在 llm_config.json 的 profile 中提供 api_key。")

    file_path = Path(args.file).resolve() if args.file else None
    if file_path is not None:
        batch_id = create_standard_batch_by_file(
            session,
            token=token,
            file_path=file_path,
            model_version=args.model_version,
            language=args.language,
            is_ocr=args.is_ocr,
            enable_formula=args.enable_formula,
            enable_table=args.enable_table,
            page_ranges=args.page_ranges,
            data_id=args.data_id,
            timeout=args.request_timeout,
        )
        result = poll_standard_batch(
            session,
            token=token,
            batch_id=batch_id,
            timeout=args.poll_timeout,
            poll_interval=args.poll_interval,
        )
        first = result["data"]["extract_result"][0]
        zip_url = str(first["full_zip_url"])
        identifier = batch_id
    else:
        task_id = create_standard_task_by_url(
            session,
            token=token,
            source_url=args.url,
            model_version=args.model_version,
            language=args.language,
            is_ocr=args.is_ocr,
            enable_formula=args.enable_formula,
            enable_table=args.enable_table,
            page_ranges=args.page_ranges,
            data_id=args.data_id,
            no_cache=args.no_cache,
            cache_tolerance=args.cache_tolerance,
            timeout=args.request_timeout,
        )
        result = poll_standard_task(
            session,
            token=token,
            task_id=task_id,
            timeout=args.poll_timeout,
            poll_interval=args.poll_interval,
        )
        zip_url = str(result["data"]["full_zip_url"])
        identifier = task_id

    stem = _guess_output_stem(file_path, args.url, args.file_name)
    output_dir = Path(args.output_dir).resolve()
    zip_path = output_dir / f"{stem}.zip"
    json_path = output_dir / f"{stem}.standard.result.json"
    _download_binary(session, zip_url, zip_path, timeout=args.request_timeout)
    _save_json(json_path, result)

    extracted_markdown_path = None
    if args.extract_zip:
        extract_dir = output_dir / stem
        extracted_markdown_path = _extract_zip_if_needed(zip_path, extract_dir)

    return {
        "mode": "standard",
        "id": identifier,
        "zip_url": zip_url,
        "zip_path": str(zip_path),
        "result_json_path": str(json_path),
        "extracted_markdown_path": str(extracted_markdown_path) if extracted_markdown_path else None,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MinerU 图片识别工具，默认使用标准 API 的 vlm 模式。")
    parser.add_argument(
        "--mode",
        choices=["agent", "standard"],
        default=DEFAULT_MODE,
        help="默认使用标准 API；如需免 Token 轻量模式可显式传 --mode agent。",
    )

    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--file", help="本地图片或文档路径")
    source_group.add_argument("--url", help="远程图片或文档 URL")

    parser.add_argument("--file-name", default=None, help="URL 模式下可显式传文件名，帮助接口判断类型")
    parser.add_argument("--language", default=DEFAULT_AGENT_LANGUAGE, help="识别语言，默认 ch")
    parser.add_argument("--page-range", default=None, help="Agent 模式页码范围，仅 PDF 生效，例如 1-10")
    parser.add_argument("--page-ranges", default=None, help="标准接口页码范围，例如 2,4-6")
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL, help="轮询间隔秒数")
    parser.add_argument("--poll-timeout", type=float, default=DEFAULT_TIMEOUT, help="轮询超时秒数")
    parser.add_argument("--request-timeout", type=float, default=60.0, help="单次 HTTP 请求超时秒数")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="输出目录")
    parser.add_argument("--use-env-proxy", action="store_true", help="默认禁用系统代理，传入后改为启用")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help=f"配置文件路径，默认 {DEFAULT_CONFIG_PATH}")
    parser.add_argument("--profile", default=None, help="配置文件中的 MinerU profile 名称，默认读取 defaults.mineru_profile")

    parser.add_argument("--token", default=None, help="标准接口 Token；不传时从 llm_config.json 的 profile.api_key 读取")
    parser.add_argument(
        "--model-version",
        choices=["pipeline", "vlm", "MinerU-HTML"],
        default=DEFAULT_STANDARD_MODEL,
        help="标准接口模型版本，默认 vlm",
    )
    parser.add_argument("--data-id", default=None, help="标准接口 data_id")
    parser.add_argument("--is-ocr", action="store_true", help="标准接口是否启用 OCR，默认关闭")
    parser.add_argument("--disable-formula", dest="enable_formula", action="store_false", help="关闭标准接口公式识别")
    parser.add_argument("--disable-table", dest="enable_table", action="store_false", help="关闭标准接口表格识别")
    parser.add_argument("--enable-formula", dest="enable_formula", action="store_true", help="开启标准接口公式识别，默认关闭")
    parser.add_argument("--no-cache", action="store_true", help="标准 URL 模式是否绕过缓存")
    parser.add_argument("--cache-tolerance", type=int, default=900, help="标准 URL 模式缓存容忍时间，默认 900 秒")
    parser.add_argument("--extract-zip", action="store_true", help="标准接口下载 zip 后自动解压")
    parser.set_defaults(enable_formula=False, enable_table=True)
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if args.file:
        file_path = _ensure_file_exists(Path(args.file))
        args.file = str(file_path)
        if args.mode == "agent":
            size_mb = file_path.stat().st_size / (1024 * 1024)
            if size_mb > 10:
                print(f"警告: 当前文件约 {size_mb:.2f}MB，Agent 轻量接口限制为 10MB。")
        if file_path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES:
            return

    if args.mode == "agent" and args.page_ranges:
        raise SystemExit("Agent 模式不支持 --page-ranges，请改用 --page-range。")
    if args.mode == "standard" and args.page_range:
        raise SystemExit("标准接口不支持 --page-range，请改用 --page-ranges。")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    _validate_args(args)

    session = _build_session(use_env_proxy=args.use_env_proxy)
    try:
        if args.mode == "agent":
            summary = run_agent_mode(args, session)
        else:
            summary = run_standard_mode(args, session)
    except MinerUError as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        session.close()

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
