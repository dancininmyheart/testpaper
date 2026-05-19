from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.domain.pipeline import AnalysisPipelineContext, AnalysisStageRun, DocumentPage

from .legacy_adapter import LegacyAnalysisAdapter, LegacyAnalysisRunner, normalize_stage_status


V1_INPUT_MODE = "paper_answer_with_key"
V1_ANALYSIS_STAGE_SEQUENCE = [
    "01_validate_input",
    "02_normalize_files",
    "03_extract_questions",
    "04_detect_answer_blocks",
    "05_recognize_student_answers",
    "06_parse_reference_answers",
    "07_align_answers",
    "08_judge_correctness",
    "09_analyze_mistakes",
    "10_build_student_profile",
    "11_ingest_mastery_events",
    "12_build_report",
]


@dataclass
class AnalysisWorkflowResult:
    result: dict[str, Any]
    stage_logs: list[dict[str, Any]] = field(default_factory=list)
    pipeline_context: AnalysisPipelineContext | None = None


class AnalysisWorkflow:
    """Application workflow for the v2 analysis pipeline.

    The v1 pipeline owns the uploaded paper + answer sheet + answer key path.
    Other input modes use an explicit legacy adapter so they remain stable while
    stages are migrated incrementally.
    """

    def __init__(self, *, legacy_runner: LegacyAnalysisRunner):
        self.legacy = LegacyAnalysisAdapter(legacy_runner)

    @staticmethod
    def _record(stage_logs: list[dict[str, Any]], stage: str, status: str, started: float, **extra: Any) -> None:
        run = AnalysisStageRun(
            stage=stage,
            status=normalize_stage_status(status),
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
            warnings=extra.pop("warnings", []) if isinstance(extra.get("warnings"), list) else [],
            error_message=extra.pop("error_message", None) if isinstance(extra.get("error_message"), str) else None,
            output={key: value for key, value in extra.items() if value is not None},
        )
        stage_logs.append(run.to_log())

    @staticmethod
    def _payload_files(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
        raw = payload.get(key)
        return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []

    @staticmethod
    def _pages_from_payload(payload: dict[str, Any], key: str) -> list[DocumentPage]:
        pages: list[DocumentPage] = []
        for index, item in enumerate(AnalysisWorkflow._payload_files(payload, key)):
            pages.append(
                DocumentPage(
                    artifact_id=str(item.get("id") or item.get("name") or f"{key}_{index + 1}"),
                    source_file=str(item.get("name") or ""),
                    page_index=index,
                    data_url=str(item.get("data_url") or ""),
                    metadata={k: v for k, v in item.items() if k not in {"id", "name", "data_url"}},
                )
            )
        return pages

    def _build_pipeline_context(self, payload: dict[str, Any]) -> AnalysisPipelineContext:
        return AnalysisPipelineContext(
            job_id=str(payload.get("job_id") or ""),
            student_id=str(payload.get("student_id") or "").strip() or "unknown",
            input_mode=str(payload.get("input_mode") or "").strip(),
            paper_pages=self._pages_from_payload(payload, "paper_files"),
            answer_sheet_pages=self._pages_from_payload(payload, "answer_sheet_files"),
            answer_key_pages=self._pages_from_payload(payload, "answer_key_files"),
            questions=(
                list(payload.get("_paper_questions") or payload.get("_pre_injected_questions") or [])
                if isinstance(payload.get("_paper_questions") or payload.get("_pre_injected_questions") or [], list)
                else []
            ),
            reference_answers=(
                list(payload.get("_paper_reference_answers") or payload.get("_pre_injected_reference_answers") or [])
                if isinstance(
                    payload.get("_paper_reference_answers") or payload.get("_pre_injected_reference_answers") or [],
                    list,
                )
                else []
            ),
            answer_blocks=(
                list(payload.get("selected_answer_blocks") or [])
                if isinstance(payload.get("selected_answer_blocks"), list)
                else []
            ),
            metadata={
                "vision_profile": str(payload.get("vision_profile") or ""),
                "text_profile": str(payload.get("text_profile") or ""),
                "paper_project_id": str(payload.get("_paper_project_id") or ""),
            },
        )

    def _run_stage(
        self,
        stage_logs: list[dict[str, Any]],
        name: str,
        fn: Callable[[], tuple[str, dict[str, Any] | None, list[str] | None]],
    ) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            status, output, warnings = fn()
            run = AnalysisStageRun(
                stage=name,
                status=normalize_stage_status(status),
                elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
                warnings=warnings or [],
                output=output or {},
            )
        except Exception as exc:
            run = AnalysisStageRun(
                stage=name,
                status="failed",
                elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
                error_message=str(exc),
            )
        entry = run.to_log()
        stage_logs.append(entry)
        return entry

    def _run_legacy_fallback(self, payload: dict[str, Any], input_mode: str) -> AnalysisWorkflowResult:
        stage_logs: list[dict[str, Any]] = []
        started = time.perf_counter()
        self._record(
            stage_logs,
            "00_validate_input",
            "succeeded" if input_mode else "failed",
            started,
            input_mode=input_mode,
            student_id=str(payload.get("student_id") or ""),
        )
        if not input_mode:
            raise ValueError("input_mode is required")

        result, legacy_stage_logs, legacy_elapsed_ms = self.legacy.run(payload)
        self._record(
            stage_logs,
            "02_legacy_analysis_adapter",
            "succeeded",
            time.perf_counter() - (legacy_elapsed_ms / 1000.0),
            delegated_stage_count=len(legacy_stage_logs),
        )
        self._record(stage_logs, "03_collect_result", "succeeded", time.perf_counter(), result_keys=len(result.keys()))

        all_stage_logs = stage_logs + legacy_stage_logs
        self._attach_process(result, workflow="AnalysisWorkflow_legacy_fallback", stage_logs=all_stage_logs)
        return AnalysisWorkflowResult(
            result=result,
            stage_logs=all_stage_logs,
            pipeline_context=self._build_pipeline_context(payload),
        )

    @staticmethod
    def _reference_answers_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
        raw = result.get("reference_answers")
        return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []

    @staticmethod
    def _questions_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
        for key in ("question_analysis", "structured_questions_full"):
            raw = result.get(key)
            if isinstance(raw, list):
                return [item for item in raw if isinstance(item, dict)]
        return []

    @staticmethod
    def _student_answers_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
        raw = result.get("answer_trace")
        return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []

    @staticmethod
    def _judgements_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
        raw = result.get("answer_key_correctness") or result.get("correctness")
        if isinstance(raw, dict) and isinstance(raw.get("items"), list):
            return [item for item in raw["items"] if isinstance(item, dict)]
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]
        return []

    @staticmethod
    def _attach_process(result: dict[str, Any], *, workflow: str, stage_logs: list[dict[str, Any]]) -> None:
        result.setdefault("analysis_process", {})
        if isinstance(result["analysis_process"], dict):
            result["analysis_process"]["workflow"] = workflow
            result["analysis_process"]["stages"] = stage_logs
            result["analysis_process"]["workflow_stages"] = stage_logs

    def _run_v1_pipeline(self, payload: dict[str, Any]) -> AnalysisWorkflowResult:
        ctx = self._build_pipeline_context(payload)
        stage_logs: list[dict[str, Any]] = []
        legacy_result: dict[str, Any] | None = None
        legacy_stage_logs: list[dict[str, Any]] = []

        def ensure_legacy_result() -> dict[str, Any]:
            nonlocal legacy_result, legacy_stage_logs
            if legacy_result is None:
                legacy_result, legacy_stage_logs, _ = self.legacy.run(payload)
                legacy_result.setdefault("student_id", ctx.student_id)
                legacy_result.setdefault("input_mode", ctx.input_mode)
            return legacy_result

        def validate_input() -> tuple[str, dict[str, Any], list[str]]:
            warnings: list[str] = []
            if not ctx.student_id:
                raise ValueError("student_id is required")
            if ctx.input_mode != V1_INPUT_MODE:
                raise ValueError(f"input_mode must be {V1_INPUT_MODE}")
            if not ctx.paper_pages and not payload.get("_skip_extraction"):
                warnings.append("paper_files is empty; legacy adapter may reject the request")
            if not ctx.answer_key_pages and not payload.get("_skip_reference_generation"):
                warnings.append("answer_key_files is empty; uploaded answer key is expected for v1")
            return "succeeded", {
                "input_mode": ctx.input_mode,
                "student_id": ctx.student_id,
                "paper_page_count": len(ctx.paper_pages),
                "answer_page_count": len(ctx.answer_sheet_pages),
                "answer_key_page_count": len(ctx.answer_key_pages),
            }, warnings

        def normalize_files() -> tuple[str, dict[str, Any], list[str]]:
            return "succeeded", {
                "paper_page_count": len(ctx.paper_pages),
                "answer_page_count": len(ctx.answer_sheet_pages),
                "answer_key_page_count": len(ctx.answer_key_pages),
            }, []

        def extract_questions() -> tuple[str, dict[str, Any], list[str]]:
            if not ctx.questions:
                result = ensure_legacy_result()
                ctx.questions = self._questions_from_result(result)
            status = "succeeded" if ctx.questions else "partial"
            return status, {"question_count": len(ctx.questions)}, []

        def detect_answer_blocks() -> tuple[str, dict[str, Any], list[str]]:
            if not ctx.answer_blocks:
                result = ensure_legacy_result()
                mapping_report = result.get("mapping_report")
                if isinstance(mapping_report, dict):
                    blocks = mapping_report.get("selected_answer_blocks") or mapping_report.get("answer_blocks")
                    if isinstance(blocks, list):
                        ctx.answer_blocks = [item for item in blocks if isinstance(item, dict)]
            return ("succeeded" if ctx.answer_blocks else "skipped"), {"answer_block_count": len(ctx.answer_blocks)}, []

        def recognize_student_answers() -> tuple[str, dict[str, Any], list[str]]:
            result = ensure_legacy_result()
            ctx.student_answers = self._student_answers_from_result(result)
            return ("succeeded" if ctx.student_answers else "partial"), {"student_answer_count": len(ctx.student_answers)}, []

        def parse_reference_answers() -> tuple[str, dict[str, Any], list[str]]:
            if not ctx.reference_answers:
                ctx.reference_answers = self._reference_answers_from_result(ensure_legacy_result())
            return (
                "succeeded" if ctx.reference_answers else "partial",
                {"reference_answer_count": len(ctx.reference_answers)},
                [],
            )

        def align_answers() -> tuple[str, dict[str, Any], list[str]]:
            mapped_count = 0
            result = ensure_legacy_result()
            mapping = result.get("mapping_report")
            if isinstance(mapping, dict):
                raw_count = mapping.get("mapped_questions") or mapping.get("mapped_count")
                if isinstance(raw_count, (int, float)):
                    mapped_count = int(raw_count)
            if not mapped_count:
                mapped_count = min(len(ctx.questions), len(ctx.student_answers))
            return ("succeeded" if mapped_count else "partial"), {"mapped_question_count": mapped_count}, []

        def judge_correctness() -> tuple[str, dict[str, Any], list[str]]:
            ctx.judgements = self._judgements_from_result(ensure_legacy_result())
            if not ctx.judgements and ctx.student_answers:
                ctx.judgements = [
                    item for item in ctx.student_answers if isinstance(item.get("correctness"), dict)
                ]
            return ("succeeded" if ctx.judgements else "partial"), {"judgement_count": len(ctx.judgements)}, []

        def analyze_mistakes() -> tuple[str, dict[str, Any], list[str]]:
            result = ensure_legacy_result()
            diagnosis_count = 0
            for answer in ctx.student_answers:
                if isinstance(answer.get("blind_diagnosis"), dict) or isinstance(answer.get("error_analysis"), dict):
                    diagnosis_count += 1
            if not diagnosis_count and isinstance(result.get("student_profile"), dict):
                diagnosis_count = len(result["student_profile"].get("weaknesses") or [])
            return ("succeeded" if diagnosis_count else "skipped"), {"diagnosis_count": diagnosis_count}, []

        def build_student_profile() -> tuple[str, dict[str, Any], list[str]]:
            profile = ensure_legacy_result().get("student_profile")
            return ("succeeded" if isinstance(profile, dict) else "skipped"), {
                "has_student_profile": isinstance(profile, dict)
            }, []

        def ingest_mastery_events() -> tuple[str, dict[str, Any], list[str]]:
            result = ensure_legacy_result()
            events = result.get("mastery_events")
            event_count = len(events) if isinstance(events, list) else 0
            return ("succeeded" if event_count else "skipped"), {"mastery_event_count": event_count}, []

        def build_report() -> tuple[str, dict[str, Any], list[str]]:
            result = ensure_legacy_result()
            result.setdefault("student_id", ctx.student_id)
            result.setdefault("input_mode", ctx.input_mode)
            return "succeeded", {"result_keys": len(result.keys())}, []

        stage_fns: list[tuple[str, Callable[[], tuple[str, dict[str, Any] | None, list[str] | None]]]] = [
            ("01_validate_input", validate_input),
            ("02_normalize_files", normalize_files),
            ("03_extract_questions", extract_questions),
            ("04_detect_answer_blocks", detect_answer_blocks),
            ("05_recognize_student_answers", recognize_student_answers),
            ("06_parse_reference_answers", parse_reference_answers),
            ("07_align_answers", align_answers),
            ("08_judge_correctness", judge_correctness),
            ("09_analyze_mistakes", analyze_mistakes),
            ("10_build_student_profile", build_student_profile),
            ("11_ingest_mastery_events", ingest_mastery_events),
            ("12_build_report", build_report),
        ]
        for name, stage_fn in stage_fns:
            entry = self._run_stage(stage_logs, name, stage_fn)
            if entry["status"] == "failed":
                break

        result = ensure_legacy_result()
        all_stage_logs = stage_logs + legacy_stage_logs
        self._attach_process(result, workflow="AnalysisWorkflow_v1", stage_logs=all_stage_logs)
        return AnalysisWorkflowResult(result=result, stage_logs=all_stage_logs, pipeline_context=ctx)

    def run(self, payload: dict[str, Any]) -> AnalysisWorkflowResult:
        input_mode = str(payload.get("input_mode") or "").strip()
        if not input_mode:
            self._run_legacy_fallback(payload, input_mode)
            raise ValueError("input_mode is required")
        if input_mode != V1_INPUT_MODE:
            return self._run_legacy_fallback(payload, input_mode)
        return self._run_v1_pipeline(payload)
