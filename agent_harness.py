from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


@dataclass(frozen=True)
class HarnessStageSpec:
    name: str
    mode: str
    profile_role: str = "default"
    expected_list_key: Optional[str] = None
    thinking_override: Optional[str] = None
    reasoning_effort_override: Optional[str] = None
    detail_override: Optional[str] = None


@dataclass(frozen=True)
class HarnessInvocationOptions:
    token_limit: int
    enable_thinking: bool
    thinking: str
    reasoning_effort: Optional[str]
    detail: Optional[str]
    image_pixel_limit: Optional[Dict[str, Any]]


class AgentHarness:
    def __init__(
        self,
        *,
        default_max_tokens: int,
        default_use_env_proxy: bool,
        should_use_langchain_runtime: Callable[[Dict[str, Any]], bool],
        get_langchain_agent: Callable[[Dict[str, Any]], Any],
        normalize_json_payload: Callable[[str, Optional[str]], Optional[Dict[str, Any]]],
        legacy_json_caller: Callable[..., Dict[str, Any]],
        legacy_text_caller: Callable[..., str],
    ) -> None:
        self.default_max_tokens = default_max_tokens
        self.default_use_env_proxy = default_use_env_proxy
        self._should_use_langchain_runtime = should_use_langchain_runtime
        self._get_langchain_agent = get_langchain_agent
        self._normalize_json_payload = normalize_json_payload
        self._legacy_json_caller = legacy_json_caller
        self._legacy_text_caller = legacy_text_caller

    @staticmethod
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

    @classmethod
    def _resolve_thinking_options(
        cls,
        profile: Dict[str, Any],
        *,
        thinking_override: Optional[str],
        reasoning_effort_override: Optional[str],
    ) -> tuple[bool, str, Optional[str]]:
        thinking_override_token = thinking_override.strip().lower() if isinstance(thinking_override, str) else None
        thinking_effort_from_thinking: Optional[str] = None
        if thinking_override_token in {"enabled", "disabled", "auto"}:
            thinking_value = thinking_override_token
        elif thinking_override_token in {"minimal", "low", "medium", "high"}:
            thinking_value = "enabled"
            thinking_effort_from_thinking = thinking_override_token
        else:
            thinking_value = (
                str(profile.get("thinking")).strip().lower()
                if isinstance(profile.get("thinking"), str)
                and str(profile.get("thinking")).strip().lower() in {"enabled", "disabled", "auto"}
                else ("enabled" if cls._as_bool(profile.get("enable_thinking", False), False) else "disabled")
            )
        enable_thinking_value = cls._as_bool(profile.get("enable_thinking", False), False)
        if thinking_override_token in {"enabled", "auto", "minimal", "low", "medium", "high"}:
            enable_thinking_value = True
        elif thinking_override_token == "disabled":
            enable_thinking_value = False
        reasoning_effort_value = (
            reasoning_effort_override.strip().lower()
            if isinstance(reasoning_effort_override, str)
            and reasoning_effort_override.strip().lower() in {"minimal", "low", "medium", "high"}
            else (
                thinking_effort_from_thinking
                if isinstance(thinking_effort_from_thinking, str)
                else (
                    str(profile.get("reasoning_effort")).strip().lower()
                    if isinstance(profile.get("reasoning_effort"), str)
                    and str(profile.get("reasoning_effort")).strip().lower() in {"minimal", "low", "medium", "high"}
                    else None
                )
            )
        )
        if thinking_value == "disabled":
            reasoning_effort_value = None
        return enable_thinking_value, thinking_value, reasoning_effort_value

    @staticmethod
    def _resolve_detail_value(profile: Dict[str, Any], detail_override: Optional[str]) -> Optional[str]:
        if isinstance(detail_override, str) and detail_override.strip().lower() in {"auto", "low", "high", "xhigh"}:
            return detail_override.strip().lower()
        if isinstance(profile.get("detail"), str) and str(profile.get("detail")).strip().lower() in {"auto", "low", "high", "xhigh"}:
            return str(profile.get("detail")).strip().lower()
        return None

    def build_invocation_options(
        self,
        profile: Dict[str, Any],
        *,
        max_tokens: Optional[int] = None,
        thinking_override: Optional[str] = None,
        reasoning_effort_override: Optional[str] = None,
        detail_override: Optional[str] = None,
        image_pixel_limit_override: Optional[Dict[str, Any]] = None,
    ) -> HarnessInvocationOptions:
        enable_thinking_value, thinking_value, reasoning_effort_value = self._resolve_thinking_options(
            profile,
            thinking_override=thinking_override,
            reasoning_effort_override=reasoning_effort_override,
        )
        detail_value = self._resolve_detail_value(profile, detail_override)
        image_pixel_limit_value = (
            image_pixel_limit_override
            if isinstance(image_pixel_limit_override, dict)
            else (profile.get("image_pixel_limit") if isinstance(profile.get("image_pixel_limit"), dict) else None)
        )
        token_limit = (
            max_tokens
            if isinstance(max_tokens, int) and max_tokens > 0
            else int(profile.get("max_tokens", self.default_max_tokens))
        )
        return HarnessInvocationOptions(
            token_limit=token_limit,
            enable_thinking=enable_thinking_value,
            thinking=thinking_value,
            reasoning_effort=reasoning_effort_value,
            detail=detail_value,
            image_pixel_limit=image_pixel_limit_value,
        )

    def invoke_json(
        self,
        *,
        profile: Dict[str, Any],
        prompt: str,
        data_urls: List[str],
        max_tokens: Optional[int] = None,
        expected_list_key: Optional[str] = None,
        thinking_override: Optional[str] = None,
        reasoning_effort_override: Optional[str] = None,
        detail_override: Optional[str] = None,
        image_pixel_limit_override: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        options = self.build_invocation_options(
            profile,
            max_tokens=max_tokens,
            thinking_override=thinking_override,
            reasoning_effort_override=reasoning_effort_override,
            detail_override=detail_override,
            image_pixel_limit_override=image_pixel_limit_override,
        )
        if self._should_use_langchain_runtime(profile):
            raw_text = self._get_langchain_agent(profile).invoke_json(
                prompt=prompt,
                data_urls=data_urls,
                max_tokens=options.token_limit,
                enable_thinking=options.enable_thinking,
                thinking=options.thinking,
                reasoning_effort=options.reasoning_effort,
                detail=options.detail,
            )
            data = self._normalize_json_payload(raw_text, expected_list_key)
            if not isinstance(data, dict):
                preview = raw_text.strip()[:300] if isinstance(raw_text, str) else ""
                raise ValueError(f"LangChain did not return valid JSON object (preview={preview})")
            return data
        return self._legacy_json_caller(
            base_url=profile["base_url"],
            api_key=profile["api_key"],
            model=profile["model"],
            provider=str(profile.get("provider", "openai_compatible")),
            prompt=prompt,
            data_urls=data_urls,
            timeout=int(profile.get("timeout_sec", 120)),
            max_retries=int(profile.get("max_retries", 2)),
            backoff_base_sec=float(profile.get("backoff_base_sec", 1.5)),
            min_interval_sec=float(profile.get("min_interval_sec", 0.0)),
            max_tokens=options.token_limit,
            use_env_proxy=self._as_bool(profile.get("use_env_proxy", self.default_use_env_proxy), self.default_use_env_proxy),
            enable_thinking=options.enable_thinking,
            thinking=options.thinking,
            reasoning_effort=options.reasoning_effort,
            detail=options.detail,
            image_pixel_limit=options.image_pixel_limit,
            expected_list_key=expected_list_key,
        )

    def invoke_text(
        self,
        *,
        profile: Dict[str, Any],
        prompt: str,
        data_urls: List[str],
        max_tokens: Optional[int] = None,
        thinking_override: Optional[str] = None,
        reasoning_effort_override: Optional[str] = None,
        detail_override: Optional[str] = None,
        image_pixel_limit_override: Optional[Dict[str, Any]] = None,
    ) -> str:
        options = self.build_invocation_options(
            profile,
            max_tokens=max_tokens,
            thinking_override=thinking_override,
            reasoning_effort_override=reasoning_effort_override,
            detail_override=detail_override,
            image_pixel_limit_override=image_pixel_limit_override,
        )
        if self._should_use_langchain_runtime(profile):
            return self._get_langchain_agent(profile).invoke_text(
                prompt=prompt,
                data_urls=data_urls,
                max_tokens=options.token_limit,
                enable_thinking=options.enable_thinking,
                thinking=options.thinking,
                reasoning_effort=options.reasoning_effort,
                detail=options.detail,
            )
        return self._legacy_text_caller(
            base_url=profile["base_url"],
            api_key=profile["api_key"],
            model=profile["model"],
            provider=str(profile.get("provider", "openai_compatible")),
            prompt=prompt,
            data_urls=data_urls,
            timeout=int(profile.get("timeout_sec", 120)),
            max_retries=int(profile.get("max_retries", 2)),
            backoff_base_sec=float(profile.get("backoff_base_sec", 1.5)),
            min_interval_sec=float(profile.get("min_interval_sec", 0.0)),
            max_tokens=options.token_limit,
            use_env_proxy=self._as_bool(profile.get("use_env_proxy", self.default_use_env_proxy), self.default_use_env_proxy),
            enable_thinking=options.enable_thinking,
            thinking=options.thinking,
            reasoning_effort=options.reasoning_effort,
            detail=options.detail,
            image_pixel_limit=options.image_pixel_limit,
        )

    def run_stage(
        self,
        spec: HarnessStageSpec,
        *,
        profile: Dict[str, Any],
        prompt: str,
        data_urls: List[str],
        max_tokens: Optional[int] = None,
        expected_list_key: Optional[str] = None,
        thinking_override: Optional[str] = None,
        reasoning_effort_override: Optional[str] = None,
        detail_override: Optional[str] = None,
        image_pixel_limit_override: Optional[Dict[str, Any]] = None,
    ) -> Any:
        resolved_expected_list_key = expected_list_key if expected_list_key is not None else spec.expected_list_key
        resolved_thinking_override = thinking_override if thinking_override is not None else spec.thinking_override
        resolved_reasoning_effort_override = (
            reasoning_effort_override if reasoning_effort_override is not None else spec.reasoning_effort_override
        )
        resolved_detail_override = detail_override if detail_override is not None else spec.detail_override
        if spec.mode == "json":
            return self.invoke_json(
                profile=profile,
                prompt=prompt,
                data_urls=data_urls,
                max_tokens=max_tokens,
                expected_list_key=resolved_expected_list_key,
                thinking_override=resolved_thinking_override,
                reasoning_effort_override=resolved_reasoning_effort_override,
                detail_override=resolved_detail_override,
                image_pixel_limit_override=image_pixel_limit_override,
            )
        if spec.mode == "text":
            return self.invoke_text(
                profile=profile,
                prompt=prompt,
                data_urls=data_urls,
                max_tokens=max_tokens,
                thinking_override=resolved_thinking_override,
                reasoning_effort_override=resolved_reasoning_effort_override,
                detail_override=resolved_detail_override,
                image_pixel_limit_override=image_pixel_limit_override,
            )
        raise ValueError(f"unsupported harness stage mode: {spec.mode}")
