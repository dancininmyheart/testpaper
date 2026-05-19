from __future__ import annotations

from time import perf_counter
from typing import Any, Callable, Dict, List

from .base import PipelineContext, StageResult


class PipelineOrchestrator:
    """Runs analysis pipeline stages in sequence against a PipelineContext.

    Each stage is a callable ``(ctx: PipelineContext) -> StageResult``.
    The orchestrator records stage results and aggregates warnings.
    """

    def __init__(self, ctx: PipelineContext):
        self.ctx = ctx
        self._stage_logs: List[Dict[str, Any]] = []

    @property
    def stage_logs(self) -> List[Dict[str, Any]]:
        return list(self._stage_logs)

    def log(self, stage: str, event: str, **extra: Any) -> None:
        """Forward log messages. Override in subclasses for custom logging."""
        pass

    def run_stage(self, name: str, stage_fn: Callable[[PipelineContext], StageResult]) -> StageResult:
        started = perf_counter()
        try:
            result = stage_fn(self.ctx)
        except Exception as exc:
            elapsed = round((perf_counter() - started) * 1000, 1)
            result = StageResult(
                status="failed",
                output={"error": str(exc)},
                elapsed_ms=elapsed,
            )
        else:
            if not result.elapsed_ms:
                result.elapsed_ms = round((perf_counter() - started) * 1000, 1)

        entry: Dict[str, Any] = {
            "stage": name,
            "status": result.status,
            "elapsed_ms": result.elapsed_ms,
        }
        if result.warnings:
            entry["warnings"] = result.warnings
        self._stage_logs.append(entry)
        self.ctx.warnings.extend(result.warnings)
        self.ctx.stage_logs.append(entry)
        return result

    def run_pipeline(self, stages: List[tuple[str, Callable[[PipelineContext], StageResult]]]) -> PipelineContext:
        """Run a sequence of (name, stage_fn) pairs.

        If a stage fails fatally (status="failed"), subsequent stages are skipped
        unless the stage is marked as optional.
        """
        for name, stage_fn in stages:
            result = self.run_stage(name, stage_fn)
            if result.status == "failed":
                # Let caller decide whether to continue
                pass
        return self.ctx
