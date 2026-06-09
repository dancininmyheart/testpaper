from .base import BaseAgent
from typing import Dict, Any, List
import json

class ScenarioGenerator(BaseAgent):
    def __init__(self, *, config: dict | None = None, config_path: str | None = None):
        super().__init__(config=config, config_path=config_path, agent_name="scenario")
        self.variant = self.config.get("prompts", {}).get("scenario", "v2")

    def _load_system_prompt(self) -> str:
        variant = self.config.get("prompts", {}).get("scenario", "v2")
        if variant == "v1":
            from .prompts.v1 import SCENARIO_SYSTEM
            return SCENARIO_SYSTEM
            
        from .prompts.v2 import get_scenario_system_prompt
        threshold = self.config.get("scenario_threshold", 6)
        return get_scenario_system_prompt(threshold)

    def process_single(self, question: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single question and merge only the new scenario data."""
        user_msg = f"请为该题目设计新情境，并以 JSON 格式输出：\n\n{json.dumps(question, ensure_ascii=False)}"
        response = self._call_llm(user_msg)
        new_data = self._extract_json(response)

        if not isinstance(new_data, dict):
            return question

        if self.variant == "v1":
            if "new_scenario" in new_data:
                question["new_scenario"] = new_data["new_scenario"]
            else:
                question["new_scenario"] = new_data
            return question

        # v2: preserve full decision context for generator
        if "decision" in new_data:
            question["scenario_decision"] = new_data["decision"]
        if "new_scenario" in new_data and new_data["new_scenario"]:
            question["new_scenario"] = new_data["new_scenario"]
        if "abstract_mutation" in new_data and new_data["abstract_mutation"]:
            question["abstract_mutation"] = new_data["abstract_mutation"]

        return question

    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process questions individually."""
        questions = input_data.get("questions", [])
        processed_questions = []
        for q in questions:
            processed_q = self.process_single(q)
            processed_questions.append(processed_q)
        return {"questions": processed_questions}
