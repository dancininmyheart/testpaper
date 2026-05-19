from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _as_bool(value: Any, default: bool) -> bool:
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


def _as_int(value: Any, default: int, *, minimum: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


def _as_float(value: Any, default: float, *, minimum: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, parsed)


def _normalize_token(value: Any, allowed: set[str], default: str) -> str:
    if isinstance(value, str) and value.strip().lower() in allowed:
        return value.strip().lower()
    return default


@dataclass(frozen=True)
class AIProfile:
    name: str
    role: str
    runtime: str
    provider: str
    base_url: str
    model: str
    api_key_env: str
    api_key: str
    timeout_sec: int = 120
    max_retries: int = 2
    backoff_base_sec: float = 1.5
    min_interval_sec: float = 0.0
    max_tokens: int = 4096
    use_responses_api: bool = False
    enable_thinking: bool = False
    thinking: str = "disabled"
    reasoning_effort: str = "low"
    detail: str | None = None
    output_version: str | None = None
    structured_output_method: str = "json_schema"
    strict_structured_output: bool | None = None

    @classmethod
    def from_config(cls, name: str, payload: dict[str, Any]) -> "AIProfile":
        base_url = payload.get("base_url")
        model = payload.get("model")
        api_key_env = payload.get("api_key_env")
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError(f"AI profile {name}: base_url is required")
        if not isinstance(model, str) or not model.strip():
            raise ValueError(f"AI profile {name}: model is required")
        if not isinstance(api_key_env, str) or not api_key_env.strip():
            raise ValueError(f"AI profile {name}: api_key_env is required")
        api_key = os.getenv(api_key_env.strip(), "").strip()
        if not api_key:
            raise ValueError(f"AI profile {name}: set env var {api_key_env.strip()} for api key")
        enable_thinking = _as_bool(payload.get("enable_thinking"), False)
        thinking = _normalize_token(
            payload.get("thinking"),
            {"enabled", "disabled", "auto"},
            "enabled" if enable_thinking else "disabled",
        )
        detail = _normalize_token(payload.get("detail"), {"auto", "low", "high", "xhigh"}, "")
        strict_raw = payload.get("strict_structured_output")
        strict_structured_output = strict_raw if isinstance(strict_raw, bool) else None
        return cls(
            name=name,
            role=_normalize_token(payload.get("profile_role"), {"vision", "text", "both"}, "both"),
            runtime=_normalize_token(payload.get("runtime"), {"langchain", "legacy"}, "langchain"),
            provider=str(payload.get("provider") or "openai_compatible").strip().lower(),
            base_url=base_url.strip(),
            model=model.strip(),
            api_key_env=api_key_env.strip(),
            api_key=api_key,
            timeout_sec=_as_int(payload.get("timeout_sec"), 120, minimum=1),
            max_retries=_as_int(payload.get("max_retries"), 2, minimum=0),
            backoff_base_sec=_as_float(payload.get("backoff_base_sec"), 1.5),
            min_interval_sec=_as_float(payload.get("min_interval_sec"), 0.0),
            max_tokens=_as_int(payload.get("max_tokens"), 4096, minimum=1),
            use_responses_api=_as_bool(payload.get("use_responses_api"), False),
            enable_thinking=enable_thinking,
            thinking=thinking,
            reasoning_effort=_normalize_token(payload.get("reasoning_effort"), {"minimal", "low", "medium", "high"}, "low"),
            detail=detail or None,
            output_version=payload.get("output_version") if isinstance(payload.get("output_version"), str) else None,
            structured_output_method=_normalize_token(
                payload.get("structured_output_method"),
                {"json_schema", "function_calling", "json_mode"},
                "json_schema",
            ),
            strict_structured_output=strict_structured_output,
        )

    def trace_metadata(self) -> dict[str, Any]:
        return {
            "profile": self.name,
            "provider": self.provider,
            "model": self.model,
            "runtime": self.runtime,
            "api_key_env": self.api_key_env,
        }


def load_ai_profiles(config_path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    profiles = payload.get("openai_profiles")
    if not isinstance(profiles, dict):
        raise ValueError("Invalid LLM config: missing openai_profiles")
    return {str(name): item for name, item in profiles.items() if isinstance(name, str) and isinstance(item, dict)}


def load_ai_profile(config_path: Path, profile_name: str | None = None) -> AIProfile:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    profiles = payload.get("openai_profiles")
    if not isinstance(profiles, dict):
        raise ValueError("Invalid LLM config: missing openai_profiles")
    if not profile_name:
        defaults = payload.get("defaults")
        if isinstance(defaults, dict) and isinstance(defaults.get("profile"), str):
            profile_name = defaults["profile"]
    if not isinstance(profile_name, str) or not profile_name.strip():
        raise ValueError("Missing AI profile name")
    profile_payload = profiles.get(profile_name)
    if not isinstance(profile_payload, dict):
        raise ValueError(f"Unknown AI profile: {profile_name}")
    return AIProfile.from_config(profile_name, profile_payload)
