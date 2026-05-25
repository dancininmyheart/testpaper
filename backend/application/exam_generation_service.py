from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from backend.infrastructure.repositories import PaperRepository
from backend.infrastructure.storage import LocalFileStorage

logger = logging.getLogger("exam_generation.service")


_EXAM_GEN_DIR = Path(__file__).resolve().parent.parent.parent / "Test_to_Test_Paper_Generation"


def _ensure_in_syspath() -> None:
    path_str = str(_EXAM_GEN_DIR)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

    # Load .env files so config.yaml ${VAR} placeholders resolve.
    # Prefer the local .env under Test_to_Test_Paper_Generation,
    # fall back to project-root .env.
    from tools.mineru_vlm_markdown_extract import load_env_file

    local_env = _EXAM_GEN_DIR / ".env"
    root_env = _EXAM_GEN_DIR.parent / ".env"
    if local_env.exists():
        load_env_file(local_env)
    if root_env.exists():
        load_env_file(root_env)


def _adapt_platform_question(q: dict[str, Any], ref_answer: dict[str, Any] | None) -> dict[str, Any]:
    question_type = str(q.get("question_type", "")).strip()
    question_id = str(q.get("question_id", ""))
    content = str(q.get("content", ""))

    raw = q.get("raw", {})
    if not isinstance(raw, dict):
        raw = {}

    options: list[str] = []
    raw_options = raw.get("options")
    if isinstance(raw_options, dict):
        for key in sorted(str(k) for k in raw_options.keys()):
            options.append(f"{key}. {raw_options[key]}")
    elif isinstance(raw_options, list):
        options = [str(o) for o in raw_options]

    sub_questions = raw.get("sub_questions") or q.get("sub_questions") or []
    if isinstance(sub_questions, list):
        for sub in sub_questions:
            sub_text = (sub.get("sub_text") or sub.get("content") or "").strip()
            if sub_text and sub_text not in content:
                content += "\n" + sub_text

    answer = ""
    if ref_answer:
        answer = str(ref_answer.get("answer_text") or ref_answer.get("final_answer") or "")

    skill_tags = q.get("skill_tags", [])
    if not isinstance(skill_tags, list):
        skill_tags = []

    score = q.get("max_score")
    if not isinstance(score, (int, float)):
        score = 0

    return {
        "id": question_id,
        "type": question_type,
        "stem": content,
        "options": options,
        "answer": answer,
        "score": score,
        "knowledge_points": list(skill_tags),
    }


def adapt_project_questions(
    questions: list[dict[str, Any]],
    ref_answers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    answer_by_qid: dict[str, dict[str, Any]] = {}
    for a in ref_answers:
        qid = str(a.get("question_id") or "")
        if qid:
            answer_by_qid[qid] = a

    adapted: list[dict[str, Any]] = []
    for q in questions:
        qid = str(q.get("question_id") or "")
        adapted.append(_adapt_platform_question(q, answer_by_qid.get(qid)))
    return adapted


class ExamGenerationService:
    def __init__(
        self,
        *,
        paper_repo: PaperRepository,
        storage: LocalFileStorage,
    ):
        self.paper_repo = paper_repo
        self.storage = storage

    def build_generation_config(self, project_id: str) -> dict[str, Any]:
        _ensure_in_syspath()
        from exam_generator.config_loader import load_config

        config_path = _EXAM_GEN_DIR / "exam_generator" / "config.yaml"
        config = load_config(str(config_path))

        config["paths"]["output_dir"] = str(
            Path(self.storage.root) / "generated_exams" / project_id
        )
        return config

    def run_generation(self, *, project_id: str, progress_callback=None, host_url: str = "") -> str:
        _ensure_in_syspath()
        from exam_generator.pipeline import ExamGenerationPipeline

        questions_raw = self.paper_repo.get_questions(project_id)
        ref_answers = self.paper_repo.get_reference_answers(project_id)
        adapted = adapt_project_questions(questions_raw, ref_answers)

        logger.info("[exam_gen] project=%s question_count=%d ref_answer_count=%d",
                     project_id, len(adapted), len(ref_answers))
        print(f"[exam_gen] Starting generation: project={project_id}, {len(adapted)} questions")

        config = self.build_generation_config(project_id)

        provider = config["api"].get("active_provider", "ds")
        api_key = config["api"].get(f"{provider}_key", "")
        base_url = config["api"].get(f"{provider}_base_url", "")
        models = config.get("models", {})

        logger.info("[exam_gen] provider=%s base_url=%s models=%s", provider, base_url, models)
        print(f"[exam_gen] Provider: {provider} | Models: {models}")

        output_dir = Path(config["paths"]["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.info("[exam_gen] output_dir=%s", output_dir)

        max_workers = int(config.get("batch_size", {}).get("generation", 4))
        pipeline = ExamGenerationPipeline(
            config=config,
            api_key=api_key,
            base_url=base_url,
            max_workers=max_workers,
        )
        result_path = pipeline.run(questions=adapted, host_url=host_url)

        if not result_path or not os.path.exists(result_path):
            logger.error("[exam_gen] Pipeline returned no output for project=%s", project_id)
            return ""

        output_dir_rel = str(output_dir)
        os.makedirs(output_dir_rel, exist_ok=True)

        import shutil
        dest_md = os.path.join(output_dir_rel, "generated_exam.md")
        shutil.copy2(result_path, dest_md)
        logger.info("[exam_gen] Final output: %s", dest_md)
        print(f"[exam_gen] Generation complete: {dest_md}")

        pdf_src = os.path.splitext(result_path)[0] + ".pdf"
        dest_pdf = os.path.join(output_dir_rel, "generated_exam.pdf")
        if os.path.exists(pdf_src):
            shutil.copy2(pdf_src, dest_pdf)
            logger.info("[exam_gen] PDF output: %s", dest_pdf)
            print(f"[exam_gen] PDF copied: {dest_pdf}")
        else:
            logger.warning("[exam_gen] PDF not found at %s", pdf_src)

        return dest_md

    def get_generated_paper_path(self, project_id: str) -> str:
        output_dir = Path(self.storage.root) / "generated_exams" / project_id
        md_path = output_dir / "generated_exam.md"
        if md_path.is_file():
            return str(md_path)
        return ""
