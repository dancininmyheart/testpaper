# -*- coding: utf-8 -*-
from __future__ import annotations

import concurrent.futures as cf
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .agents.analyzer import KnowledgeAnalyzer
from .agents.scenario import ScenarioGenerator
from .agents.generator import QuestionGenerator
from .agents.assembler import ExamAssembler

log = logging.getLogger("exam_generator.pipeline")


class ExamGenerationPipeline:
    """Backward-compatible facade.

    保持平台已接入的契约:
        ExamGenerationPipeline(config, api_key, base_url, max_workers)
        .run(questions: list[dict], host_url: str = "") -> str
    """

    def __init__(
        self,
        *,
        config: dict[str, Any],
        api_key: str = "",
        base_url: str = "",
        max_workers: int = 4,
    ):
        self.config = self._merge_inline_credentials(config, api_key, base_url)
        self.max_workers = max(1, int(max_workers or 1))

        output_dir = self.config.get("paths", {}).get("output_dir", "output")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # checkpoints 放 output_dir 下,不污染 CWD
        self.checkpoint_dir = self.output_dir / "_checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # agents 直接吃 dict config
        self.analyzer = KnowledgeAnalyzer(config=self.config)
        self.scenario = ScenarioGenerator(config=self.config)
        self.generator = QuestionGenerator(config=self.config)
        self.assembler = ExamAssembler(config=self.config)

    # ---------- public ----------

    def run(self, *, questions: list[dict], host_url: str = "") -> str:
        if not questions:
            raise ValueError("ExamGenerationPipeline.run: no questions provided")

        log.info("[pipeline] start: %d questions, max_workers=%d",
                 len(questions), self.max_workers)
        print(f"\n>>> [pipeline] Starting generation for {len(questions)} questions (max_workers={self.max_workers})")

        cp0 = self._save_checkpoint({"questions": questions}, stage="step0_input")
        new_questions = self._run_per_question_loop(questions)

        if len(new_questions) < len(questions) * 0.8:
            log.error("[pipeline] Too many questions failed. Got %d/%d generated questions", len(new_questions), len(questions))
            raise RuntimeError(f"Too many question generations failed. Only {len(new_questions)}/{len(questions)} succeeded.")

        cp1 = self._save_checkpoint({"new_questions": new_questions}, stage="step3_generated")

        print("\n>>> Assembling final exam markdown...")
        markdown = self.assembler.run({"new_questions": new_questions})

        markdown = self._sanitize_latex_delimiters(markdown)

        md_path = self._write_markdown(markdown)
        
        print(f"\n>>> Rendering PDF to: {md_path.with_suffix('.pdf')}...")
        pdf_path = self._write_pdf(markdown, md_path)

        log.info("[pipeline] done: md=%s pdf=%s", md_path, pdf_path)
        print(f"\n[+] Processing complete. final markdown: {md_path}")
        return str(md_path)

    # ---------- internal ----------

    def _merge_inline_credentials(self, config: dict, api_key: str, base_url: str) -> dict:
        """允许平台直接传 api_key/base_url(覆盖 config.yaml)。

        优先级:run-time 入参 > config.yaml > env var(由 base.BaseAgent 解析)。
        """
        cfg = json.loads(json.dumps(config))  # deep copy
        cfg.setdefault("api", {})
        active = cfg["api"].get("active_provider", "ds")
        if api_key:
            cfg["api"][f"{active}_key"] = api_key
        if base_url:
            cfg["api"][f"{active}_base_url"] = base_url
        return cfg

    def _run_per_question_loop(self, questions: list[dict]) -> list[dict]:
        """对每道题串行执行 analyze → scenario → generate;题目之间并行。"""

        def _process_one(idx_q):
            idx, q = idx_q
            try:
                # deep copy to avoid modifying original questions
                q_copy = json.loads(json.dumps(q))
                print(f"[*] [q_id={q_copy.get('id')}] Starting pipeline steps...")
                
                # 1. Analyze
                qa = self.analyzer.process_single(q_copy)
                # 2. Scenario
                qs = self.scenario.process_single(qa)
                # 3. Generate
                nq = self.generator.process_single(qs)
                
                print(f"[+] [q_id={q_copy.get('id')}] Completed successfully.")
                return idx, nq
            except Exception as e:  # 单题失败不阻碍全局
                log.warning("[pipeline] question %s failed: %s", q.get("id"), e)
                print(f"[!] [q_id={q.get('id')}] Process failed: {e}. Skipping...")
                return idx, None

        results: list[tuple[int, dict | None]] = []
        if self.max_workers > 1:
            with cf.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
                for r in ex.map(_process_one, enumerate(questions)):
                    results.append(r)
        else:
            for r in map(_process_one, enumerate(questions)):
                results.append(r)

        results.sort(key=lambda x: x[0])
        return [nq for _, nq in results if nq]

    def _save_checkpoint(self, data, *, stage: str) -> Path:
        path = self.checkpoint_dir / f"{stage}_{self.timestamp}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("[pipeline] checkpoint: %s", path)
        return path

    def _write_markdown(self, markdown: str) -> Path:
        path = self.output_dir / f"generated_exam_{self.timestamp}.md"
        path.write_text(markdown, encoding="utf-8")
        return path

    def _sanitize_latex_delimiters(self, markdown: str) -> str:
        markdown = re.sub(r"\\+\(\s*", "$", markdown)
        markdown = re.sub(r"\s*\\+\)", "$", markdown)
        markdown = re.sub(r"\\+\[\s*", "$$", markdown)
        markdown = re.sub(r"\s*\\+\]", "$$", markdown)
        return markdown

    def _write_pdf(self, markdown: str, md_path: Path) -> Path | None:
        from .pdf_export import render_markdown_to_pdf
        pdf_path = md_path.with_suffix(".pdf")
        try:
            render_markdown_to_pdf(markdown, pdf_path)
            return pdf_path
        except Exception as e:
            log.warning("[pipeline] pdf export failed: %s", e)
            print(f"[!] PDF export failed: {e}")
            return None
