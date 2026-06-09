import json
from .base import BaseAgent
from typing import List, Dict, Any
from ..knowledge_manager import KnowledgeManager

class KnowledgeAnalyzer(BaseAgent):
    def __init__(self, *, config: dict | None = None, config_path: str | None = None):
        self.km = KnowledgeManager()
        super().__init__(config=config, config_path=config_path, agent_name="analyzer")
        # Phase A uses the pdf_parser model configuration by default.
        self.phase_a_agent = "pdf_parser"
        self.variant = self.config.get("prompts", {}).get("analyzer", "v2")

    def _load_system_prompt(self) -> str:
        variant = self.config.get("prompts", {}).get("analyzer", "v2")
        if variant == "v1":
            from .prompts.v1 import ANALYZER_SYSTEM
            return ANALYZER_SYSTEM
        return "你是一位经验丰富的教研专家。"

    def _get_phase_a_prompt(self) -> str:
        from .prompts.v2 import get_analyzer_phase_a_prompt
        summary = self.km.get_topics_summary()
        summary_text = "\n".join([f"- {t['id']}: {t['name']}" for t in summary])
        return get_analyzer_phase_a_prompt(summary_text)

    def _get_phase_b_prompt(self, topic_id: str) -> str:
        from .prompts.v2 import get_analyzer_phase_b_prompt
        details = self.km.get_topic_details(topic_id)
        
        if not details:
            key_points_text = "无详细考点信息"
            details_name = ""
        else:
            key_points_text = "\n".join([f"- {kp}" for kp in details["key_points"]])
            details_name = details["name"]

        competencies = self.km.get_core_competencies()
        comp_text = "\n".join([f"- {c}" for c in competencies])

        ideas = self.km.get_math_ideas()
        ideas_text = "\n".join([f"- {i}" for i in ideas])
        standard = self.km.get_standard_info()
        
        return get_analyzer_phase_b_prompt(
            topic_id=topic_id,
            details_name=details_name,
            key_points_text=key_points_text,
            comp_text=comp_text,
            ideas_text=ideas_text,
            standard_title=standard.get('title', '初中数学知识体系'),
            standard_desc=standard.get('standard', '')
        )

    def process_single(self, question: Dict[str, Any]) -> Dict[str, Any]:
        """Two-step analysis process or legacy single-stage analysis."""
        if self.variant == "v1":
            return self._process_single_v1(question)
        return self._process_single_v2(question)

    def _process_single_v1(self, question: Dict[str, Any]) -> Dict[str, Any]:
        print(f"\n[*] Analyzing Question ID (V1 Prompt): {question.get('id')}...")
        user_msg = f"请为此题进行深度解析并标注知识点和难度，以 JSON 格式输出：\n\n{json.dumps(question, ensure_ascii=False)}"
        response = self._call_llm(user_msg, system_prompt=self.system_prompt)
        result = self._extract_json(response)
        
        # Merge results
        if isinstance(result, list) and len(result) > 0:
            result = result[0]
            
        if isinstance(result, dict):
            question.update(result)
            
        return question

    def _process_single_v2(self, question: Dict[str, Any]) -> Dict[str, Any]:
        """Two-step analysis process."""
        print(f"\n[*] Deep Analyzing Question ID (V2 Prompt): {question.get('id')}...")
        
        # Step A: Identify Topic ID (using mini model)
        user_msg_a = f"请为此题选择最匹配的知识点 ID，并以 JSON 格式输出：\n\n{json.dumps(question, ensure_ascii=False)}"
        response_a = self._call_llm(
            user_msg_a,
            agent_name=self.phase_a_agent,
            system_prompt=self._get_phase_a_prompt()
        )
        result_a = self._extract_json(response_a)
        topic_id = result_a.get("topic_id")
        
        if not topic_id:
            print(f"    [!] Warning: Phase A failed to identify topic_id. Fallback to general analysis.")
            return question

        print(f"    [+] Topic Identified: {topic_id}")

        # Step B: Detailed Analysis (using main analyzer model)
        user_msg_b = f"请基于知识点 {topic_id} 对此题进行深度解析，并以 JSON 格式输出：\n\n{json.dumps(question, ensure_ascii=False)}"
        response_b = self._call_llm(user_msg_b, system_prompt=self._get_phase_b_prompt(topic_id))
        result_b = self._extract_json(response_b)
        
        # Merge results
        if isinstance(result_b, dict):
            result_b["topic_id"] = topic_id
            question.update(result_b)
            
        return question

    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        questions = input_data.get("questions", [])
        processed_questions = []
        for q in questions:
            processed_q = self.process_single(q)
            processed_questions.append(processed_q)
        return {"questions": processed_questions}
