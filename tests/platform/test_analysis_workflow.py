from __future__ import annotations

from backend.application.workflows import AnalysisWorkflow
from backend.application.workflows.analysis_workflow import V1_ANALYSIS_STAGE_SEQUENCE


class _FakeLegacyRunner:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, payload):
        self.calls += 1
        return {
            "student_id": payload["student_id"],
            "analysis_process": {
                "stages": [
                    {"stage": "legacy_validate_input", "status": "ok"},
                    {"stage": "legacy_done", "status": "ok"},
                ]
            },
        }


def test_workflow_wraps_legacy_runner_and_preserves_stage_logs() -> None:
    runner = _FakeLegacyRunner()
    workflow = AnalysisWorkflow(legacy_runner=runner)

    output = workflow.run({"student_id": "S001", "input_mode": "paper_answer_with_key"})

    assert runner.calls == 1
    assert output.result["student_id"] == "S001"
    assert output.result["analysis_process"]["workflow"] == "AnalysisWorkflow_v1"
    assert [item["stage"] for item in output.stage_logs[: len(V1_ANALYSIS_STAGE_SEQUENCE)]] == V1_ANALYSIS_STAGE_SEQUENCE
    assert output.stage_logs[len(V1_ANALYSIS_STAGE_SEQUENCE)]["stage"] == "legacy_validate_input"
    assert output.stage_logs[-1]["stage"] == "legacy_done"
    assert output.result["analysis_process"]["stages"][: len(V1_ANALYSIS_STAGE_SEQUENCE)] == output.stage_logs[
        : len(V1_ANALYSIS_STAGE_SEQUENCE)
    ]


def test_non_v1_input_mode_uses_legacy_fallback_stages_only() -> None:
    runner = _FakeLegacyRunner()
    workflow = AnalysisWorkflow(legacy_runner=runner)

    output = workflow.run({"student_id": "S001", "input_mode": "paper_answer_auto_key"})

    assert runner.calls == 1
    assert [item["stage"] for item in output.stage_logs[:3]] == [
        "00_validate_input",
        "02_legacy_analysis_adapter",
        "03_collect_result",
    ]
    assert "01_validate_input" not in [item["stage"] for item in output.stage_logs]


def test_v1_workflow_stage_logs_use_normalized_contract() -> None:
    workflow = AnalysisWorkflow(legacy_runner=_FakeLegacyRunner())

    output = workflow.run({"student_id": "S001", "input_mode": "paper_answer_with_key"})

    for entry in output.stage_logs:
        assert isinstance(entry["stage"], str) and entry["stage"]
        assert entry["status"] in {"succeeded", "partial", "failed", "skipped"}
        assert isinstance(entry.get("elapsed_ms"), (int, float))


def test_workflow_rejects_missing_input_mode() -> None:
    workflow = AnalysisWorkflow(legacy_runner=_FakeLegacyRunner())

    try:
        workflow.run({"student_id": "S001"})
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "input_mode is required" in str(exc)
