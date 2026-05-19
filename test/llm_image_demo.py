from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import requests

DEFAULT_CONFIG_PATH = Path(r"D:\project\testpaper\llm_config.json")


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


def load_llm_profile(config_path: Path, profile_name: Optional[str]) -> Dict[str, Any]:
    if not config_path.exists():
        raise SystemExit(f"LLM config not found: {config_path}")

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    profiles = payload.get("openai_profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise SystemExit("Invalid LLM config: missing openai_profiles.")

    if not profile_name:
        defaults = payload.get("defaults")
        if isinstance(defaults, dict):
            profile_name = defaults.get("profile")

    if not profile_name:
        raise SystemExit("Missing profile. Set defaults.profile in config or pass --profile.")

    profile = profiles.get(profile_name)
    if not isinstance(profile, dict):
        raise SystemExit(f"Unknown profile: {profile_name}")

    provider = profile.get("provider", "openai_compatible")
    base_url = profile.get("base_url")
    model = profile.get("model")
    api_key_env = profile.get("api_key_env")
    api_key = profile.get("api_key")
    if not isinstance(base_url, str) or not base_url.strip():
        raise SystemExit(f"Invalid profile {profile_name}: base_url is required.")
    if not isinstance(model, str) or not model.strip():
        raise SystemExit(f"Invalid profile {profile_name}: model is required.")
    resolved_api_key = ""
    if isinstance(api_key_env, str) and api_key_env.strip():
        env_value = os.getenv(api_key_env.strip())
        if isinstance(env_value, str) and env_value.strip():
            resolved_api_key = env_value.strip()
    if not resolved_api_key and isinstance(api_key, str) and api_key.strip():
        resolved_api_key = api_key.strip()
    if not resolved_api_key:
        if isinstance(api_key_env, str) and api_key_env.strip():
            raise SystemExit(f"Invalid profile {profile_name}: missing env var {api_key_env.strip()}.")
        raise SystemExit(f"Invalid profile {profile_name}: api_key is required.")

    timeout_sec = profile.get("timeout_sec", 120)
    max_tokens = profile.get("max_tokens", 1024)
    use_env_proxy = _as_bool(profile.get("use_env_proxy", True), True)
    enable_thinking = _as_bool(profile.get("enable_thinking", False), False)

    try:
        timeout_sec = int(timeout_sec)
    except (TypeError, ValueError):
        timeout_sec = 120
    if timeout_sec <= 0:
        timeout_sec = 120

    try:
        max_tokens = int(max_tokens)
    except (TypeError, ValueError):
        max_tokens = 1024
    if max_tokens <= 0:
        max_tokens = 1024

    return {
        "name": profile_name,
        "provider": provider if isinstance(provider, str) and provider.strip() else "openai_compatible",
        "base_url": base_url.strip(),
        "api_key": resolved_api_key,
        "model": model.strip(),
        "timeout_sec": timeout_sec,
        "max_tokens": max_tokens,
        "use_env_proxy": use_env_proxy,
        "enable_thinking": enable_thinking,
    }


def image_to_data_url(image_path: Path) -> str:
    if not image_path.exists() or not image_path.is_file():
        raise SystemExit(f"Image not found: {image_path}")

    suffix = image_path.suffix.lower().lstrip(".")
    mime = "jpeg" if suffix in {"jpg", "jpeg"} else (suffix or "png")
    image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:image/{mime};base64,{image_b64}"


def _extract_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "\n".join(chunks)
    return ""


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
    chunks = []
    for item in output:
        item_obj = _model_dump_compat(item)
        if not isinstance(item_obj, dict) or item_obj.get("type") != "message":
            continue
        content = item_obj.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            block_obj = _model_dump_compat(block)
            if isinstance(block_obj, dict) and block_obj.get("type") == "output_text" and isinstance(block_obj.get("text"), str):
                chunks.append(block_obj["text"])
    return "\n".join(chunks).strip()


def call_vlm_with_image(profile: Dict[str, Any], image_path: Path, prompt: str) -> Dict[str, Any]:
    if str(profile.get("provider", "openai_compatible")).strip().lower() == "ark_responses":
        try:
            import httpx
            from volcenginesdkarkruntime import Ark
        except ImportError as exc:  # pragma: no cover - runtime dependency check
            raise SystemExit(
                "Ark SDK not installed. Run: pip install --upgrade \"volcengine-python-sdk[ark]\""
            ) from exc

        http_client = None
        if not profile["use_env_proxy"]:
            http_client = httpx.Client(trust_env=False, timeout=profile["timeout_sec"])
        try:
            client = Ark(
                base_url=profile["base_url"],
                api_key=profile["api_key"],
                timeout=profile["timeout_sec"],
                http_client=http_client,
            )
            response = client.responses.create(
                model=profile["model"],
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_image", "image_url": image_to_data_url(image_path)},
                            {"type": "input_text", "text": prompt},
                        ],
                    }
                ],
                temperature=0,
                max_output_tokens=profile["max_tokens"],
                thinking={"type": "enabled" if bool(profile.get("enable_thinking", False)) else "disabled"},
            )
            return {
                "provider": "ark_responses",
                "raw_response": _model_dump_compat(response),
                "choices": [
                    {
                        "message": {"content": _extract_ark_output_text(response)},
                        "finish_reason": getattr(response, "status", None),
                    }
                ],
            }
        finally:
            if http_client is not None:
                http_client.close()

    url = profile["base_url"].rstrip("/") + "/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {profile['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": profile["model"],
        "temperature": 0,
        "max_tokens": profile["max_tokens"],
        "messages": [
            {"role": "system", "content": "You are a helpful vision assistant."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}},
                ],
            },
        ],
    }
    payload["enable_thinking"] = bool(profile.get("enable_thinking", False))

    timeout = profile["timeout_sec"]
    if profile["use_env_proxy"]:
        response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    else:
        with requests.Session() as session:
            session.trust_env = False
            response = session.post(url, headers=headers, json=payload, timeout=timeout)

    if response.status_code >= 400:
        detail = response.text.strip()
        if len(detail) > 1000:
            detail = detail[:1000] + "...(truncated)"
        raise SystemExit(
            f"Request failed: status={response.status_code}, url={url}, model={profile['model']}. detail={detail}"
        )

    return response.json()


def parse_model_text(response: Dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message")
    if not isinstance(message, dict):
        return ""
    return _extract_content_text(message.get("content"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo: call vision LLM with image path and prompt")
    parser.add_argument("--image", required=True, help="Image file path")
    parser.add_argument(
        "--prompt",
        default="Please describe the image and extract key information.",
        help="User prompt",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help=f"Path to llm_config.json (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument("--profile", default=None, help="Profile name in openai_profiles")
    parser.add_argument("--output-json", default=None, help="Optional path to save full response JSON")
    args = parser.parse_args()

    config_path = Path(args.config)
    image_path = Path(args.image)

    profile = load_llm_profile(config_path, args.profile)
    response = call_vlm_with_image(profile, image_path, args.prompt)
    text = parse_model_text(response)

    print(f"profile: {profile['name']}")
    print(f"model: {profile['model']}")
    print("\n=== response text ===")
    print(text if text else "<empty>")

    if args.output_json:
        output_path = Path(args.output_json)
        output_path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nFull JSON saved to: {output_path}")


if __name__ == "__main__":
    main()
