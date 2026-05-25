from __future__ import annotations

import io
import json
import os
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional

import requests


DEFAULT_BASE_URL = "https://mineru.net/api/v4"
DEFAULT_MODEL_VERSION = "vlm"
DEFAULT_LANGUAGE = "ch"
DEFAULT_REQUEST_TIMEOUT_SEC = 60
DEFAULT_RESULT_TIMEOUT_SEC = 300
DEFAULT_POLL_INTERVAL_SEC = 3


class MinerUAPIError(RuntimeError):
    """MinerU 标准 API 调用失败。"""


def _ensure_file_exists(file_path: Path) -> Path:
    resolved = file_path.expanduser().resolve()
    if not resolved.exists() or not resolved.is_file():
        raise RuntimeError(f"file not found: {resolved}")
    return resolved


def load_mineru_config(config_path: Path, profile_name: Optional[str] = None) -> Dict[str, Any]:
    resolved = _ensure_file_exists(config_path)
    payload = json.loads(resolved.read_text(encoding="utf-8-sig"))

    defaults = payload.get("defaults")
    if not profile_name and isinstance(defaults, dict):
        default_profile = defaults.get("mineru_profile")
        if not isinstance(default_profile, str) or not default_profile.strip():
            default_profile = defaults.get("profile")
        if isinstance(default_profile, str) and default_profile.strip():
            profile_name = default_profile.strip()

    mineru = payload.get("mineru")
    if not isinstance(mineru, dict):
        raise RuntimeError(f"config missing mineru block: {resolved}")

    profiles = mineru.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise RuntimeError(f"config missing mineru.profiles block: {resolved}")
    if not profile_name:
        raise RuntimeError("mineru profile is required; set defaults.mineru_profile or pass profile_name")

    profile = profiles.get(profile_name)
    if not isinstance(profile, dict):
        raise RuntimeError(f"mineru profile not found: {profile_name}")

    api_key_env_raw = profile.get("api_key_env")
    api_key_env = api_key_env_raw.strip() if isinstance(api_key_env_raw, str) else ""
    api_key = os.getenv(api_key_env, "").strip() if api_key_env else ""
    if not api_key:
        api_key_raw = profile.get("api_key")
        api_key = api_key_raw.strip() if isinstance(api_key_raw, str) else ""
    if not api_key:
        if api_key_env:
            raise RuntimeError(f"mineru profile {profile_name} missing env var {api_key_env}")
        raise RuntimeError(f"mineru profile {profile_name} missing api_key_env or api_key")

    base_url = str(profile.get("base_url") or DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    return {
        "profile_name": profile_name,
        "api_key": api_key,
        "api_key_env": api_key_env,
        "base_url": base_url.rstrip("/"),
        "model_version": str(profile.get("model_version") or DEFAULT_MODEL_VERSION).strip() or DEFAULT_MODEL_VERSION,
        "language": str(profile.get("language") or DEFAULT_LANGUAGE).strip() or DEFAULT_LANGUAGE,
        "request_timeout_sec": float(profile.get("timeout_sec", DEFAULT_REQUEST_TIMEOUT_SEC)),
        "result_timeout_sec": float(profile.get("result_timeout_sec", DEFAULT_RESULT_TIMEOUT_SEC)),
        "poll_interval_sec": float(profile.get("poll_interval_sec", DEFAULT_POLL_INTERVAL_SEC)),
        "use_env_proxy": bool(profile.get("use_env_proxy", False)),
    }


def _json_or_error(response: requests.Response) -> Dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        detail = response.text.strip()
        if len(detail) > 500:
            detail = detail[:500] + "...(truncated)"
        raise MinerUAPIError(f"mineru response is not valid JSON, status={response.status_code}, body={detail}") from exc

    if response.status_code >= 400:
        raise MinerUAPIError(
            f"mineru request failed, status={response.status_code}, "
            f"msg={payload.get('msg')!r}, trace_id={payload.get('trace_id')!r}"
        )
    code = payload.get("code")
    if code not in (0, None):
        raise MinerUAPIError(
            f"mineru API returned failure, code={code}, msg={payload.get('msg')!r}, trace_id={payload.get('trace_id')!r}"
        )
    return payload


def _read_archive_json(archive: zipfile.ZipFile, member_name: str) -> Any:
    with archive.open(member_name, "r") as fh:
        return json.loads(fh.read().decode("utf-8"))


class MinerUStandardClient:
    def __init__(self, config_path: Path, profile_name: Optional[str] = None):
        self.config = load_mineru_config(config_path, profile_name)
        self.session = requests.Session()
        self.session.trust_env = self.config["use_env_proxy"]

    def close(self) -> None:
        self.session.close()

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        response = self.session.request(
            method=method,
            url=url,
            headers=headers,
            json=json_body,
            timeout=timeout or self.config["request_timeout_sec"],
        )
        return _json_or_error(response)

    def _download_bytes(self, url: str) -> bytes:
        response = self.session.get(url, timeout=self.config["request_timeout_sec"])
        if response.status_code >= 400:
            raise MinerUAPIError(f"mineru download failed, status={response.status_code}, url={url}")
        return response.content

    def _create_batch_by_file(self, file_path: Path) -> str:
        payload: Dict[str, Any] = {
            "files": [{"name": file_path.name, "is_ocr": False}],
            "model_version": self.config["model_version"],
            "language": self.config["language"],
            "enable_formula": False,
            "enable_table": True,
        }
        result = self._request_json(
            "POST",
            f"{self.config['base_url']}/file-urls/batch",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config['api_key']}",
            },
            json_body=payload,
        )
        batch_id = str(result["data"]["batch_id"])
        file_urls = result["data"].get("file_urls")
        if not isinstance(file_urls, list) or not file_urls:
            raise MinerUAPIError(f"mineru file upload URL missing, batch_id={batch_id}")
        with file_path.open("rb") as fh:
            upload_response = self.session.put(
                str(file_urls[0]),
                data=fh,
                timeout=self.config["request_timeout_sec"],
            )
        if upload_response.status_code not in (200, 201):
            raise MinerUAPIError(
                f"mineru file upload failed, status={upload_response.status_code}, batch_id={batch_id}"
            )
        return batch_id

    def _poll_batch_result(self, batch_id: str) -> Dict[str, Any]:
        deadline = time.monotonic() + float(self.config["result_timeout_sec"])
        headers = {"Authorization": f"Bearer {self.config['api_key']}"}
        while time.monotonic() < deadline:
            result = self._request_json(
                "GET",
                f"{self.config['base_url']}/extract-results/batch/{batch_id}",
                headers=headers,
            )
            data = result.get("data", {})
            extract_results = data.get("extract_result")
            if isinstance(extract_results, list) and extract_results:
                first = extract_results[0]
                state = first.get("state")
                if state == "done":
                    return result
                if state == "failed":
                    raise MinerUAPIError(
                        f"mineru batch extraction failed, err_msg={first.get('err_msg')!r}, batch_id={batch_id}"
                    )
            time.sleep(float(self.config["poll_interval_sec"]))
        raise MinerUAPIError(f"mineru batch polling timed out, batch_id={batch_id}")

    @staticmethod
    def _pick_archive_member(names: list[str], suffixes: list[str]) -> Optional[str]:
        lowered = {name.lower(): name for name in names}
        for suffix in suffixes:
            exact = lowered.get(suffix.lower())
            if exact is not None:
                return exact
        for suffix in suffixes:
            matched = [name for name in names if name.lower().endswith(suffix.lower())]
            if matched:
                matched.sort(key=len)
                return matched[0]
        return None

    def _parse_result_archive(self, archive_bytes: bytes) -> Dict[str, Any]:
        with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as archive:
            names = archive.namelist()
            bundle: Dict[str, Any] = {
                "archive_files": sorted(names),
                "content_list": None,
                "content_list_v2": None,
                "model": None,
                "middle": None,
                "layout": None,
            }
            suffix_mapping = {
                "content_list_v2": ["content_list_v2.json", "_content_list_v2.json"],
                "content_list": ["content_list.json", "_content_list.json"],
                "model": ["model.json", "_model.json"],
                "middle": ["middle.json", "_middle.json"],
                "layout": ["layout.json", "_layout.json"],
            }
            for key, suffixes in suffix_mapping.items():
                member_name = self._pick_archive_member(names, suffixes)
                if member_name is None:
                    continue
                bundle[key] = _read_archive_json(archive, member_name)
            return bundle

    def _run_file_with_archive(self, file_path: Path) -> tuple[Dict[str, Any], bytes]:
        resolved = _ensure_file_exists(file_path)
        batch_id = self._create_batch_by_file(resolved)
        result = self._poll_batch_result(batch_id)
        extract_results = result.get("data", {}).get("extract_result")
        if not isinstance(extract_results, list) or not extract_results:
            raise MinerUAPIError(f"mineru batch result missing extract_result, batch_id={batch_id}")
        first = extract_results[0]
        zip_url = first.get("full_zip_url")
        if not isinstance(zip_url, str) or not zip_url.strip():
            raise MinerUAPIError(f"mineru batch result missing full_zip_url, batch_id={batch_id}")
        archive_bytes = self._download_bytes(zip_url.strip())
        bundle = self._parse_result_archive(archive_bytes)
        bundle["batch_id"] = batch_id
        bundle["zip_url"] = zip_url.strip()
        bundle["result"] = result
        return bundle, archive_bytes

    def run_file(self, file_path: Path) -> Dict[str, Any]:
        bundle, _archive_bytes = self._run_file_with_archive(file_path)
        return bundle

    def run_file_archive(self, file_path: Path) -> tuple[Dict[str, Any], bytes]:
        return self._run_file_with_archive(file_path)

    def run_bytes(self, *, filename: str, content: bytes, suffix: Optional[str] = None) -> Dict[str, Any]:
        safe_suffix = suffix or Path(filename).suffix or ".jpg"
        with tempfile.TemporaryDirectory(prefix="mineru_standard_") as temp_dir:
            temp_path = Path(temp_dir) / f"{Path(filename).stem or 'upload'}{safe_suffix}"
            temp_path.write_bytes(content)
            return self.run_file(temp_path)
