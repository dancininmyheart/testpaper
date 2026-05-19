from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, TypeVar

from pydantic import BaseModel

from backend.infrastructure.ai.profiles import AIProfile
from langchain_compat import ensure_langchain_root_globals

try:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI
except Exception as exc:  # pragma: no cover - optional dependency
    ChatOpenAI = None  # type: ignore[assignment]
    HumanMessage = None  # type: ignore[assignment]
    SystemMessage = None  # type: ignore[assignment]
    _IMPORT_ERROR = str(exc)
else:
    _IMPORT_ERROR = ""


SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LangChainUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMTrace:
    stage_name: str
    profile: str
    model: str
    prompt_version: str
    elapsed_ms: float
    output_mode: str
    raw_status: str
    parsed_status: str
    warnings: list[str] = field(default_factory=list)
    token_estimate: int | None = None

    def as_stage_log(self) -> dict[str, Any]:
        return {
            "stage": self.stage_name,
            "status": "ok" if self.parsed_status == "ok" else "partial",
            "profile": self.profile,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "elapsed_ms": self.elapsed_ms,
            "output_mode": self.output_mode,
            "raw_status": self.raw_status,
            "parsed_status": self.parsed_status,
            "warnings": self.warnings,
            "token_estimate": self.token_estimate,
        }


def is_langchain_available() -> bool:
    return ChatOpenAI is not None and HumanMessage is not None and SystemMessage is not None


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                chunks.append(item.strip())
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
        return "\n".join(chunks).strip()
    return ""


class LangChainModelFactory:
    def __init__(self) -> None:
        if not is_langchain_available():
            raise LangChainUnavailableError(f"LangChain runtime is unavailable: {_IMPORT_ERROR}")

    def build_chat_model(self, profile: AIProfile) -> Any:
        extra_body: dict[str, Any] = {}
        if profile.use_responses_api:
            extra_body["thinking"] = {"type": profile.thinking}
            if profile.thinking != "disabled":
                extra_body["reasoning"] = {"effort": profile.reasoning_effort}
        else:
            if profile.enable_thinking:
                extra_body["enable_thinking"] = True
            if profile.thinking in {"enabled", "disabled", "auto"}:
                extra_body["thinking"] = {"type": profile.thinking}
            if profile.reasoning_effort:
                extra_body["reasoning_effort"] = profile.reasoning_effort
        kwargs: dict[str, Any] = {
            "model": profile.model,
            "api_key": profile.api_key,
            "base_url": profile.base_url,
            "temperature": 0,
            "max_retries": 0,
            "request_timeout": profile.timeout_sec,
            "metadata": {
                "ls_model_name": profile.model,
                "ls_provider": profile.provider,
                "profile": profile.name,
            },
        }
        if profile.use_responses_api:
            kwargs["use_responses_api"] = True
        if profile.output_version:
            kwargs["output_version"] = profile.output_version
        if profile.max_tokens > 0:
            kwargs["max_tokens"] = profile.max_tokens
        if extra_body:
            kwargs["extra_body"] = extra_body
        ensure_langchain_root_globals()
        return ChatOpenAI(**kwargs)

    @staticmethod
    def build_human_content(prompt: str, data_urls: list[str], *, use_responses_api: bool, detail: str | None) -> Any:
        if not data_urls:
            return [{"type": "input_text", "text": prompt}] if use_responses_api else prompt
        content: list[dict[str, Any]] = [
            {"type": "input_text", "text": prompt} if use_responses_api else {"type": "text", "text": prompt}
        ]
        for data_url in data_urls:
            if use_responses_api:
                item: dict[str, Any] = {"type": "input_image", "image_url": data_url}
                if detail:
                    item["detail"] = detail
                content.append(item)
            else:
                image_url: dict[str, Any] = {"url": data_url}
                if detail:
                    image_url["detail"] = detail
                content.append({"type": "image_url", "image_url": image_url})
        return content


class LangChainLLMClient:
    _interval_lock = Lock()
    _last_request_ts = 0.0

    def __init__(self, *, profile: AIProfile, factory: LangChainModelFactory | None = None) -> None:
        self.profile = profile
        self.factory = factory or LangChainModelFactory()

    def _respect_min_interval(self) -> None:
        if self.profile.min_interval_sec <= 0:
            return
        with self._interval_lock:
            now = time.monotonic()
            wait_sec = self.profile.min_interval_sec - (now - self.__class__._last_request_ts)
            if wait_sec > 0:
                time.sleep(wait_sec)
                now = time.monotonic()
            self.__class__._last_request_ts = now

    def _messages(self, *, system_prompt: str, prompt: str, data_urls: list[str]) -> list[Any]:
        return [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=self.factory.build_human_content(
                    prompt,
                    data_urls,
                    use_responses_api=self.profile.use_responses_api,
                    detail=self.profile.detail,
                )
            ),
        ]

    def invoke_text(
        self,
        *,
        stage_name: str,
        system_prompt: str,
        prompt: str,
        data_urls: list[str] | None = None,
        prompt_version: str = "v1",
    ) -> tuple[str, LLMTrace]:
        started = time.perf_counter()
        last_exc: Exception | None = None
        for attempt in range(self.profile.max_retries + 1):
            try:
                model = self.factory.build_chat_model(self.profile)
                self._respect_min_interval()
                response = model.invoke(
                    self._messages(system_prompt=system_prompt, prompt=prompt, data_urls=data_urls or []),
                    {
                        "run_name": stage_name,
                        "tags": ["analysis", stage_name],
                        "metadata": self.profile.trace_metadata(),
                    },
                )
                text = _content_to_text(getattr(response, "content", ""))
                if not text:
                    raise ValueError("LangChain returned empty content")
                elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
                return text, LLMTrace(
                    stage_name=stage_name,
                    profile=self.profile.name,
                    model=self.profile.model,
                    prompt_version=prompt_version,
                    elapsed_ms=elapsed_ms,
                    output_mode="text",
                    raw_status="ok",
                    parsed_status="ok",
                    token_estimate=max(1, len(prompt) // 4),
                )
            except Exception as exc:
                last_exc = exc
                if attempt >= self.profile.max_retries:
                    break
                time.sleep(self.profile.backoff_base_sec * max(1, 2 ** attempt))
        assert last_exc is not None
        raise last_exc

    def invoke_structured(
        self,
        *,
        stage_name: str,
        schema: type[SchemaT],
        system_prompt: str,
        prompt: str,
        data_urls: list[str] | None = None,
        prompt_version: str = "v1",
    ) -> tuple[SchemaT, LLMTrace]:
        started = time.perf_counter()
        warnings: list[str] = []
        last_exc: Exception | None = None
        for attempt in range(self.profile.max_retries + 1):
            try:
                model = self.factory.build_chat_model(self.profile)
                structured = model.with_structured_output(
                    schema,
                    method=self.profile.structured_output_method,
                    include_raw=True,
                    strict=self.profile.strict_structured_output,
                )
                self._respect_min_interval()
                raw = structured.invoke(
                    self._messages(system_prompt=system_prompt, prompt=prompt, data_urls=data_urls or []),
                    {
                        "run_name": stage_name,
                        "tags": ["analysis", stage_name],
                        "metadata": self.profile.trace_metadata(),
                    },
                )
                parsed = raw.get("parsed") if isinstance(raw, dict) else raw
                parsing_error = raw.get("parsing_error") if isinstance(raw, dict) else None
                if parsing_error is not None:
                    warnings.append(str(parsing_error))
                if isinstance(parsed, schema):
                    value = parsed
                elif isinstance(parsed, dict):
                    value = schema.model_validate(parsed)
                else:
                    raise ValueError(f"LangChain structured output is not {schema.__name__}")
                elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
                return value, LLMTrace(
                    stage_name=stage_name,
                    profile=self.profile.name,
                    model=self.profile.model,
                    prompt_version=prompt_version,
                    elapsed_ms=elapsed_ms,
                    output_mode="structured",
                    raw_status="ok",
                    parsed_status="ok",
                    warnings=warnings,
                    token_estimate=max(1, len(prompt) // 4),
                )
            except Exception as exc:
                last_exc = exc
                if attempt >= self.profile.max_retries:
                    break
                time.sleep(self.profile.backoff_base_sec * max(1, 2 ** attempt))
        assert last_exc is not None
        raise last_exc
