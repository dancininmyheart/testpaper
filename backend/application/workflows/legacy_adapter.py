from __future__ import annotations

import time
from typing import Any, Protocol


class LegacyAnalysisRunner(Protocol):
    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    def _ensure_new_points(self, questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ...


_STATUS_MAP = {
    "ok": "succeeded",
    "success": "succeeded",
    "done": "succeeded",
    "error": "failed",
}
_ALLOWED_STATUS = {"succeeded", "partial", "failed", "skipped"}


def normalize_stage_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    status = _STATUS_MAP.get(status, status)
    return status if status in _ALLOWED_STATUS else "partial"


def normalize_stage_log(entry: dict[str, Any]) -> dict[str, Any]:
    stage = str(entry.get("stage") or "").strip() or "legacy_stage"
    normalized: dict[str, Any] = {
        "stage": stage,
        "status": normalize_stage_status(entry.get("status")),
    }
    elapsed = entry.get("elapsed_ms")
    if isinstance(elapsed, (int, float)):
        normalized["elapsed_ms"] = round(float(elapsed), 1)
    else:
        normalized["elapsed_ms"] = 0.0
    warnings = entry.get("warnings")
    if isinstance(warnings, list) and warnings:
        normalized["warnings"] = warnings
    error_message = entry.get("error_message") or entry.get("error")
    if isinstance(error_message, str) and error_message.strip():
        normalized["error_message"] = error_message.strip()
    for key, value in entry.items():
        if key not in normalized and key not in {"status", "elapsed_ms", "warnings", "error_message", "error"}:
            normalized[key] = value
    return normalized


class LegacyAnalysisAdapter:
    def __init__(self, runner: LegacyAnalysisRunner):
        self.runner = runner

    @staticmethod
    def extract_stage_logs(result: dict[str, Any]) -> list[dict[str, Any]]:
        process = result.get("analysis_process")
        if isinstance(process, dict) and isinstance(process.get("stages"), list):
            return [
                normalize_stage_log(item)
                for item in process["stages"]
                if isinstance(item, dict)
            ]
        return []

    def run(self, payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], float]:
        started = time.perf_counter()
        result = self.runner.run(payload)
        if not isinstance(result, dict):
            raise RuntimeError("legacy runner result is not object")
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        return result, self.extract_stage_logs(result), elapsed_ms
