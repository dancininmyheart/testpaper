from __future__ import annotations

import unittest
from unittest.mock import Mock

from demo.http_app import _resolve_export_result


class HttpAppExportTests(unittest.TestCase):
    def test_resolve_export_result_prefers_result_payload(self) -> None:
        service = Mock()
        payload = {
            "request_payload": {"student_id": "s1"},
            "result": {"student_id": "s2", "value": 1},
        }
        result, request_payload = _resolve_export_result(service, payload)
        self.assertEqual(result["student_id"], "s2")
        self.assertEqual(request_payload, {"student_id": "s1"})
        service.run.assert_not_called()

    def test_resolve_export_result_falls_back_to_run(self) -> None:
        service = Mock()
        service.run.return_value = {"student_id": "s3", "value": 2}
        payload = {"request_payload": {"student_id": "s3"}}
        result, request_payload = _resolve_export_result(service, payload)
        self.assertEqual(result["student_id"], "s3")
        self.assertEqual(request_payload, {"student_id": "s3"})
        service.run.assert_called_once_with({"student_id": "s3"})

    def test_resolve_export_result_requires_request_or_result(self) -> None:
        service = Mock()
        with self.assertRaisesRegex(ValueError, "request_payload or result is required"):
            _resolve_export_result(service, {})


if __name__ == "__main__":
    unittest.main()
