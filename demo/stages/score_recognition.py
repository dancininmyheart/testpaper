from __future__ import annotations

from time import perf_counter
from typing import Any, Callable, Dict, List

from .base import StageResult


def run_score_recognition_stage(
    answer_urls: List[str],
    answer_contexts: List[Dict[str, Any]],
    answer_candidates: List[Dict[str, Any]],
    *,
    profile: Dict[str, Any] | None,
    harness_stage_answer_score: Any,
    run_harness_stage: Callable,
    log_progress: Callable,
    answer_score_sheet_prompt_fn: Callable,
    build_candidate_summaries_fn: Callable,
    build_answer_context_map_fn: Callable,
    normalize_answer_item_fn: Callable,
    warnings_out: List[str],
) -> StageResult:
    """Run answer score recognition against scanned answer sheets.

    Returns StageResult with ``output["score_answers"]`` and ``output["stats"]``.
    """
    if not answer_urls or not answer_contexts:
        return StageResult(
            status="skipped",
            output={
                "score_answers": [],
                "stats": {"score_answer_count": 0, "score_scan_ms": 0.0, "score_page_count": 0},
            },
        )

    target_question_ids = [
        ctx.get("question_id")
        for ctx in answer_contexts
        if isinstance(ctx, dict) and isinstance(ctx.get("question_id"), str) and ctx.get("question_id")
    ]
    candidate_summaries = build_candidate_summaries_fn(answer_candidates, target_question_ids)
    score_started = perf_counter()
    log_progress(
        "answer_trace",
        "score_scan_start",
        page_count=len(answer_urls),
        question_count=len(target_question_ids),
        candidate_summary_count=len(candidate_summaries),
    )
    try:
        score_data = run_harness_stage(
            harness_stage_answer_score,
            prompt=answer_score_sheet_prompt_fn(answer_contexts, candidate_summaries),
            data_urls=answer_urls,
            profile=profile,
        )
    except Exception as exc:
        elapsed_ms = round((perf_counter() - score_started) * 1000, 1)
        warnings_out.append(f"answer_score failed: {exc}")
        log_progress(
            "answer_trace",
            "score_scan_failed",
            page_count=len(answer_urls),
            elapsed_ms=elapsed_ms,
        )
        return StageResult(
            status="failed",
            output={
                "score_answers": [],
                "stats": {"score_answer_count": 0, "score_scan_ms": elapsed_ms, "score_page_count": len(answer_urls)},
            },
            elapsed_ms=elapsed_ms,
        )

    raw_items = score_data.get("answers", [])
    score_answers: List[Dict[str, Any]] = []
    if isinstance(raw_items, list):
        context_map = build_answer_context_map_fn(answer_contexts)
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            normalized = normalize_answer_item_fn(
                item,
                context_map,
                source_stage="score",
                page_index=item.get("page_index") if isinstance(item.get("page_index"), int) else None,
            )
            if normalized is not None:
                score_answers.append(normalized)
    elapsed_ms = round((perf_counter() - score_started) * 1000, 1)
    log_progress(
        "answer_trace",
        "score_scan_done",
        page_count=len(answer_urls),
        answer_count=len(score_answers),
        elapsed_ms=elapsed_ms,
    )
    return StageResult(
        status="succeeded" if score_answers else "partial",
        output={
            "score_answers": score_answers,
            "stats": {"score_answer_count": len(score_answers), "score_scan_ms": elapsed_ms, "score_page_count": len(answer_urls)},
        },
        elapsed_ms=elapsed_ms,
    )
