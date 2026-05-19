from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class StageResponseContract:
    stage_name: str
    example: str
    expected_list_key: Optional[str] = None


_CONTRACTS: Dict[str, StageResponseContract] = {
    "question_index": StageResponseContract(
        stage_name="question_index",
        expected_list_key="questions",
        example='{"questions": [{"question_id":"Q1","paper_page_index":0}]}',
    ),
    "question_analysis": StageResponseContract(
        stage_name="question_analysis",
        expected_list_key="questions",
        example=(
            '{"questions": [{"question_id":"Q1","question_type":"solution",'
            '"problem_text":"题干摘要","problem_text_full":"题干完整文本",'
            '"sub_questions":[{"sub_question_id":"Q1(1)","sub_text":"小题文本"}]}]}'
        ),
    ),
    "answer_route": StageResponseContract(
        stage_name="answer_route",
        expected_list_key="routes",
        example='{"routes": [{"question_id":"Q1","confidence":0.8}]}',
    ),
    "score_repair": StageResponseContract(
        stage_name="score_repair",
        expected_list_key="answers",
        example='{"answers": [...]}',
    ),
    "knowledge_grouping": StageResponseContract(
        stage_name="knowledge_grouping",
        expected_list_key="items",
        example='{"items": [{"question_id":"Q1","knowledge_groups":["algebra.formula"]}]}',
    ),
    "knowledge_tagging": StageResponseContract(
        stage_name="knowledge_tagging",
        expected_list_key="items",
        example='{"items": [{"question_id":"Q1","knowledge_points":["kp.id"]}]}',
    ),
    "answer_structuring": StageResponseContract(
        stage_name="answer_structuring",
        expected_list_key="answers",
        example=(
            '{"answers": [{"question_id":"Q1","sub_question_id":"Q1(1)",'
            '"status":"answered|unseen|unclear","student_answer_text":"...",'
            '"steps":["step 1","step 2"],"confidence":0.8}]}'
        ),
    ),
    "answer_struct_and_align": StageResponseContract(
        stage_name="answer_struct_and_align",
        expected_list_key="answers",
        example=(
            '{"answers": [{"question_id":"Q1","sub_question_id":"Q1(1)",'
            '"status":"answered|unseen|unclear","student_answer_text":"...",'
            '"steps":["step 1","step 2"],"confidence":0.8}]}'
        ),
    ),
    "answer_alignment": StageResponseContract(
        stage_name="answer_alignment",
        expected_list_key="answers",
        example='{"answers": [{"question_id":"Q1","sub_question_id":"Q1(1)","status":"answered"}]}',
    ),
    "answer_score": StageResponseContract(
        stage_name="answer_score",
        expected_list_key="answers",
        example='{"answers": [{"question_id":"Q1","status":"answered","deducted_score":1,"lost_score":1,"confidence":0.8}]}',
    ),
    "reference_answer_extract": StageResponseContract(
        stage_name="reference_answer_extract",
        expected_list_key="reference_answers",
        example=(
            '{"reference_answers": [{"question_id":"Q1","sub_question_id":"Q1(1)",'
            '"reference_answer_text":"...","reference_final_answer":"...",'
            '"reference_steps":["..."],"confidence":0.9,"reason":"..."}]}'
        ),
    ),
    "reference_answer_generate": StageResponseContract(
        stage_name="reference_answer_generate",
        expected_list_key="reference_answers",
        example=(
            '{"reference_answers": [{"question_id":"Q1","sub_question_id":"Q1(1)",'
            '"analysis":"...","reference_steps":["1. ...","2. ..."],'
            '"reference_final_answer":"...","reference_answer_text":"...",'
            '"confidence":0.95,"reason":"..."}]}'
        ),
    ),
    "answer_key_correctness": StageResponseContract(
        stage_name="answer_key_correctness",
        expected_list_key="items",
        example=(
            '{"items": [{"question_id":"Q1","sub_question_id":"Q1(1)",'
            '"by_answer_key":true,"confidence":0.9,"reason":"..."}]}'
        ),
    ),
    "blind_step_analysis": StageResponseContract(
        stage_name="blind_step_analysis",
        expected_list_key="items",
        example=(
            '{"items": [{"question_id":"Q1","blind_diagnosis":{'
            '"standard_steps":[{"step_index":1,"content":"...","skill_tags":["skill.id"]}],'
            '"student_steps":[{"step_index":1,"content":"...","evidence":"..."}],'
            '"divergence_point":"...","error_type":"concept|calculation|reading|strategy|unknown",'
            '"reason":"...","evidence_span":"...","repair_suggestion":"...",'
            '"suggestion":"...","is_correct_estimate":null,"confidence":0.8}}]}'
        ),
    ),
    "error_analysis": StageResponseContract(
        stage_name="error_analysis",
        expected_list_key="items",
        example=(
            '{"items": [{"question_id":"Q1","error_analysis":{'
            '"error_type":"concept|calculation|reading|strategy|unknown",'
            '"wrong_step":"...","step_reason":"...","step_evidence":"...",'
            '"step_fix":"...","reason":"...","evidence":"...","suggestion":"..."}}]}'
        ),
    ),
    "student_profile": StageResponseContract(
        stage_name="student_profile",
        example=(
            '{"student_id":"41200105","mastery":[{"skill_id":"eq.method.linear_transpose",'
            '"value":0.62,"reason":"..."}],"error_profile":{"concept":0,"calculation":0,'
            '"reading":0,"strategy":0,"unknown":0},"literacy":[{"literacy_id":"number_sense",'
            '"name":"数感","value":0.62,"level":"high|medium|low","evidence":["Q1"],'
            '"reason":"...","suggestion":"..."}],"weaknesses":[{"skill_id":"eq.method.linear_transpose",'
            '"evidence":["Q1"],"priority":"high|medium|low","symptom":"...",'
            '"cause":"...","improvement_steps":["...","..."],"practice_plan":"...",'
            '"success_criteria":"...","suggestion":"..."}],"summary":"..."}'
        ),
    ),
    "new_knowledge_point": StageResponseContract(
        stage_name="new_knowledge_point",
        example='{"new_point":{"id":"new.skill.id","name":"知识点名称","short_name":"短名","type":"method","aliases":["别名1"],"description":"说明"}}',
    ),
    "knowledge_tagger": StageResponseContract(
        stage_name="knowledge_tagger",
        expected_list_key="knowledge_points",
        example='{"knowledge_points": [{"id":"kp.id","name":"知识点"}]}',
    ),
    "knowledge_tagger_new_point": StageResponseContract(
        stage_name="knowledge_tagger_new_point",
        example='{"new_point": {"id":"new.skill.id","name":"新知识点","type":"method"}}',
    ),
    "vlm_answer_parser": StageResponseContract(
        stage_name="vlm_answer_parser",
        expected_list_key="answers",
        example='{"answers": [{"question_id":"Q1","answer_text":"...","score":0,"max_score":5,"is_correct":false}]}',
    ),
}


def stage_contract(stage_name: str) -> StageResponseContract:
    try:
        return _CONTRACTS[stage_name]
    except KeyError as exc:
        raise KeyError(f"unknown stage response contract: {stage_name}") from exc


def expected_list_key(stage_name: str) -> Optional[str]:
    return stage_contract(stage_name).expected_list_key


def response_contract(stage_name: str) -> str:
    return stage_contract(stage_name).example
