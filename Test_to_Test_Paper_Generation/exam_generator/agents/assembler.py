from .base import BaseAgent
from typing import Dict, Any
import json
import re

class ExamAssembler(BaseAgent):
    def __init__(self, *, config: dict | None = None, config_path: str | None = None):
        super().__init__(config=config, config_path=config_path, agent_name="assembler")
        self.variant = self.config.get("prompts", {}).get("assembler", "v2")

    def _load_system_prompt(self) -> str:
        variant = self.config.get("prompts", {}).get("assembler", "v2")
        if variant == "v1":
            from .prompts.v1 import ASSEMBLER_SYSTEM
            return ASSEMBLER_SYSTEM

        from .prompts.v2 import ASSEMBLER_SYSTEM
        return ASSEMBLER_SYSTEM

    def _format_header(self, title: str, total_score: float, total_count: int) -> str:
        prompt = f"[TASK: HEADER]\n标题：{title}\n总题量：{total_count}\n满分：{total_score}\n建议考试时间：{total_count * 3} 分钟"
        return self._call_llm(prompt, response_format="text")

    def _format_question_item(self, question: Dict[str, Any], index: int) -> str:
        svg_code = question.get("svg_code")
        svg_code = svg_code if isinstance(svg_code, str) and svg_code.strip() else None

        q_for_llm = {k: v for k, v in question.items() if k != "svg_code"}
        if svg_code:
            q_for_llm["_has_figure"] = True

        prompt = f"[TASK: QUESTION]\n题号：{index}\n数据：{json.dumps(q_for_llm, ensure_ascii=False)}"
        md = self._call_llm(prompt, response_format="text")

        if svg_code:
            svg = self._normalize_svg(svg_code)
            md += f"\n\n{svg}\n"

        return md

    def _format_answer_item(self, question: Dict[str, Any], index: int) -> str:
        svg_code = question.get("svg_code")
        svg_code = svg_code if isinstance(svg_code, str) and svg_code.strip() else None

        q_for_llm = {k: v for k, v in question.items() if k != "svg_code"}
        if svg_code:
            q_for_llm["_has_figure"] = True

        prompt = f"[TASK: ANSWER]\n题号：{index}\n数据：{json.dumps(q_for_llm, ensure_ascii=False)}"
        md = self._call_llm(prompt, response_format="text")

        if svg_code:
            svg = self._normalize_svg(svg_code)
            md += f"\n\n{svg}\n"

        return md

    @staticmethod
    def _normalize_svg(svg: str) -> str:
        svg = svg.strip()
        svg = re.sub(r"\s+", " ", svg)
        svg = re.sub(r">\s*<", "><", svg)
        return svg

    def run(self, input_data: Dict[str, Any]) -> str:
        new_questions = input_data.get("new_questions", [])
        if not new_questions:
            return "# 错误：未生成任何题目"

        if self.variant == "v1":
            print("[*] Assembling: Generating Paper using V1 Prompt...")
            user_msg = f"请根据提供的新题目列表，将其组装成一份规范的模拟试卷和参考答案解析：\n\n{json.dumps(input_data, ensure_ascii=False)}"
            return self._call_llm(user_msg, response_format="text")

        # V2 modular assembling logic
        # 1. 本地分组 (维持输入原序)
        categories = {}
        for q in new_questions:
            q_type = q.get("type", "其他题型")
            if q_type not in categories:
                categories[q_type] = []
            categories[q_type].append(q)

        # 2. 计算总分
        total_score = sum([int(q.get("score", 0)) for q in new_questions])
        
        # 3. 生成卷头
        print("[*] Assembling: Generating Paper Header (V2)...")
        final_md = self._format_header("全仿真智能模拟试卷", total_score, len(new_questions)) + "\n\n"

        # 4. 逐个生成题目正文
        print("[*] Assembling: Formatting questions (V2)...")
        idx_map = {} # 用于记录原题在总题号中的位置，方便后续匹配答案
        global_idx = 1
        
        category_names = ["单选题", "多选题", "判断题", "填空题", "解答题", "简答题", "其他题型"]
        # 先按常见顺序排序分类名
        sorted_types = sorted(categories.keys(), key=lambda t: category_names.index(t) if t in category_names else 99)

        for q_type in sorted_types:
            qs = categories[q_type]
            final_md += f"## {q_type}（共 {len(qs)} 题）\n\n"
            for q in qs:
                print(f"    - Formatting Question {global_idx}/{len(new_questions)}...")
                final_md += self._format_question_item(q, global_idx) + "\n\n"
                idx_map[q.get("id")] = global_idx
                global_idx += 1

        # 5. 逐个生成解析
        print("[*] Assembling: Formatting answers (V2)...")
        final_md += "---\n## 参考答案与解析\n\n"
        
        for q_type in sorted_types:
            for q in categories[q_type]:
                idx = idx_map.get(q.get("id"))
                print(f"    - Formatting Answer {idx}/{len(new_questions)}...")
                final_md += self._format_answer_item(q, idx) + "\n\n"

        return final_md
