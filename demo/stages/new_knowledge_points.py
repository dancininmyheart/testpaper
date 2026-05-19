from __future__ import annotations

from time import perf_counter
from typing import Any, Callable, Dict, List

from llm_knowledge_tagger import _normalize_new_point
from prompt_store import PromptStore

from .base import StageResult


def _new_point_prompt(skill_id: str, question: Dict[str, Any], existing_ids: List[str]) -> str:
    return PromptStore.new_point_prompt(skill_id, question, existing_ids)


def run_new_knowledge_points_stage(
    questions: List[Dict[str, Any]],
    *,
    known_map: Dict[str, Dict[str, Any]],
    all_nodes: List[Dict[str, Any]],
    profile: Dict[str, Any] | None,
    mock_mode: bool,
    call_json_with_profile: Callable,
    log_progress: Callable,
) -> StageResult:
    """Discover new knowledge points from question skill tags that are not yet in the graph.

    Returns a StageResult whose ``output["new_nodes"]`` holds the added nodes.
    """
    started = perf_counter()
    warnings: List[str] = []
    existing_ids = set(known_map.keys())
    existing_name_to_id: Dict[str, str] = {
        n.get("name"): n.get("id")
        for n in all_nodes
        if isinstance(n, dict) and isinstance(n.get("name"), str) and isinstance(n.get("id"), str)
    }

    unknown_pairs: List[tuple[str, Dict[str, Any]]] = []
    seen_unknown: set[str] = set()
    for q in questions:
        if not isinstance(q, dict):
            continue
        tags = q.get("skill_tags")
        if not isinstance(tags, list):
            continue
        for tag in tags:
            if isinstance(tag, str) and tag not in existing_ids and tag not in seen_unknown:
                seen_unknown.add(tag)
                unknown_pairs.append((tag, q))

    added: List[Dict[str, Any]] = []
    log_progress(
        "new_knowledge_points",
        "scan_done",
        unknown_count=len(unknown_pairs),
        existing_count=len(existing_ids),
    )
    for missing_id, q in unknown_pairs:
        candidate: Dict[str, Any] = {
            "id": missing_id,
            "name": missing_id,
            "type": "concept",
            "prereq": [],
        }
        point_started = perf_counter()
        if not mock_mode and profile is not None:
            llm_data = call_json_with_profile(
                profile,
                prompt=_new_point_prompt(missing_id, q, sorted(existing_ids)),
                data_urls=[],
            )
            if isinstance(llm_data.get("new_point"), dict):
                candidate = llm_data["new_point"]
            elif isinstance(llm_data, dict):
                candidate = llm_data

        normalized = _normalize_new_point(candidate, existing_ids, existing_name_to_id)
        if not normalized:
            log_progress(
                "new_knowledge_points",
                "normalize_skipped",
                missing_id=missing_id,
                elapsed_ms=round((perf_counter() - point_started) * 1000, 1),
            )
            continue
        if isinstance(normalized.get("reuse_id"), str):
            log_progress(
                "new_knowledge_points",
                "reuse_existing",
                missing_id=missing_id,
                reuse_id=normalized.get("reuse_id"),
                elapsed_ms=round((perf_counter() - point_started) * 1000, 1),
            )
            continue
        node_id = normalized.get("id")
        if not isinstance(node_id, str):
            continue
        if node_id in existing_ids:
            continue
        short_name = normalized.get("short_name")
        if not isinstance(short_name, str) or not short_name.strip():
            node_name = normalized.get("name")
            normalized["short_name"] = node_name if isinstance(node_name, str) and node_name.strip() else node_id
        all_nodes.append(normalized)
        existing_ids.add(node_id)
        node_name = normalized.get("name")
        if isinstance(node_name, str) and node_name:
            existing_name_to_id[node_name] = node_id
        added.append(normalized)
        log_progress(
            "new_knowledge_points",
            "added",
            missing_id=missing_id,
            node_id=node_id,
            elapsed_ms=round((perf_counter() - point_started) * 1000, 1),
        )

    return StageResult(
        status="succeeded" if added else "partial",
        output={"new_nodes": added},
        warnings=warnings,
        elapsed_ms=round((perf_counter() - started) * 1000, 1),
    )


def create_new_knowledge_points_stage(service: Any) -> Callable[[Any], StageResult]:
    """Create a PipelineContext-based stage wired to a DemoService instance."""

    def stage_fn(ctx: Any) -> StageResult:
        return run_new_knowledge_points_stage(
            questions=ctx.questions,
            known_map=service._known_map(),
            all_nodes=service.nodes,
            profile=service.profile,
            mock_mode=ctx.mock_mode,
            call_json_with_profile=service._call_json_with_profile,
            log_progress=service._log_progress,
        )

    return stage_fn
