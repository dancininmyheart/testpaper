from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from typing import Any, Callable, Dict, List, Optional

from demo.data_utils import _chunk_list

from .base import StageResult


def run_answer_key_correctness_stage(
    *,
    answer_contexts: List[Dict[str, Any]],
    structured_questions_full: List[Dict[str, Any]],
    reference_answers: List[Dict[str, Any]],
    answer_key_source: str,
    teacher_review_by_id: Dict[str, Dict[str, Any]],
    text_profile: Dict[str, Any] | None,
    question_chunk_size: int,
    answer_concurrency: int,
    harness_stage_correctness: Any,
    run_harness_stage: Callable,
    log_progress: Callable,
    correctness_prompt_fn: Callable,
    build_items_fn: Callable,
    build_context_map_fn: Callable,
    normalize_item_fn: Callable,
    warnings_out: List[str],
) -> StageResult:
    """Run answer-key correctness evaluation against reference answers.

    Returns StageResult with ``output["items"]``.
    """
    if not reference_answers:
        return StageResult(status="skipped", output={"items": []})

    raw_items = build_items_fn(
        structured_questions_full=structured_questions_full,
        reference_answers=reference_answers,
        reference_source=answer_key_source,
        teacher_review_by_id=teacher_review_by_id,
    )
    if not raw_items:
        return StageResult(status="skipped", output={"items": []})

    context_map = build_context_map_fn(answer_contexts)
    outputs: Dict[tuple[str, Optional[str]], Dict[str, Any]] = {}
    chunks = [chunk for chunk in _chunk_list(raw_items, question_chunk_size) if chunk]
    if not chunks:
        return StageResult(status="skipped", output={"items": []})

    max_workers = min(max(1, answer_concurrency), len(chunks))
    log_progress(
        "answer_key_correctness",
        "chunk_start",
        item_count=len(raw_items),
        chunk_count=len(chunks),
        max_workers=max_workers,
    )
    started = perf_counter()

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
                        harness_stage_correctness,
                        prompt=correctness_prompt_fn(chunk),
                        data_urls=[],
                        profile=text_profile,
                    ),
                )
            )
        for chunk_index, chunk_size, task_started, future in tasks:
            try:
                data = future.result()
            except Exception as exc:
                warnings_out.append(f"answer_key_correctness chunk={chunk_index} failed: {exc}")
                log_progress(
                    "answer_key_correctness",
                    "chunk_failed",
                    chunk=chunk_index,
                    item_count=chunk_size,
                    elapsed_ms=round((perf_counter() - task_started) * 1000, 1),
                )
                continue
            result_items = data.get("items", []) if isinstance(data, dict) else []
            if isinstance(result_items, list):
                for item in result_items:
                    parsed = normalize_item_fn(item, context_map)
                    if parsed is None:
                        continue
                    key = (
                        parsed["question_id"],
                        parsed["sub_question_id"] if isinstance(parsed.get("sub_question_id"), str) else None,
                    )
                    existing = outputs.get(key)
                    new_conf = parsed.get("confidence") if isinstance(parsed.get("confidence"), (int, float)) else -1.0
                    old_conf = existing.get("confidence") if isinstance(existing, dict) and isinstance(existing.get("confidence"), (int, float)) else -1.0
                    if existing is None or new_conf >= old_conf:
                        outputs[key] = parsed
            log_progress(
                "answer_key_correctness",
                "chunk_done",
                chunk=chunk_index,
                item_count=chunk_size,
                output_count=len(result_items) if isinstance(result_items, list) else 0,
                elapsed_ms=round((perf_counter() - task_started) * 1000, 1),
            )

    return StageResult(
        status="succeeded" if outputs else "partial",
        output={"items": list(outputs.values())},
        elapsed_ms=round((perf_counter() - started) * 1000, 1),
    )
