from __future__ import annotations

from typing import Any

from demo.service import (
    _build_export_payload,
    _build_export_pdf_bytes,
    run_temporal_demo,
)


class LegacyDemoApiService:
    def __init__(self, *, demo_service: Any) -> None:
        self.demo_service = demo_service

    def run_demo(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.demo_service.run(payload)

    def get_model_options(self) -> dict[str, Any]:
        return self.demo_service.get_model_options()

    def run_temporal(self, payload: dict[str, Any]) -> dict[str, Any]:
        if run_temporal_demo is None:
            raise RuntimeError("temporal demo is unavailable")
        return run_temporal_demo(payload)

    def export_json(self, payload: dict[str, Any]) -> tuple[str, bytes]:
        result, request_payload = self._resolve_result(payload)
        export_payload = _build_export_payload(request_payload, result)
        student_id = result.get("student_id") if isinstance(result.get("student_id"), str) else "unknown"
        filename = f"analysis_export_{student_id}.json"
        body = self._json_bytes(export_payload)
        return filename, body

    def export_pdf(self, payload: dict[str, Any]) -> tuple[str, bytes]:
        result, request_payload = self._resolve_result(payload)
        pdf_bytes = _build_export_pdf_bytes(request_payload, result)
        student_id = result.get("student_id") if isinstance(result.get("student_id"), str) else "unknown"
        filename = f"analysis_report_{student_id}.pdf"
        return filename, pdf_bytes

    def _resolve_result(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        request_payload = payload.get("request_payload")
        result_payload = payload.get("result")
        if isinstance(result_payload, dict):
            return result_payload, request_payload if isinstance(request_payload, dict) else {}
        if isinstance(request_payload, dict):
            return self.demo_service.run(request_payload), request_payload
        raise ValueError("request_payload or result is required")

    @staticmethod
    def _json_bytes(payload: dict[str, Any]) -> bytes:
        import json

        return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
