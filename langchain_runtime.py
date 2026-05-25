from __future__ import annotations

import time
from threading import Lock
from typing import Any, Dict, List, Optional

from langchain_compat import ensure_langchain_root_globals

try:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI
except Exception as exc:  # pragma: no cover - optional runtime dependency
    ChatOpenAI = None  # type: ignore[assignment]
    HumanMessage = None  # type: ignore[assignment]
    SystemMessage = None  # type: ignore[assignment]
    _LANGCHAIN_IMPORT_ERROR = str(exc)
else:
    _LANGCHAIN_IMPORT_ERROR = ""

try:
    from openai import LengthFinishReasonError
except ImportError:
    LengthFinishReasonError = None


def is_langchain_available() -> bool:
    return ChatOpenAI is not None and HumanMessage is not None and SystemMessage is not None


def _response_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: List[str] = []
        for item in content:
            if isinstance(item, str):
                if item.strip():
                    chunks.append(item.strip())
                continue
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "text":
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
            elif item_type == "output_text":
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
        return "\n".join(chunks).strip()
    return ""


def _is_unsupported_json_response_format_error(exc: Exception) -> bool:
    message = str(exc).lower()
    if "response_format" not in message:
        return False
    if "json_object" not in message:
        return False
    return any(token in message for token in {"not supported", "not valid", "invalidparameter", "badrequest"})


def _is_length_finish_reason_error(exc: Exception) -> bool:
    if LengthFinishReasonError is not None and isinstance(exc, LengthFinishReasonError):
        return True
    message = str(exc).lower()
    return "lengthfinishreasonerror" in message.replace(" ", "")


class LangChainAgentRuntime:
    _interval_lock = Lock()
    _last_request_ts = 0.0

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: int,
        max_retries: int,
        backoff_base_sec: float,
        min_interval_sec: float,
        use_responses_api: bool = False,
        output_version: Optional[str] = None,
    ) -> None:
        if not is_langchain_available():
            raise RuntimeError(f"langchain runtime is unavailable: {_LANGCHAIN_IMPORT_ERROR}")
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))
        self.backoff_base_sec = max(0.0, float(backoff_base_sec))
        self.min_interval_sec = max(0.0, float(min_interval_sec))
        self.use_responses_api = bool(use_responses_api)
        self.output_version = output_version.strip() if isinstance(output_version, str) and output_version.strip() else None

    def _respect_min_interval(self) -> None:
        if self.min_interval_sec <= 0:
            return
        with self._interval_lock:
            now = time.monotonic()
            wait_sec = self.min_interval_sec - (now - self._last_request_ts)
            if wait_sec > 0:
                time.sleep(wait_sec)
                now = time.monotonic()
            self.__class__._last_request_ts = now

    def _build_model(
        self,
        *,
        max_tokens: int,
        enable_thinking: bool,
        thinking: Optional[str],
        reasoning_effort: Optional[str],
    ) -> Any:
        extra_body: Dict[str, Any] = {}
        thinking_mode = thinking.strip().lower() if isinstance(thinking, str) and thinking.strip().lower() in {"enabled", "disabled", "auto"} else ("enabled" if enable_thinking else "disabled")
        reasoning_value = reasoning_effort.strip().lower() if isinstance(reasoning_effort, str) and reasoning_effort.strip().lower() in {"minimal", "low", "medium", "high"} else None
        if thinking_mode == "disabled":
            reasoning_value = None
        if self.use_responses_api:
            extra_body["thinking"] = {"type": thinking_mode}
            if thinking_mode != "disabled" and isinstance(reasoning_value, str):
                extra_body["reasoning"] = {"effort": reasoning_value}
        else:
            if enable_thinking:
                extra_body["enable_thinking"] = True
            if isinstance(thinking, str) and thinking.strip().lower() in {"enabled", "disabled", "auto"}:
                extra_body["thinking"] = {"type": thinking.strip().lower()}
            if isinstance(reasoning_value, str):
                extra_body["reasoning_effort"] = reasoning_value
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "temperature": 0,
            "max_retries": 0,
            "request_timeout": self.timeout,
        }
        if self.use_responses_api:
            kwargs["use_responses_api"] = True
        if isinstance(self.output_version, str):
            kwargs["output_version"] = self.output_version
        if max_tokens > 0:
            kwargs["max_tokens"] = max_tokens
        if extra_body:
            kwargs["extra_body"] = extra_body
        ensure_langchain_root_globals()
        return ChatOpenAI(**kwargs)

    def _build_human_content(self, prompt: str, data_urls: List[str], detail: Optional[str]) -> Any:
        if not data_urls:
            if self.use_responses_api:
                return [{"type": "input_text", "text": prompt}]
            return prompt
        detail_value = detail.strip().lower() if isinstance(detail, str) and detail.strip().lower() in {"auto", "low", "high", "xhigh"} else None
        content: List[Dict[str, Any]] = [
            {"type": "input_text", "text": prompt} if self.use_responses_api else {"type": "text", "text": prompt}
        ]
        for data_url in data_urls:
            if self.use_responses_api:
                image_item: Dict[str, Any] = {"type": "input_image", "image_url": data_url}
                if detail_value is not None:
                    image_item["detail"] = detail_value
                content.append(image_item)
            else:
                image_url: Dict[str, Any] = {"url": data_url}
                if detail_value is not None:
                    image_url["detail"] = detail_value
                content.append({"type": "image_url", "image_url": image_url})
        return content

    def _invoke(
        self,
        *,
        system_prompt: str,
        prompt: str,
        data_urls: List[str],
        max_tokens: int,
        enable_thinking: bool,
        thinking: Optional[str],
        reasoning_effort: Optional[str],
        detail: Optional[str],
        json_mode: bool,
    ) -> str:
        last_exc: Optional[Exception] = None
        _current_max_tokens = max_tokens
        _current_enable_thinking = enable_thinking
        _current_thinking = thinking
        for attempt in range(self.max_retries + 1):
            try:
                model = self._build_model(
                    max_tokens=_current_max_tokens,
                    enable_thinking=_current_enable_thinking,
                    thinking=_current_thinking,
                    reasoning_effort=reasoning_effort,
                )
                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=self._build_human_content(prompt, data_urls, detail)),
                ]

                def _invoke_once(bound_model: Any) -> str:
                    self._respect_min_interval()
                    response = bound_model.invoke(messages)
                    text = _response_to_text(getattr(response, "content", ""))
                    if not text:
                        raise ValueError("LangChain returned empty content")
                    return text

                if json_mode:
                    try:
                        return _invoke_once(model.bind(response_format={"type": "json_object"}))
                    except Exception as exc:
                        if _is_unsupported_json_response_format_error(exc):
                            return _invoke_once(model)
                        raise
                return _invoke_once(model)
            except Exception as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                _is_length_error = _is_length_finish_reason_error(exc)
                if _is_length_error:
                    _current_max_tokens = max(_current_max_tokens * 2, 32000)
                    _current_enable_thinking = False
                    _current_thinking = "disabled"
                time.sleep(self.backoff_base_sec * max(1, 2 ** attempt))
        assert last_exc is not None
        raise last_exc

    def invoke_text(
        self,
        *,
        prompt: str,
        data_urls: List[str],
        max_tokens: int,
        enable_thinking: bool,
        thinking: Optional[str],
        reasoning_effort: Optional[str],
        detail: Optional[str],
    ) -> str:
        return self._invoke(
            system_prompt="You are a precise educational analysis assistant. Be concise and to the point. Avoid unnecessary elaboration.",
            prompt=prompt,
            data_urls=data_urls,
            max_tokens=max_tokens,
            enable_thinking=enable_thinking,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            detail=detail,
            json_mode=False,
        )

    def invoke_json(
        self,
        *,
        prompt: str,
        data_urls: List[str],
        max_tokens: int,
        enable_thinking: bool,
        thinking: Optional[str],
        reasoning_effort: Optional[str],
        detail: Optional[str],
    ) -> str:
        return self._invoke(
            system_prompt="You are a strict JSON generator. Output valid JSON matching the requested schema. Be concise, avoid verbosity. No markdown fences, no extra text outside the JSON.",
            prompt=prompt,
            data_urls=data_urls,
            max_tokens=max_tokens,
            enable_thinking=enable_thinking,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            detail=detail,
            json_mode=True,
        )
