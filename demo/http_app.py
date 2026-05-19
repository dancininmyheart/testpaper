from __future__ import annotations

import argparse
import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from time import perf_counter
from typing import Any, Dict
from urllib.parse import urlparse

try:
    from .http_utils import (
        _binary_download_response,
        _json_download_response,
        _json_response,
        _terminal_log,
        _text_response,
    )
    from .service import (
        DemoService,
        _TEMPORAL_IMPORT_ERROR,
        _build_export_payload,
        _build_export_pdf_bytes,
        run_temporal_demo,
    )
except ImportError:  # pragma: no cover - script execution fallback
    from demo.http_utils import (  # type: ignore[no-redef]
        _binary_download_response,
        _json_download_response,
        _json_response,
        _terminal_log,
        _text_response,
    )
    from demo.service import (  # type: ignore[no-redef]
        DemoService,
        _TEMPORAL_IMPORT_ERROR,
        _build_export_payload,
        _build_export_pdf_bytes,
        run_temporal_demo,
    )


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_ui_html() -> str:
    path = _project_root() / "demo_index.html"
    return path.read_text(encoding="utf-8")


def _load_temporal_ui_html() -> str:
    path = _project_root() / "demo_temporal_index.html"
    return path.read_text(encoding="utf-8")


def _resolve_export_result(service: DemoService, payload: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    request_payload = payload.get("request_payload")
    result_payload = payload.get("result")
    if isinstance(result_payload, dict):
        return result_payload, request_payload if isinstance(request_payload, dict) else {}
    if isinstance(request_payload, dict):
        return service.run(request_payload), request_payload
    raise ValueError("request_payload or result is required")


def make_handler(service: DemoService):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path in {"/", "/index.html"}:
                _text_response(self, 200, _load_ui_html())
                return
            if path in {"/temporal", "/temporal.html"}:
                _text_response(self, 200, _load_temporal_ui_html())
                return
            if path == "/api/demo/model-options":
                _json_response(self, 200, {"ok": True, "result": service.get_model_options()})
                return
            _json_response(self, 404, {"detail": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            request_started = perf_counter()
            try:
                content_len = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(content_len)
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("request must be json object")
                student_id = str(payload.get("student_id") or "").strip() or "unknown"
                input_mode = str(payload.get("input_mode") or "").strip()
                _terminal_log(
                    f"[http] path={path} method=POST student_id={student_id} input_mode={input_mode} "
                    f"content_length={content_len}"
                )
                if path == "/api/demo/run":
                    result = service.run(payload)
                elif path == "/api/demo/segment/mineru":
                    result = service.build_mineru_segment_preview(payload)
                elif path == "/api/demo/segment/refine":
                    result = service.build_refine_segment_preview(payload)
                elif path == "/api/demo/export":
                    result, request_payload = _resolve_export_result(service, payload)
                    export_payload = _build_export_payload(
                        request_payload,
                        result,
                    )
                    export_student_id = result.get("student_id") if isinstance(result.get("student_id"), str) else "unknown"
                    export_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"analysis_export_{export_student_id}_{export_timestamp}.json"
                    _json_download_response(self, 200, export_payload, filename)
                    return
                elif path == "/api/demo/export/pdf":
                    result, request_payload = _resolve_export_result(service, payload)
                    pdf_bytes = _build_export_pdf_bytes(
                        request_payload,
                        result,
                    )
                    export_student_id = result.get("student_id") if isinstance(result.get("student_id"), str) else "unknown"
                    export_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"analysis_report_{export_student_id}_{export_timestamp}.pdf"
                    _binary_download_response(
                        self,
                        200,
                        pdf_bytes,
                        filename,
                        content_type="application/pdf",
                    )
                    return
                elif path == "/api/demo/temporal/run":
                    if run_temporal_demo is None:
                        raise RuntimeError(f"temporal demo unavailable: {_TEMPORAL_IMPORT_ERROR}")
                    result = run_temporal_demo(payload)
                else:
                    _json_response(self, 404, {"detail": "not found"})
                    _terminal_log(f"[http] path={path} method=POST status=404 elapsed_ms={round((perf_counter() - request_started) * 1000, 1)}")
                    return
                _json_response(self, 200, {"ok": True, "result": result})
                _terminal_log(
                    f"[http] path={path} method=POST status=200 student_id={student_id} "
                    f"elapsed_ms={round((perf_counter() - request_started) * 1000, 1)}"
                )
            except Exception as exc:
                _json_response(self, 400, {"ok": False, "error": str(exc)})
                _terminal_log(
                    f"[http] path={path} method=POST status=400 error={exc} "
                    f"elapsed_ms={round((perf_counter() - request_started) * 1000, 1)}"
                )

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo server for paper+answer VLM analysis.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--config", default="llm_config.json")
    parser.add_argument("--profile", default=None)
    parser.add_argument("--key-word", default="key_word.json")
    parser.add_argument("--mock", action="store_true", help="Run demo with mock results, no LLM call.")
    args = parser.parse_args()

    service = DemoService(
        Path(args.config),
        args.profile,
        Path(args.key_word),
        mock_mode=args.mock,
    )
    handler = make_handler(service)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Demo server running: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
