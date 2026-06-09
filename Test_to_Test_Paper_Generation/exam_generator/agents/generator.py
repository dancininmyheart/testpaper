from .base import BaseAgent
from typing import Dict, Any, List
import json
import logging
import re
from ..knowledge_manager import KnowledgeManager

log = logging.getLogger("exam_generator.generator")

GEOMETRY_TOPIC_PREFIXES = ("G", "图形", "几何", "三角形", "四边形", "圆", "相似", "全等", "勾股", "坐标")

def _needs_figure(question: Dict[str, Any]) -> bool:
    topic_id = str(question.get("topic_id", ""))
    stem = str(question.get("stem", ""))
    q_type = str(question.get("type", ""))
    if any(topic_id.startswith(p) for p in GEOMETRY_TOPIC_PREFIXES):
        return True
    geo_keywords = ["如图", "下图", "图中", "图形", "求证", "证明", "示意图", "△", "∠", "⊙", "≅", "∥", "⟂"]
    if any(kw in stem for kw in geo_keywords):
        return True
    if q_type in ("解答题", "证明题"):
        return True
    return False


class QuestionGenerator(BaseAgent):
    def __init__(self, *, config: dict | None = None, config_path: str | None = None):
        self.km = KnowledgeManager()
        super().__init__(config=config, config_path=config_path, agent_name="generator")
        self.variant = self.config.get("prompts", {}).get("generator", "v2")

    def _load_system_prompt(self) -> str:
        variant = self.config.get("prompts", {}).get("generator", "v2")
        if variant == "v1":
            from .prompts.v1 import GENERATOR_SYSTEM
            return GENERATOR_SYSTEM

        from .prompts.v2 import get_generator_system_prompt
        standard = self.km.get_standard_info()
        return get_generator_system_prompt(standard.get("standard", "初中数学课程标准"))

    def process_single(self, question: Dict[str, Any]) -> Dict[str, Any]:
        topic_id = question.get("topic_id")
        topic_details = self.km.get_topic_details(topic_id) if topic_id else None

        knowledge_context = ""
        if topic_details:
            knowledge_context = f"\n\n【本题归属知识点详情】\n- 知识点：{topic_id} {topic_details['name']}\n- 允许考点范围：\n" + \
                               "\n".join([f"  * {kp}" for kp in topic_details["key_points"]])

        user_msg = f"请基于以下原题、分析报告和知识点约束生成新题，并以 JSON 格式输出：{knowledge_context}\n\n数据详情：\n{json.dumps(question, ensure_ascii=False)}"

        response = self._call_llm(user_msg)
        result = self._extract_json(response)

        if isinstance(result, list):
            result = result[0] if result else None
        elif isinstance(result, dict) and "new_questions" in result:
            result = result["new_questions"][0] if result["new_questions"] else None

        if isinstance(result, dict):
            result = self._post_process_svg(result, question)

        return result

    def _post_process_svg(self, result: Dict[str, Any], original: Dict[str, Any]) -> Dict[str, Any]:
        svg_code = result.get("svg_code")
        if svg_code and isinstance(svg_code, str) and svg_code.strip():
            svg = svg_code.strip()
            svg = re.sub(r"\s+", " ", svg)
            svg = re.sub(r">\s*<", "><", svg)
            result["svg_code"] = svg
        elif _needs_figure(original) or _needs_figure(result):
            log.warning("[generator] question %s looks like it needs a figure but svg_code is missing", result.get("id", "?"))

        return result

    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        questions = input_data.get("questions", [])
        new_questions = []
        for q in questions:
            new_q = self.process_single(q)
            if new_q:
                new_questions.append(new_q)
        return {"new_questions": new_questions}
