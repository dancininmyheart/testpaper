from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from typing import Any, Callable, Dict, List

from demo.data_utils import _canonical_question_id, _chunk_list, _has_answer_signal

from .base import StageResult


def run_blind_diagnosis_stage(
    questions: List[Dict[str, Any]],
    answers: List[Dict[str, Any]],
    *,
    text_profile: Dict[str, Any] | None,
    answer_concurrency: int,
    question_chunk_size: int,
    blind_diagnosis_max_items: int,
    harness_stage_blind_diagnosis: str,
    run_harness_stage: Callable,
    log_progress: Callable,
    blind_diagnosis_prompt_fn: Callable,
    should_run_fn: Callable,
    build_item_fn: Callable,
    diagnosis_priority_fn: Callable,
    normalize_payload_fn: Callable,
    warnings_out: List[str],
) -> StageResult:
    """Run blind diagnosis on student answers.

    Returns StageResult with ``output["diagnosis_by_id"]`` and
    ``output["diagnosis_count"]``.
    """
    started = perf_counter()
    question_by_id = {
        q.get("question_id"): q
        for q in questions
        if isinstance(q, dict) and isinstance(q.get("question_id"), str)
    }
    items: List[Dict[str, Any]] = []
    skipped_count = 0
    for answer in answers:
        qid = answer.get("question_id")
        if not isinstance(qid, str) or qid not in question_by_id:
            continue
        if not _has_answer_signal(answer):
            continue
        if not should_run_fn(answer):
            skipped_count += 1
            continue
        blind_item = build_item_fn(question_by_id[qid], answer)
        if blind_item is not None:
            items.append(blind_item)

    if blind_diagnosis_max_items > 0 and len(items) > blind_diagnosis_max_items:
        answer_by_id = {
            answer.get("question_id"): answer
            for answer in answers
            if isinstance(answer, dict) and isinstance(answer.get("question_id"), str)
        }
        items.sort(
            key=lambda item: diagnosis_priority_fn(answer_by_id.get(item.get("question_id"), {})),
            reverse=True,
        )
        skipped_count += len(items) - blind_diagnosis_max_items
        items = items[:blind_diagnosis_max_items]

    if not items:
        return StageResult(
            status="skipped",
            output={"diagnosis_by_id": {}, "diagnosis_count": 0,
                     "target_count": 0, "skipped_count": skipped_count},
            elapsed_ms=round((perf_counter() - started) * 1000, 1),
        )

    diagnosis_by_id: Dict[str, Dict[str, Any]] = {}
    chunks = [chunk for chunk in _chunk_list(items, question_chunk_size) if chunk]
    if not chunks:
        return StageResult(
            status="skipped",
            output={"diagnosis_by_id": {}, "diagnosis_count": 0,
                     "target_count": 0, "skipped_count": skipped_count},
            elapsed_ms=round((perf_counter() - started) * 1000, 1),
        )

    max_workers = min(max(1, answer_concurrency), len(chunks))
    log_progress(
        "blind_step_analysis",
        "chunk_start",
        item_count=len(items),
        chunk_count=len(chunks),
        max_workers=max_workers,
    )
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        tasks: List[tuple[int, int, float, Any]] = []
        for chunk_index, chunk in enumerate(chunks, start=1):
            tasks.append(
                (
                    chunk_index,
                    len(chunk),
                    perf_counter(),
                    executor.submit(
                        run_harness_stage,
                        harness_stage_blind_diagnosis,
                        prompt=blind_diagnosis_prompt_fn(chunk),
                        data_urls=[],
                        profile=text_profile,
                    ),
                )
            )
        for chunk_index, chunk_size, chunk_started, future in tasks:
            try:
                data = future.result()
            except Exception as exc:
                warnings_out.append(f"blind_step_analysis chunk={chunk_index} failed: {exc}")
                log_progress(
                    "blind_step_analysis",
                    "chunk_failed",
                    chunk=chunk_index,
                    item_count=chunk_size,
                    elapsed_ms=round((perf_counter() - chunk_started) * 1000, 1),
                )
                continue
            results = data.get("items", [])
            log_progress(
                "blind_step_analysis",
                "chunk_done",
                chunk=chunk_index,
                item_count=chunk_size,
                result_count=len(results) if isinstance(results, list) else 0,
                elapsed_ms=round((perf_counter() - chunk_started) * 1000, 1),
            )
            if not isinstance(results, list):
                continue
            for item in results:
                if not isinstance(item, dict):
                    continue
                qid = _canonical_question_id(item.get("question_id"))
                diagnosis = normalize_payload_fn(item.get("blind_diagnosis"))
                if isinstance(qid, str) and isinstance(diagnosis, dict):
                    diagnosis_by_id[qid] = diagnosis

    return StageResult(
        status="succeeded" if diagnosis_by_id else "partial",
        output={
            "diagnosis_by_id": diagnosis_by_id,
            "diagnosis_count": len(diagnosis_by_id),
            "target_count": len(items),
            "skipped_count": skipped_count,
        },
        warnings=warnings_out if isinstance(warnings_out, list) else [],
        elapsed_ms=round((perf_counter() - started) * 1000, 1),
    )


def create_blind_diagnosis_stage(service: Any) -> Callable[[Any], StageResult]:
    """Create a PipelineContext-based blind diagnosis stage wired to a DemoService instance."""

    from demo.service import (
        HARNESS_STAGE_BLIND_DIAGNOSIS,
        _blind_diagnosis_prompt,
        _build_blind_diagnosis_item,
        _diagnosis_priority_score,
        _normalize_blind_diagnosis_payload,
        _should_run_blind_diagnosis_for_answer,
    )

    def stage_fn(ctx: Any) -> StageResult:
        return run_blind_diagnosis_stage(
            questions=ctx.questions,
            answers=ctx.answers,
            text_profile=service.text_profile,
            answer_concurrency=service.answer_concurrency,
            question_chunk_size=service.question_chunk_size,
            blind_diagnosis_max_items=service.blind_diagnosis_max_items,
            harness_stage_blind_diagnosis=HARNESS_STAGE_BLIND_DIAGNOSIS,
            run_harness_stage=service._run_harness_stage,
            log_progress=service._log_progress,
            blind_diagnosis_prompt_fn=_blind_diagnosis_prompt,
            should_run_fn=_should_run_blind_diagnosis_for_answer,
            build_item_fn=_build_blind_diagnosis_item,
            diagnosis_priority_fn=_diagnosis_priority_score,
            normalize_payload_fn=_normalize_blind_diagnosis_payload,
            warnings_out=ctx.warnings,
        )

    return stage_fn
