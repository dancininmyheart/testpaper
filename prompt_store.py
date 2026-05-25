from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from demo.stage_contracts import response_contract


PROFILE_LITERACY_DIMENSIONS: List[Dict[str, str]] = [
    {"literacy_id": "number_sense", "name": "数感", "definition": "数量关系感知与估算能力。"},
    {"literacy_id": "measurement_sense", "name": "量感", "definition": "度量与单位选择、估计能力。"},
    {"literacy_id": "symbol_awareness", "name": "符号意识", "definition": "理解并使用数学符号表达关系。"},
    {"literacy_id": "operation_ability", "name": "运算能力", "definition": "按算理规则稳定完成运算。"},
    {"literacy_id": "geometric_intuition", "name": "几何直观", "definition": "通过图形理解性质与关系。"},
    {"literacy_id": "spatial_concept", "name": "空间观念", "definition": "理解位置、方向与空间变化。"},
    {"literacy_id": "reasoning_awareness", "name": "推理意识", "definition": "依据条件做逻辑推断并解释。"},
    {"literacy_id": "data_awareness", "name": "数据意识", "definition": "读取、整理并利用数据判断。"},
    {"literacy_id": "model_awareness", "name": "模型意识", "definition": "将问题抽象建模并求解。"},
    {"literacy_id": "application_awareness", "name": "应用意识", "definition": "在真实情境中应用数学。"},
    {"literacy_id": "innovation_awareness", "name": "创新意识", "definition": "提出猜想并尝试多种解法。"},
]


class PromptStore:
    @staticmethod
    def paper_prompt(
        knowledge_points: List[Dict[str, Any]],
        *,
        mode: str = "full",
        target_question_ids: Optional[List[str]] = None,
    ) -> str:
        target_ids = [qid for qid in (target_question_ids or []) if isinstance(qid, str) and qid.strip()]
        points = [
            {"id": item.get("id"), "name": item.get("name"), "type": item.get("type")}
            for item in knowledge_points
            if isinstance(item, dict)
        ]
        if mode == "index":
            return (
                "识别当前页包含的题号范围，并输出题号索引。只返回 JSON 对象。\n"
                f"{response_contract('question_index')}\n"
            )
        return (
            "识别题目文本、题型和小题结构。只返回 JSON 对象。\n"
            f"{response_contract('question_analysis')}\n"
            f"target_question_ids={json.dumps(target_ids, ensure_ascii=False)}\n"
            f"knowledge_points={json.dumps(points, ensure_ascii=False)}"
        )

    @staticmethod
    def route_prompt(question_contexts: List[Dict[str, Any]], page_index: int) -> str:
        payload = [
            {
                "question_id": item.get("question_id"),
                "question_type": item.get("question_type"),
                "sub_questions": item.get("sub_questions") if isinstance(item.get("sub_questions"), list) else [],
            }
            for item in question_contexts
            if isinstance(item, dict)
        ]
        return (
            "判断当前页可能对应哪些题号。只返回 JSON 对象。\n"
            f"{response_contract('answer_route')}\n"
            f"page_index={page_index}\n"
            f"question_contexts={json.dumps(payload, ensure_ascii=False)}"
        )

    @staticmethod
    def score_repair_prompt(
        question_contexts: List[Dict[str, Any]],
        candidate_summaries: List[Dict[str, Any]],
        target_question_ids: List[str],
    ) -> str:
        contexts = [item for item in question_contexts if isinstance(item, dict)]
        return (
            "请结合候选摘要补全目标题的作答结果。只返回 JSON 对象。\n"
            f"{response_contract('score_repair')}\n"
            f"target_question_ids={json.dumps(target_question_ids, ensure_ascii=False)}\n"
            f"structured_questions={json.dumps(contexts, ensure_ascii=False)}\n"
            f"candidate_summaries={json.dumps(candidate_summaries, ensure_ascii=False)}"
        )

    @staticmethod
    def knowledge_tag_prompt(
        question_chunk: List[Dict[str, Any]],
        candidate_points: List[Dict[str, Any]],
        knowledge_groups_by_question: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        return (
            "为题目匹配知识点，输出 items。只返回 JSON 对象。\n"
            f"{response_contract('knowledge_tagging')}\n"
            f"question_chunk={json.dumps(question_chunk, ensure_ascii=False)}\n"
            f"candidate_points={json.dumps(candidate_points, ensure_ascii=False)}\n"
            f"knowledge_groups_by_question={json.dumps(knowledge_groups_by_question or [], ensure_ascii=False)}"
        )

    @staticmethod
    def knowledge_group_prompt(
        question_chunk: List[Dict[str, Any]],
        candidate_groups: List[Dict[str, Any]],
    ) -> str:
        return (
            "为题目粗筛知识点组，输出 items。只返回 JSON 对象。\n"
            f"{response_contract('knowledge_grouping')}\n"
            f"question_chunk={json.dumps(question_chunk, ensure_ascii=False)}\n"
            f"candidate_groups={json.dumps(candidate_groups, ensure_ascii=False)}"
        )

    @staticmethod
    def answer_raw_section_prompt(
        question_contexts: List[Dict[str, Any]],
        page_index: int,
        section_name: str,
        segment_class_name: Optional[str] = None,
    ) -> str:
        return (
            "请转写该区域可见作答痕迹，保持原始顺序，不要改写。\n"
            "不要输出 question_id，不要做结构化归类，只输出原始可见文本。\n"
            f"page_index={page_index}\n"
            f"section_name={section_name}\n"
            f"segment_class_name={segment_class_name or 'unknown'}\n"
            f"question_context_count={len(question_contexts)}"
        )

    @staticmethod
    def answer_struct_from_raw_texts_prompt(
        question_contexts: List[Dict[str, Any]],
        raw_texts_by_page: List[Dict[str, Any]],
    ) -> str:
        return (
            "将原始作答痕迹结构化到题目粒度。只返回 JSON 对象。\n"
            f"{response_contract('answer_structuring')}\n"
            f"structured_questions={json.dumps(question_contexts, ensure_ascii=False)}\n"
            f"raw_answer_texts_by_page={json.dumps(raw_texts_by_page, ensure_ascii=False)}"
        )

    @staticmethod
    def answer_struct_and_align_prompt(
        question_contexts: List[Dict[str, Any]],
        raw_texts_by_page: List[Dict[str, Any]],
    ) -> str:
        return (
            "Read the raw student answer traces, structure them, and align each answer to the most likely "
            "question_id/sub_question_id in one pass. Return only one JSON object.\n"
            "Use the provided question ids exactly. If a trace is visible but ambiguous, set status=unclear "
            "and keep confidence below 0.6. If there is no visible answer, set status=unseen.\n"
            f"{response_contract('answer_struct_and_align')}\n"
            f"structured_questions={json.dumps(question_contexts, ensure_ascii=False)}\n"
            f"raw_answer_texts_by_page={json.dumps(raw_texts_by_page, ensure_ascii=False)}"
        )

    @staticmethod
    def answer_alignment_prompt(
        question_contexts: List[Dict[str, Any]],
        preliminary_answers: List[Dict[str, Any]],
        raw_texts_by_page: List[Dict[str, Any]],
    ) -> str:
        return (
            "请对 preliminary_answers 做题号/小题对齐修正。只返回 JSON 对象。\n"
            f"{response_contract('answer_alignment')}\n"
            f"structured_questions={json.dumps(question_contexts, ensure_ascii=False)}\n"
            f"preliminary_answers={json.dumps(preliminary_answers, ensure_ascii=False)}\n"
            f"raw_answer_texts_by_page={json.dumps(raw_texts_by_page, ensure_ascii=False)}"
        )

    @staticmethod
    def answer_score_sheet_prompt(
        question_contexts: List[Dict[str, Any]],
        candidate_summaries: List[Dict[str, Any]],
    ) -> str:
        return (
            "识别教师批改扣分信息，不要重做作答转写。只返回 JSON 对象。\n"
            f"{response_contract('answer_score')}\n"
            f"structured_questions={json.dumps(question_contexts, ensure_ascii=False)}\n"
            f"candidate_summaries={json.dumps(candidate_summaries, ensure_ascii=False)}"
        )

    @staticmethod
    def reference_answer_extract_prompt(question_contexts: List[Dict[str, Any]]) -> str:
        return (
            "根据上传标准答案文件提取各题参考答案。只返回 JSON 对象。\n"
            f"{response_contract('reference_answer_extract')}\n"
            f"structured_questions={json.dumps(question_contexts, ensure_ascii=False)}"
        )

    @staticmethod
    def reference_answer_generate_prompt(question_contexts: List[Dict[str, Any]]) -> str:
        return (
            "基于题目自动生成参考答案。只返回 JSON 对象。\n"
            "Use all attached original paper images/PDF pages as the primary source. "
            "Use structured_questions only as OCR/index hints; if a hint conflicts with the original paper image, follow the original paper image.\n"
            "Only answer the questions listed in structured_questions. For every returned item, copy question_id exactly from structured_questions; do not renumber or swap answers between questions.\n"
            "Return formatted reference answers only as JSON. For each item, include:\n"
            "- question_id, optional sub_question_id\n"
            "- analysis: 解题分析（解题思路、关键方法选择、易错点提示）\n"
            "- reference_steps: 具体解题步骤列表（逐步推导，每步简洁）\n"
            "- reference_final_answer: 最终答案\n"
            "- reference_answer_text: 完整解答文本（兼容字段，可复用 analysis 内容）\n"
            "- confidence: 置信度 0-1\n"
            "- reason: 判断依据说明\n"
            "Keep mathematical formulas readable, preferably in plain LaTeX-style text. Do not wrap the JSON in Markdown fences.\n"
            "Keep each generated answer concise: final answer plus no more than 4 essential steps.\n"
            f"{response_contract('reference_answer_generate')}\n"
            f"structured_questions={json.dumps(question_contexts, ensure_ascii=False)}"
        )

    @staticmethod
    def answer_key_correctness_prompt(items: List[Dict[str, Any]]) -> str:
        return (
            "逐题比对学生的作答与参考答案，给出对错判定。比对要点：\n"
            "1. 优先比对最终答案/结论是否一致，一致即判为正确，不拘泥于步骤差异；\n"
            "2. 选择题比对学生所选选项与参考答案选项是否一致；\n"
            "3. 数学表达式中等价形式（如分数/小数互化、因式展开/分解、单位换算）视为一致；\n"
            "4. 忽略书写格式差异（空格、换行、大小写）；\n"
            "5. 绝对不要尝试自己去重新演算或验证参考答案的正确性，也不要自己重新做题。必须无条件信任并以给出的参考答案（reference_final_answer / reference_answer_text）作为判定对错的唯一基准；\n"
            "6. 判定为错误时，reason 必须写明具体错因"
            "（如选项选错应选C、最终结果符号错误、关键步骤遗漏），"
            "不可只写答案不一致。\n"
            "判定规则：无论 reference_source 是 uploaded 还是 generated，均须以给出的参考答案为唯一标准进行正误判定。结合给出的参考答案与教师批改痕迹（如有）进行正误分析。\n"
            "只返回 JSON 对象。不要过度展开解释，不要输出 schema 之外的字段。reason 字段≤30字。\n"
            f"{response_contract('answer_key_correctness')}\n"
            f"items={json.dumps(items, ensure_ascii=False)}"
        )

    @staticmethod
    def blind_diagnosis_prompt(items: List[Dict[str, Any]]) -> str:
        return (
            "你是数学作答双盲诊断助手。请只依据题目和学生作答痕迹做步骤级诊断。\n"
            "禁止参考教师批改信号。只返回 JSON 对象。\n"
            f"{response_contract('blind_step_analysis')}\n"
            f"items={json.dumps(items, ensure_ascii=False)}"
        )

    @staticmethod
    def error_analysis_prompt(items: List[Dict[str, Any]]) -> str:
        return (
            "数学错因分析。结合题目、作答痕迹与失分信息，深入诊断错因。要求：\n"
            "1. 必须定位并指出具体是在哪一步（如第几步，或推导的哪一个公式）开始出错，详细描述该错误步骤的内容；\n"
            "2. 深度剖析错误的具体成因（如：概念混淆、计算失误、审题不清、公式记忆错误等），并写出详细的错误原因分析；\n"
            "3. 给出针对性的订正步骤与具体的修复建议。\n"
            "只返回 JSON 对象。在保证表述详尽、准确的前提下，输出限制为：wrong_step/step_reason/step_fix/suggestion 各≤60字，避免空泛描述。\n"
            f"{response_contract('error_analysis')}\n"
            f"items={json.dumps(items, ensure_ascii=False)}"
        )

    @staticmethod
    def profile_prompt(
        student_id: str,
        questions: List[Dict[str, Any]],
        answers: List[Dict[str, Any]],
        graph: Dict[str, Any],
        rule_based_literacy: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        literacy_schema = [
            {
                "literacy_id": item["literacy_id"],
                "name": item["name"],
                "value": 0.62,
                "level": "high|medium|low",
                "evidence": ["Q1"],
                "reason": "结合题目表现给出的判断",
                "suggestion": "一条针对该素养的提升建议",
            }
            for item in PROFILE_LITERACY_DIMENSIONS
        ]
        return (
            "你是学习诊断助手，请输出学生画像 JSON。只返回 JSON 对象。\n"
            f"{response_contract('student_profile')}\n"
            f"literacy_schema={json.dumps(literacy_schema, ensure_ascii=False)}\n"
            f"student_id={student_id}\n"
            f"questions={json.dumps(questions, ensure_ascii=False)}\n"
            f"answers={json.dumps(answers, ensure_ascii=False)}\n"
            f"graph={json.dumps(graph, ensure_ascii=False)}\n"
            f"rule_based_literacy={json.dumps(rule_based_literacy or [], ensure_ascii=False)}"
        )

    @staticmethod
    def new_point_prompt(skill_id: str, question: Dict[str, Any], existing_ids: List[str]) -> str:
        return (
            "请补全一个知识点定义与别名。只返回 JSON 对象。\n"
            f"{response_contract('new_knowledge_point')}\n"
            f"skill_id={skill_id}\n"
            f"question={json.dumps(question, ensure_ascii=False)}\n"
            f"existing_ids={json.dumps(existing_ids, ensure_ascii=False)}"
        )

    @staticmethod
    def knowledge_tagger_prompt(points: List[Dict[str, str]], max_points: Optional[int] = None) -> str:
        limited = points[: max_points or len(points)]
        return (
            "请从候选知识点中选择最相关项，输出 JSON。只返回 JSON 对象。\n"
            f"{response_contract('knowledge_tagger')}\n"
            f"candidates={json.dumps(limited, ensure_ascii=False)}"
        )

    @staticmethod
    def knowledge_tagger_new_point_prompt(points: List[Dict[str, str]], max_points: Optional[int] = None) -> str:
        limited = points[: max_points or len(points)]
        return (
            "若无匹配知识点，请提出新知识点建议。只返回 JSON 对象。\n"
            f"{response_contract('knowledge_tagger_new_point')}\n"
            f"candidates={json.dumps(limited, ensure_ascii=False)}"
        )

    @staticmethod
    def vlm_answer_parser_prompt(candidates: List[Dict[str, Any]]) -> str:
        return (
            "请按候选题号解析学生答案与得分。只返回 JSON 对象。\n"
            f"{response_contract('vlm_answer_parser')}\n"
            f"candidates={json.dumps(candidates, ensure_ascii=False)}"
        )
