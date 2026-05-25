from __future__ import annotations

import argparse
import ast
import base64
import json
import os
import random
import re
import time
import warnings
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

from prompt_store import PromptStore

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
ALLOWED_NODE_TYPES = {"concept", "formula", "method", "theorem", "skill"}
_LAST_REQUEST_TS: Optional[float] = None


def _as_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _normalize_thinking_mode(value: Any, *, fallback_enable_thinking: bool = False) -> str:
    if isinstance(value, str):
        mode = value.strip().lower()
        if mode in {"enabled", "disabled", "auto"}:
            return mode
    return "enabled" if fallback_enable_thinking else "disabled"


def _normalize_reasoning_effort(value: Any, *, default: str = "low") -> str:
    if isinstance(value, str):
        effort = value.strip().lower()
        if effort in {"minimal", "low", "medium", "high"}:
            return effort
    return default


def _reasoning_effort_for_thinking(thinking_mode: str, reasoning_effort: Any, *, default: str = "low") -> Optional[str]:
    if thinking_mode == "disabled":
        return None
    return _normalize_reasoning_effort(reasoning_effort, default=default)


def _normalize_image_detail(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if text in {"auto", "low", "high", "xhigh"}:
        return text
    return None


def _normalize_image_pixel_limit(value: Any) -> Optional[Dict[str, int]]:
    if not isinstance(value, dict):
        return None
    out: Dict[str, int] = {}
    min_pixels = value.get("min_pixels")
    max_pixels = value.get("max_pixels")
    if isinstance(min_pixels, (int, float, str)):
        min_int = int(min_pixels)
        if min_int < 196 or min_int > 36_000_000:
            raise ValueError("image_pixel_limit.min_pixels out of range [196, 36000000]")
        out["min_pixels"] = min_int
    if isinstance(max_pixels, (int, float, str)):
        max_int = int(max_pixels)
        if max_int < 196 or max_int > 36_000_000:
            raise ValueError("image_pixel_limit.max_pixels out of range [196, 36000000]")
        out["max_pixels"] = max_int
    if "min_pixels" in out and "max_pixels" in out and out["min_pixels"] > out["max_pixels"]:
        raise ValueError("image_pixel_limit.min_pixels cannot exceed max_pixels")
    return out or None


def _load_key_word_payload(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("key_word.json must be a JSON object")
    return payload


def _extract_points_from_nodes(nodes: Any) -> List[Dict[str, str]]:
    points: List[Dict[str, str]] = []
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = node.get("id")
            name = node.get("name", "")
            node_type = node.get("type", "")
            if isinstance(node_id, str):
                points.append(
                    {
                        "id": node_id,
                        "name": name if isinstance(name, str) else "",
                        "type": node_type if isinstance(node_type, str) else "",
                    }
                )
    return points


def _load_llm_profile(config_path: Path, profile_name: Optional[str]) -> Dict[str, Any]:
    if not config_path.exists():
        raise SystemExit(f"LLM config not found: {config_path}")
    payload = json.loads(config_path.read_text(encoding="utf-8-sig"))
    profiles = payload.get("openai_profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise SystemExit("Invalid LLM config: missing openai_profiles.")

    if not profile_name:
        defaults = payload.get("defaults", {})
        if isinstance(defaults, dict):
            profile_name = defaults.get("profile")
    if not profile_name:
        raise SystemExit("Missing LLM profile: set defaults.profile or pass --profile.")

    profile = profiles.get(profile_name)
    if not isinstance(profile, dict):
        raise SystemExit(f"Unknown LLM profile: {profile_name}")

    provider = profile.get("provider", "openai_compatible")
    runtime = profile.get("runtime", "legacy")
    base_url = profile.get("base_url")
    model = profile.get("model")
    api_key_env = profile.get("api_key_env")
    api_key = profile.get("api_key")

    if not isinstance(base_url, str) or not base_url.strip():
        raise SystemExit(f"Invalid LLM profile {profile_name}: base_url is required.")
    if not isinstance(model, str) or not model.strip():
        raise SystemExit(f"Invalid LLM profile {profile_name}: model is required.")
    resolved_api_key = ""
    if isinstance(api_key_env, str) and api_key_env.strip():
        env_key = os.getenv(api_key_env.strip())
        if isinstance(env_key, str) and env_key.strip():
            resolved_api_key = env_key.strip()
    if not resolved_api_key and isinstance(api_key, str) and api_key.strip():
        resolved_api_key = api_key.strip()
    if not resolved_api_key:
        if isinstance(api_key_env, str) and api_key_env.strip():
            raise SystemExit(
                f"Invalid LLM profile {profile_name}: set env var {api_key_env.strip()} for api key."
            )
        raise SystemExit(f"Invalid LLM profile {profile_name}: api_key is required.")

    timeout_sec = profile.get("timeout_sec", 120)
    max_retries = profile.get("max_retries", 3)
    backoff_base_sec = profile.get("backoff_base_sec", 1.5)
    min_interval_sec = profile.get("min_interval_sec", 0.0)
    paper_batch_size = profile.get("paper_batch_size", 1)
    answer_batch_size = profile.get("answer_batch_size", 1)
    max_tokens = profile.get("max_tokens", 600)
    use_env_proxy = _as_bool(profile.get("use_env_proxy", True), True)
    use_responses_api = _as_bool(profile.get("use_responses_api", False), False)
    enable_thinking = _as_bool(profile.get("enable_thinking", False), False)
    thinking = _normalize_thinking_mode(profile.get("thinking"), fallback_enable_thinking=enable_thinking)
    reasoning_effort = _normalize_reasoning_effort(profile.get("reasoning_effort"), default="low")
    detail = _normalize_image_detail(profile.get("detail"))
    image_pixel_limit = _normalize_image_pixel_limit(profile.get("image_pixel_limit"))
    output_version = profile.get("output_version")

    try:
        timeout_sec = int(timeout_sec)
    except (TypeError, ValueError):
        timeout_sec = 120
    if timeout_sec <= 0:
        timeout_sec = 120

    try:
        max_retries = int(max_retries)
    except (TypeError, ValueError):
        max_retries = 3
    if max_retries < 0:
        max_retries = 3

    try:
        backoff_base_sec = float(backoff_base_sec)
    except (TypeError, ValueError):
        backoff_base_sec = 1.5
    if backoff_base_sec < 0:
        backoff_base_sec = 1.5

    try:
        min_interval_sec = float(min_interval_sec)
    except (TypeError, ValueError):
        min_interval_sec = 0.0
    if min_interval_sec < 0:
        min_interval_sec = 0.0

    try:
        paper_batch_size = int(paper_batch_size)
    except (TypeError, ValueError):
        paper_batch_size = 1
    if paper_batch_size <= 0:
        paper_batch_size = 1

    try:
        answer_batch_size = int(answer_batch_size)
    except (TypeError, ValueError):
        answer_batch_size = 1
    if answer_batch_size <= 0:
        answer_batch_size = 1

    try:
        max_tokens = int(max_tokens)
    except (TypeError, ValueError):
        max_tokens = 600
    if max_tokens <= 0:
        max_tokens = 600

    result = {
        "name": profile_name,
        "provider": provider if isinstance(provider, str) and provider.strip() else "openai_compatible",
        "runtime": runtime.strip().lower() if isinstance(runtime, str) and runtime.strip() else "legacy",
        "base_url": base_url.strip(),
        "api_key": resolved_api_key,
        "api_key_env": api_key_env.strip() if isinstance(api_key_env, str) and api_key_env.strip() else None,
        "model": model.strip(),
        "timeout_sec": timeout_sec,
        "max_retries": max_retries,
        "backoff_base_sec": backoff_base_sec,
        "min_interval_sec": min_interval_sec,
        "paper_batch_size": paper_batch_size,
        "answer_batch_size": answer_batch_size,
        "max_tokens": max_tokens,
        "use_env_proxy": use_env_proxy,
        "use_responses_api": use_responses_api,
        "enable_thinking": enable_thinking,
        "thinking": thinking,
        "reasoning_effort": reasoning_effort,
        "detail": detail,
        "image_pixel_limit": image_pixel_limit,
        "output_version": output_version.strip() if isinstance(output_version, str) and output_version.strip() else None,
    }
    passthrough_keys = (
        "question_page_batch_size",
        "question_chunk_size",
        "reference_answer_chunk_size",
        "route_chunk_size",
        "score_chunk_size",
        "answer_chunk_size",
        "answer_structuring_chunk_size",
        "objective_chunk_size",
        "subjective_chunk_size",
        "paper_concurrency",
        "answer_route_concurrency",
        "answer_concurrency",
        "text_profile",
        "subjective_question_types",
        "max_repair_rounds",
        "repair_trigger_unseen",
        "repair_trigger_unmatched",
        "min_answer_confidence_for_skip_repair",
        "answer_segmentation_enabled",
        "answer_segment_weights",
        "answer_segment_imgsz",
        "answer_segment_conf",
        "answer_segment_iou",
        "answer_segment_device",
        "answer_segment_include_student_id",
        "answer_segment_margin_px",
        "answer_segment_save_crops",
        "answer_segment_crop_output_dir",
        "answer_trace_save_debug_json",
        "answer_trace_debug_output_dir",
        "question_full_discovery_enabled",
        "knowledge_tagging_mode",
        "blind_diagnosis_enabled",
        "blind_diagnosis_max_items",
        "profile_mode",
        "teacher_signal_usage",
        "review_mark_filter_mode",
        "pdf_render_dpi",
        "pdf_max_pages",
    )
    for key in passthrough_keys:
        if key in profile:
            result[key] = profile.get(key)
    return result


def iter_images(root: Path) -> Iterable[Path]:
    if root.is_file():
        if root.suffix.lower() in IMAGE_EXTS:
            yield root
        return
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS:
            yield path


def load_knowledge_points(key_word_path: Path) -> List[Dict[str, str]]:
    payload = _load_key_word_payload(key_word_path)
    return _extract_points_from_nodes(payload.get("nodes", []))


def build_prompt(points: List[Dict[str, str]], max_points: Optional[int] = None) -> str:
    return PromptStore.knowledge_tagger_prompt(points, max_points=max_points)



def build_new_point_prompt(points: List[Dict[str, str]], max_points: Optional[int] = None) -> str:
    return PromptStore.knowledge_tagger_new_point_prompt(points, max_points=max_points)



def image_to_data_url(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    ext = path.suffix.lower().lstrip(".") or "png"
    return f"data:image/{ext};base64,{data}"


def _model_dump_compat(value: Any) -> Any:
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return value.model_dump(mode="json")
    if hasattr(value, "dict") and callable(value.dict):
        return value.dict()
    return value


def _extract_ark_output_text(response: Any) -> str:
    output = getattr(response, "output", None)
    if output is None and isinstance(response, dict):
        output = response.get("output")
    if not isinstance(output, list):
        return ""

    texts: List[str] = []
    for item in output:
        item_obj = _model_dump_compat(item)
        if not isinstance(item_obj, dict) or item_obj.get("type") != "message":
            continue
        content = item_obj.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            block_obj = _model_dump_compat(block)
            if not isinstance(block_obj, dict):
                continue
            if block_obj.get("type") == "output_text" and isinstance(block_obj.get("text"), str):
                texts.append(block_obj["text"])
    return "\n".join(texts).strip()


def _call_ark_responses_with_data_urls(
    *,
    base_url: str,
    api_key: str,
    model: str,
    prompt: str,
    data_urls: List[str],
    timeout: int,
    max_retries: int,
    max_tokens: int,
    use_env_proxy: bool,
    json_mode: bool,
    enable_thinking: bool,
    thinking: Optional[str],
    reasoning_effort: Optional[str],
    detail: Optional[str],
    image_pixel_limit: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    try:
        import httpx
        from volcenginesdkarkruntime import Ark
    except ImportError as exc:  # pragma: no cover - runtime dependency check
        raise RuntimeError(
            "Ark SDK not installed. Run: pip install --upgrade \"volcengine-python-sdk[ark]\""
        ) from exc

    http_client = None
    if not use_env_proxy:
        http_client = httpx.Client(trust_env=False, timeout=timeout)

    try:
        client = Ark(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
            http_client=http_client,
        )

        content: List[Dict[str, Any]] = []
        detail_mode = _normalize_image_detail(detail)
        pixel_limit = _normalize_image_pixel_limit(image_pixel_limit)
        for data_url in data_urls:
            image_item: Dict[str, Any] = {"type": "input_image", "image_url": data_url}
            # image_pixel_limit has higher priority than detail when both are configured.
            if isinstance(pixel_limit, dict) and pixel_limit:
                image_item["image_pixel_limit"] = pixel_limit
            elif isinstance(detail_mode, str):
                image_item["detail"] = detail_mode
            content.append(image_item)
        content.append({"type": "input_text", "text": prompt})

        kwargs: Dict[str, Any] = {
            "model": model,
            "input": [{"role": "user", "content": content}],
            "temperature": 0,
        }
        thinking_mode = _normalize_thinking_mode(thinking, fallback_enable_thinking=enable_thinking)
        effort = _reasoning_effort_for_thinking(thinking_mode, reasoning_effort, default="low")
        kwargs["thinking"] = {"type": thinking_mode}
        if effort is not None:
            kwargs["reasoning"] = {"effort": effort}
        if max_tokens > 0:
            kwargs["max_output_tokens"] = max_tokens
        if json_mode:
            kwargs["text"] = {"format": {"type": "json_object"}}

        response = client.responses.create(**kwargs)
        status = getattr(response, "status", None)
        error = getattr(response, "error", None)
        if error:
            raise RuntimeError(f"Ark response error: {_model_dump_compat(error)}")

        text = _extract_ark_output_text(response)
        if status in {"failed", "incomplete"} and not text:
            raise RuntimeError(f"Ark response status={status}, body={_model_dump_compat(response)}")

        return {
            "provider": "ark_responses",
            "raw_response": _model_dump_compat(response),
            "choices": [
                {
                    "message": {"content": text},
                    "finish_reason": "stop" if status == "completed" else status,
                }
            ],
        }
    finally:
        if http_client is not None:
            http_client.close()


def _enforce_min_interval(min_interval_sec: float) -> None:
    global _LAST_REQUEST_TS
    if min_interval_sec <= 0:
        return
    now = time.time()
    if _LAST_REQUEST_TS is not None:
        gap = now - _LAST_REQUEST_TS
        if gap < min_interval_sec:
            time.sleep(min_interval_sec - gap)
    _LAST_REQUEST_TS = time.time()


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _post_json(
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout: int,
    *,
    use_env_proxy: bool,
) -> requests.Response:
    if use_env_proxy:
        return requests.post(url, headers=headers, json=payload, timeout=timeout)
    with requests.Session() as session:
        session.trust_env = False
        return session.post(url, headers=headers, json=payload, timeout=timeout)


def _build_chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if re.search(r"/api/v\d+$", normalized):
        return normalized + "/chat/completions"
    if normalized.endswith("/v1"):
        return normalized + "/chat/completions"
    return normalized + "/v1/chat/completions"


def _build_http_error(response: requests.Response, payload: Dict[str, Any]) -> RuntimeError:
    status = response.status_code
    model = payload.get("model")
    model_text = model if isinstance(model, str) and model else "<unknown>"
    detail = response.text.strip()
    if len(detail) > 1200:
        detail = detail[:1200] + "...(truncated)"

    hints: List[str] = []
    if status == 401:
        hints.append("API Key 无效、过期，或鉴权头格式不被服务端接受。")
    if status == 403:
        hints.append("当前账号可能无该模型权限，或该 API Key 被 IP/来源策略限制。")
        hints.append("请确认模型名在服务端已开通，例如可先查询 /v1/models。")
    if status == 404:
        hints.append("base_url 或路径可能不正确。若 base_url 是 /api/v3 这类路径，请使用 .../chat/completions 而不是 .../v1/chat/completions。")
    if status == 429:
        hints.append("请求频率过高，请降低并发或增大重试退避时间。")
    if status == 524:
        hints.append("网关等待上游超时（Cloudflare 524），通常是单次请求处理过重或上游响应过慢。")
        hints.append("建议减小图片尺寸、减少单次输入图片数、降低输出长度或更换更快模型。")

    hint_text = " ".join(hints)
    message = (
        f"LLM request failed: status={status}, url={response.url}, model={model_text}. "
        f"response_body={detail}"
    )
    if hint_text:
        message += f" hint={hint_text}"
    return RuntimeError(message)


def _post_with_retry(
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout: int,
    *,
    max_retries: int,
    backoff_base_sec: float,
    min_interval_sec: float,
    use_env_proxy: bool = True,
) -> requests.Response:
    last_exc: Optional[Exception] = None
    prefer_env_proxy = use_env_proxy
    for attempt in range(max_retries + 1):
        _enforce_min_interval(min_interval_sec)
        try:
            response = _post_json(
                url,
                headers,
                payload,
                timeout,
                use_env_proxy=prefer_env_proxy,
            )
        except requests.exceptions.ProxyError as exc:
            if prefer_env_proxy:
                # Proxy is unreachable; retry the same request with direct connection.
                prefer_env_proxy = False
                try:
                    response = _post_json(
                        url,
                        headers,
                        payload,
                        timeout,
                        use_env_proxy=False,
                    )
                except requests.RequestException as direct_exc:
                    last_exc = RuntimeError(
                        f"Proxy connection failed ({exc}); direct connection also failed ({direct_exc})."
                    )
                    if attempt >= max_retries:
                        raise last_exc
                    sleep_sec = backoff_base_sec * (2**attempt) + random.uniform(0, 0.25)
                    time.sleep(sleep_sec)
                    continue
            else:
                last_exc = exc
                if attempt >= max_retries:
                    raise
                sleep_sec = backoff_base_sec * (2**attempt) + random.uniform(0, 0.25)
                time.sleep(sleep_sec)
                continue
        except requests.RequestException as exc:
            last_exc = exc
            if attempt >= max_retries:
                raise
            sleep_sec = backoff_base_sec * (2**attempt) + random.uniform(0, 0.25)
            time.sleep(sleep_sec)
            continue

        if response.status_code in {408, 429, 500, 502, 503, 504, 524}:
            if attempt >= max_retries:
                raise _build_http_error(response, payload)
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            if retry_after is not None:
                time.sleep(retry_after)
            else:
                sleep_sec = backoff_base_sec * (2**attempt) + random.uniform(0, 0.25)
                time.sleep(sleep_sec)
            continue

        if response.status_code >= 400:
            raise _build_http_error(response, payload)
        return response

    if last_exc:
        raise last_exc
    raise SystemExit("LLM request failed after retries.")


def _extract_json_text(text: str) -> Optional[str]:
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return None
    return match.group(0)


def extract_json(text: str) -> Dict[str, Any]:
    json_text = _extract_json_text(text)
    if not json_text:
        raise ValueError("no JSON object in response")
    return json.loads(json_text)


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        if isinstance(content.get("text"), str):
            return content["text"]
        if isinstance(content.get("content"), str):
            return content["content"]
        if isinstance(content.get("output_text"), str):
            return content["output_text"]
        return json.dumps(content, ensure_ascii=False)
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item.get("content"), str):
                    parts.append(item["content"])
                elif isinstance(item.get("output_text"), str):
                    parts.append(item["output_text"])
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
        return "\n".join(parts)
    return ""


def _is_valid_node_id(value: str) -> bool:
    return bool(re.match(r"^[a-z][a-z0-9_.]*$", value))


def _slugify_id(text: str) -> str:
    lowered = text.lower()
    slug = re.sub(r"[^a-z0-9]+", ".", lowered).strip(".")
    slug = re.sub(r"\.{2,}", ".", slug)
    return slug


def _make_unique_id(candidate: str, name: str, existing_ids: set[str]) -> str:
    base = candidate.strip()
    if not _is_valid_node_id(base):
        base = _slugify_id(name)
    if not base:
        base = "auto.generated"
    if not base[0].isalpha():
        base = f"auto.{base}"
    unique = base
    suffix = 1
    while unique in existing_ids:
        unique = f"{base}.{suffix}"
        suffix += 1
    return unique


def _normalize_new_point(
    new_point: Dict[str, Any],
    existing_ids: set[str],
    existing_name_to_id: Dict[str, str],
) -> Optional[Dict[str, Any]]:
    raw_name = new_point.get("name")
    raw_type = new_point.get("type")
    raw_id = new_point.get("id")
    raw_prereq = new_point.get("prereq", [])

    name = raw_name.strip() if isinstance(raw_name, str) else ""
    if name and name in existing_name_to_id:
        return {"reuse_id": existing_name_to_id[name]}

    node_type = raw_type if isinstance(raw_type, str) else "concept"
    node_type = node_type.strip().lower() if node_type else "concept"
    if node_type not in ALLOWED_NODE_TYPES:
        node_type = "concept"

    candidate_id = raw_id if isinstance(raw_id, str) else ""
    node_id = _make_unique_id(candidate_id, name, existing_ids)

    prereq: List[str] = []
    if isinstance(raw_prereq, list):
        for item in raw_prereq:
            if isinstance(item, str) and item in existing_ids:
                prereq.append(item)

    return {
        "id": node_id,
        "name": name or node_id,
        "short_name": name or node_id,
        "type": node_type,
        "stage": "",
        "grade_band": "",
        "canonical": [],
        "procedure": [],
        "prereq": prereq,
    }


def _loads_json_like(text: str) -> Optional[Dict[str, Any]]:
    cleaned = _strip_code_fences(text)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    json_text = _extract_json_text(cleaned)
    if json_text:
        try:
            data = json.loads(json_text)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
        try:
            data = _safe_literal_eval(json_text)
            if isinstance(data, dict):
                return data
        except (ValueError, SyntaxError):
            pass

    try:
        data = _safe_literal_eval(cleaned)
        if isinstance(data, dict):
            return data
    except (ValueError, SyntaxError):
        pass

    return None


def _safe_literal_eval(text: str) -> Any:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=SyntaxWarning)
        return ast.literal_eval(text)


def call_llm_with_images(
    *,
    prompt: str,
    data_urls: List[str],
    base_url: str,
    api_key: str,
    model: str,
    timeout: int = 120,
    max_retries: int = 3,
    backoff_base_sec: float = 1.5,
    min_interval_sec: float = 0.0,
    use_env_proxy: bool = True,
    enable_thinking: bool = False,
    thinking: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
    detail: Optional[str] = None,
    image_pixel_limit: Optional[Dict[str, Any]] = None,
    provider: str = "openai_compatible",
    max_tokens: int = 0,
    json_mode: bool = False,
) -> Dict[str, Any]:
    provider_key = provider.strip().lower() if isinstance(provider, str) else "openai_compatible"
    if provider_key == "ark_responses":
        _enforce_min_interval(min_interval_sec)
        return _call_ark_responses_with_data_urls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            prompt=prompt,
            data_urls=data_urls,
            timeout=timeout,
            max_retries=max_retries,
            max_tokens=max_tokens,
            use_env_proxy=use_env_proxy,
            json_mode=json_mode,
            enable_thinking=enable_thinking,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            detail=detail,
            image_pixel_limit=image_pixel_limit,
        )

    url = _build_chat_completions_url(base_url)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
    detail_mode = _normalize_image_detail(detail)
    for data_url in data_urls:
        image_url_obj: Dict[str, Any] = {"url": data_url}
        if isinstance(detail_mode, str):
            image_url_obj["detail"] = detail_mode
        content.append({"type": "image_url", "image_url": image_url_obj})
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": "You are a strict JSON generator."},
            {"role": "user", "content": content},
        ],
    }
    payload["enable_thinking"] = bool(enable_thinking)
    thinking_mode = _normalize_thinking_mode(thinking, fallback_enable_thinking=enable_thinking)
    if isinstance(thinking, str) and thinking.strip().lower() in {"enabled", "disabled", "auto"}:
        payload["thinking"] = {"type": thinking_mode}
    effort = _reasoning_effort_for_thinking(thinking_mode, reasoning_effort, default="low")
    if isinstance(effort, str):
        payload["reasoning_effort"] = effort
    if max_tokens > 0:
        payload["max_tokens"] = max_tokens
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    response = _post_with_retry(
        url,
        headers,
        payload,
        timeout,
        max_retries=max_retries,
        backoff_base_sec=backoff_base_sec,
        min_interval_sec=min_interval_sec,
        use_env_proxy=use_env_proxy,
    )
    return response.json()


def call_llm_with_image(
    image_path: Path,
    prompt: str,
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout: int = 120,
    max_retries: int = 3,
    backoff_base_sec: float = 1.5,
    min_interval_sec: float = 0.0,
    use_env_proxy: bool = True,
    enable_thinking: bool = False,
    thinking: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
    detail: Optional[str] = None,
    image_pixel_limit: Optional[Dict[str, Any]] = None,
    provider: str = "openai_compatible",
    max_tokens: int = 0,
    json_mode: bool = True,
) -> Dict[str, Any]:
    return call_llm_with_images(
        prompt=prompt,
        data_urls=[image_to_data_url(image_path)],
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout=timeout,
        max_retries=max_retries,
        backoff_base_sec=backoff_base_sec,
        min_interval_sec=min_interval_sec,
        use_env_proxy=use_env_proxy,
        enable_thinking=enable_thinking,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
        detail=detail,
        image_pixel_limit=image_pixel_limit,
        provider=provider,
        max_tokens=max_tokens,
        json_mode=json_mode,
    )


def parse_knowledge_points(response: Dict[str, Any]) -> List[str]:
    choices = response.get("choices", [])
    if not choices:
        return []
    message = choices[0].get("message", {})
    content = _content_to_text(message.get("content", ""))
    if not content.strip():
        return []
    data = _loads_json_like(content)
    if not isinstance(data, dict):
        return []
    points = data.get("knowledge_points", [])
    return [item for item in points if isinstance(item, str)]


def parse_new_point(response: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    choices = response.get("choices", [])
    if not choices:
        return None
    message = choices[0].get("message", {})
    content = _content_to_text(message.get("content", ""))
    if not content.strip():
        return None
    data = _loads_json_like(content)
    if not isinstance(data, dict):
        return None
    if "new_point" in data and isinstance(data.get("new_point"), dict):
        return data.get("new_point")
    return data


def tag_folder(
    image_dir: Path,
    key_word_path: Path,
    *,
    base_url: str,
    api_key: str,
    model: str,
    source: Optional[str] = None,
    max_points: Optional[int] = None,
    timeout: int = 120,
    max_retries: int = 3,
    backoff_base_sec: float = 1.5,
    min_interval_sec: float = 0.0,
    use_env_proxy: bool = True,
    enable_thinking: bool = False,
    thinking: Optional[str] = None,
    reasoning_effort: Optional[str] = None,
    detail: Optional[str] = None,
    image_pixel_limit: Optional[Dict[str, Any]] = None,
    provider: str = "openai_compatible",
    max_tokens: int = 0,
) -> List[Dict[str, Any]]:
    payload = _load_key_word_payload(key_word_path)
    nodes = payload.get("nodes")
    if not isinstance(nodes, list):
        nodes = []
        payload["nodes"] = nodes
    points = _extract_points_from_nodes(nodes)
    prompt = build_prompt(points, max_points=max_points)
    existing_ids = {point["id"] for point in points if point.get("id")}
    existing_name_to_id = {
        point["name"]: point["id"]
        for point in points
        if point.get("name") and point.get("id")
    }
    key_word_dirty = False
    records: List[Dict[str, Any]] = []
    for image_path in iter_images(image_dir):
        def _add_new_point(new_point_raw: Dict[str, Any]) -> Optional[str]:
            nonlocal key_word_dirty, prompt
            normalized = _normalize_new_point(
                new_point_raw, existing_ids, existing_name_to_id
            )
            if not normalized:
                return None
            reuse_id = normalized.get("reuse_id")
            if isinstance(reuse_id, str):
                return reuse_id
            node_id = normalized.get("id")
            node_name = normalized.get("name")
            node_type = normalized.get("type")
            if not isinstance(node_id, str) or not isinstance(node_name, str) or not isinstance(node_type, str):
                return None
            nodes.append(normalized)
            points.append({"id": node_id, "name": node_name, "type": node_type})
            existing_ids.add(node_id)
            if node_name:
                existing_name_to_id[node_name] = node_id
            key_word_dirty = True
            prompt = build_prompt(points, max_points=max_points)
            return node_id

        llm_response = call_llm_with_image(
            image_path,
            prompt,
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=timeout,
            max_retries=max_retries,
            backoff_base_sec=backoff_base_sec,
            min_interval_sec=min_interval_sec,
            use_env_proxy=use_env_proxy,
            enable_thinking=enable_thinking,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            detail=detail,
            image_pixel_limit=image_pixel_limit,
            provider=provider,
            max_tokens=max_tokens,
            json_mode=True,
        )
        raw_points = parse_knowledge_points(llm_response)
        known_points = [kp for kp in raw_points if kp in existing_ids]
        unknown_points = [kp for kp in raw_points if kp not in existing_ids]
        knowledge_points = list(dict.fromkeys(known_points))

        # If VLM predicts ids outside the knowledge base, add them into the base.
        for unknown_id in unknown_points:
            new_id = _add_new_point(
                {"id": unknown_id, "name": unknown_id, "type": "concept", "prereq": []}
            )
            if isinstance(new_id, str):
                knowledge_points.append(new_id)

        if not knowledge_points:
            discovery_prompt = build_new_point_prompt(points, max_points=max_points)
            discovery_response = call_llm_with_image(
                image_path,
                discovery_prompt,
                base_url=base_url,
                api_key=api_key,
                model=model,
                timeout=timeout,
                max_retries=max_retries,
                backoff_base_sec=backoff_base_sec,
                min_interval_sec=min_interval_sec,
                use_env_proxy=use_env_proxy,
                enable_thinking=enable_thinking,
                thinking=thinking,
                reasoning_effort=reasoning_effort,
                detail=detail,
                image_pixel_limit=image_pixel_limit,
                provider=provider,
                max_tokens=max_tokens,
                json_mode=True,
            )
            new_point_raw = parse_new_point(discovery_response)
            if isinstance(new_point_raw, dict):
                new_id = _add_new_point(new_point_raw)
                if isinstance(new_id, str):
                    knowledge_points = [new_id]
        records.append(
            {
                "question_id": image_path.stem,
                "knowledge_points": knowledge_points,
                "is_correct": None,
                "score": None,
                "max_score": None,
                "answered_at": None,
                "difficulty": None,
                "source": source or image_dir.name,
                "time_spent_sec": None,
            }
        )
    if key_word_dirty:
        key_word_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Tag images with knowledge points using an OpenAI-compatible LLM."
    )
    parser.add_argument("--images", required=True, help="Folder or image file path.")
    parser.add_argument("--key-word", required=True, help="Path to key_word.json.")
    parser.add_argument("--output", required=True, help="Output JSON file path.")
    parser.add_argument("--source", default=None, help="Source label for records.")
    parser.add_argument("--max-points", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Max retries for 429/5xx or transient errors.",
    )
    parser.add_argument(
        "--backoff-base-sec",
        type=float,
        default=1.5,
        help="Base seconds for exponential backoff.",
    )
    parser.add_argument(
        "--min-interval-sec",
        type=float,
        default=0.0,
        help="Minimum seconds between LLM requests (rate limiting).",
    )
    parser.add_argument(
        "--config",
        default="llm_config.json",
        help="Path to LLM config JSON (default: llm_config.json).",
    )
    parser.add_argument(
        "--profile",
        default=None,
        help="LLM profile name defined in config (overrides defaults.profile).",
    )
    args = parser.parse_args()

    profile = _load_llm_profile(Path(args.config), args.profile)

    records = tag_folder(
        Path(args.images),
        Path(args.key_word),
        base_url=profile["base_url"],
        api_key=profile["api_key"],
        model=profile["model"],
        source=args.source,
        max_points=args.max_points,
        timeout=args.timeout,
        max_retries=args.max_retries,
        backoff_base_sec=args.backoff_base_sec,
        min_interval_sec=args.min_interval_sec,
        use_env_proxy=profile.get("use_env_proxy", True),
        enable_thinking=profile.get("enable_thinking", False),
        thinking=profile.get("thinking"),
        reasoning_effort=profile.get("reasoning_effort"),
        detail=profile.get("detail"),
        image_pixel_limit=profile.get("image_pixel_limit"),
        provider=profile.get("provider", "openai_compatible"),
        max_tokens=profile.get("max_tokens", 0),
    )
    Path(args.output).write_text(json.dumps(records, ensure_ascii=True, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

