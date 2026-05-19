from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional

from demo.data_utils import (
    _mapping_pattern_matches,
    _normalize_question_type,
    _now_iso,
    _question_literacy_signal,
)
from demo.prompts import _attach_question_metadata, _question_anchor_text
from prompt_store import PROFILE_LITERACY_DIMENSIONS


def _normalize_profile_payload(student_id: str, profile_data: Dict[str, Any]) -> Dict[str, Any]:
    profile = dict(profile_data) if isinstance(profile_data, dict) else {}
    if not isinstance(profile.get("student_id"), str) or not profile.get("student_id"):
        profile["student_id"] = student_id

    literacy_raw = profile.get("literacy")
    literacy_items = literacy_raw if isinstance(literacy_raw, list) else []
    literacy_by_id: Dict[str, Dict[str, Any]] = {}
    for raw in literacy_items:
        if not isinstance(raw, dict):
            continue
        literacy_id = raw.get("literacy_id") if isinstance(raw.get("literacy_id"), str) else ""
        if not literacy_id:
            continue
        literacy_by_id[literacy_id] = raw

    normalized_literacy: List[Dict[str, Any]] = []
    for item in PROFILE_LITERACY_DIMENSIONS:
        literacy_id = item["literacy_id"]
        raw = literacy_by_id.get(literacy_id, {})
        value = raw.get("value")
        try:
            value_float = max(0.0, min(1.0, float(value)))
        except Exception:
            value_float = 0.5
        level = raw.get("level") if isinstance(raw.get("level"), str) else ""
        if level not in {"high", "medium", "low"}:
            if value_float >= 0.75:
                level = "high"
            elif value_float >= 0.45:
                level = "medium"
            else:
                level = "low"
        evidence = raw.get("evidence") if isinstance(raw.get("evidence"), list) else []
        evidence = [x for x in evidence if isinstance(x, str) and x.strip()]
        reason = raw.get("reason") if isinstance(raw.get("reason"), str) else ""
        suggestion = raw.get("suggestion") if isinstance(raw.get("suggestion"), str) else ""
        confidence = raw.get("confidence")
        try:
            confidence_value = max(0.0, min(1.0, float(confidence)))
        except Exception:
            confidence_value = 0.5
        source_breakdown = raw.get("source_breakdown") if isinstance(raw.get("source_breakdown"), dict) else {}
        normalized_breakdown = {
            "skill_tag": int(source_breakdown.get("skill_tag", 0) or 0),
            "question_type": int(source_breakdown.get("question_type", 0) or 0),
            "error_type": int(source_breakdown.get("error_type", 0) or 0),
            "wrong_step": int(source_breakdown.get("wrong_step", 0) or 0),
        }
        if not reason:
            reason = f"当前{item['name']}相关证据有限，先按整体作答稳定性给出基线判断"
        if not suggestion:
            suggestion = f"围绕{item['name']}做针对性题型训练，并在错题复盘时显式总结方法"
        normalized_literacy.append(
            {
                "literacy_id": literacy_id,
                "name": item["name"],
                "definition": item["definition"],
                "value": round(value_float, 2),
                "level": level,
                "evidence": evidence,
                "reason": reason,
                "suggestion": suggestion,
                "confidence": round(confidence_value, 2),
                "source_breakdown": normalized_breakdown,
            }
        )
    profile["literacy"] = normalized_literacy

    weaknesses_raw = profile.get("weaknesses")
    weaknesses_list = weaknesses_raw if isinstance(weaknesses_raw, list) else []
    normalized_weaknesses: List[Dict[str, Any]] = []
    for raw in weaknesses_list:
        if not isinstance(raw, dict):
            continue
        skill_id = raw.get("skill_id") if isinstance(raw.get("skill_id"), str) else ""
        if not skill_id:
            continue
        evidence = raw.get("evidence") if isinstance(raw.get("evidence"), list) else []
        evidence = [x for x in evidence if isinstance(x, str)]
        priority = raw.get("priority") if isinstance(raw.get("priority"), str) else "medium"
        if priority not in {"high", "medium", "low"}:
            priority = "medium"
        symptom = raw.get("symptom") if isinstance(raw.get("symptom"), str) else ""
        cause = raw.get("cause") if isinstance(raw.get("cause"), str) else ""
        steps = raw.get("improvement_steps") if isinstance(raw.get("improvement_steps"), list) else []
        steps = [x for x in steps if isinstance(x, str) and x.strip()]
        practice_plan = raw.get("practice_plan") if isinstance(raw.get("practice_plan"), str) else ""
        success_criteria = raw.get("success_criteria") if isinstance(raw.get("success_criteria"), str) else ""
        suggestion = raw.get("suggestion") if isinstance(raw.get("suggestion"), str) else ""
        if not symptom:
            symptom = "low score or unstable performance on related questions"
        if not cause:
            cause = "weak fundamentals and unstable key-step execution"
        if not steps:
            steps = [
                "review incorrect answers and locate the loss points",
                "practice 2-3 basic questions from the same skill",
                "practice 1-2 variants and review again",
            ]
        if not practice_plan:
            practice_plan = "3 days, 15-20 minutes per day"
        if not success_criteria:
            success_criteria = "accuracy and step stability both improve"
        if not suggestion:
            suggestion = f"focus practice on skill {skill_id} with step-by-step verification"
        normalized_weaknesses.append(
            {
                "skill_id": skill_id,
                "evidence": evidence,
                "priority": priority,
                "symptom": symptom,
                "cause": cause,
                "improvement_steps": steps,
                "practice_plan": practice_plan,
                "success_criteria": success_criteria,
                "suggestion": suggestion,
            }
        )
    profile["weaknesses"] = normalized_weaknesses
    return profile


def _build_rule_based_literacy_profile(
    questions: List[Dict[str, Any]],
    answers: List[Dict[str, Any]],
    literacy_mapping: Dict[str, Any],
) -> List[Dict[str, Any]]:
    if not questions:
        return []

    answer_by_qid: Dict[str, Dict[str, Any]] = {}
    for answer in answers:
        if not isinstance(answer, dict):
            continue
        qid = answer.get("question_id")
        if isinstance(qid, str) and qid:
            answer_by_qid.setdefault(qid, answer)

    question_type_rules = literacy_mapping.get("question_type_rules")
    if not isinstance(question_type_rules, dict):
        question_type_rules = {}
    skill_tag_rules = literacy_mapping.get("skill_tag_rules")
    if not isinstance(skill_tag_rules, list):
        skill_tag_rules = []
    error_type_penalties = literacy_mapping.get("error_type_penalties")
    if not isinstance(error_type_penalties, dict):
        error_type_penalties = {}
    wrong_step_keyword_penalties = literacy_mapping.get("wrong_step_keyword_penalties")
    if not isinstance(wrong_step_keyword_penalties, list):
        wrong_step_keyword_penalties = []

    literacy_scores: Dict[str, float] = {item["literacy_id"]: 0.5 for item in PROFILE_LITERACY_DIMENSIONS}
    literacy_evidence: Dict[str, List[str]] = {item["literacy_id"]: [] for item in PROFILE_LITERACY_DIMENSIONS}
    literacy_breakdown: Dict[str, Dict[str, int]] = {
        item["literacy_id"]: {"skill_tag": 0, "question_type": 0, "error_type": 0, "wrong_step": 0}
        for item in PROFILE_LITERACY_DIMENSIONS
    }
    literacy_reason_tokens: Dict[str, List[str]] = {item["literacy_id"]: [] for item in PROFILE_LITERACY_DIMENSIONS}

    for question in questions:
        if not isinstance(question, dict):
            continue
        qid = question.get("question_id")
        if not isinstance(qid, str) or not qid:
            continue
        answer = answer_by_qid.get(qid, {})
        ratio: Optional[float] = None
        if isinstance(answer, dict):
            score = answer.get("score")
            max_score = answer.get("max_score")
            if isinstance(score, (int, float)) and isinstance(max_score, (int, float)) and float(max_score) > 0:
                ratio = max(0.0, min(1.0, float(score) / float(max_score)))
            elif isinstance(answer.get("is_correct"), bool):
                ratio = 1.0 if answer.get("is_correct") else 0.0
        status = answer.get("status") if isinstance(answer, dict) else None
        signal = _question_literacy_signal(status, ratio)

        question_type = _normalize_question_type(question.get("question_type"))
        question_type_weights = question_type_rules.get(question_type)
        if isinstance(question_type_weights, dict):
            for literacy_id, weight in question_type_weights.items():
                try:
                    delta = float(weight) * signal
                except Exception:
                    continue
                if literacy_id not in literacy_scores:
                    continue
                literacy_scores[literacy_id] = max(0.0, min(1.0, literacy_scores[literacy_id] + delta))
                literacy_evidence[literacy_id].append(qid)
                literacy_breakdown[literacy_id]["question_type"] += 1
                literacy_reason_tokens[literacy_id].append(f"{qid} 的题型表现")

        skill_tags = question.get("skill_tags") if isinstance(question.get("skill_tags"), list) else []
        for tag in skill_tags:
            if not isinstance(tag, str) or not tag.strip():
                continue
            for rule in skill_tag_rules:
                if not isinstance(rule, dict):
                    continue
                pattern = rule.get("pattern")
                if not isinstance(pattern, str) or not _mapping_pattern_matches(pattern, tag):
                    continue
                weights = rule.get("literacy_weights")
                if not isinstance(weights, dict):
                    continue
                for literacy_id, weight in weights.items():
                    try:
                        delta = float(weight) * signal
                    except Exception:
                        continue
                    if literacy_id not in literacy_scores:
                        continue
                    literacy_scores[literacy_id] = max(0.0, min(1.0, literacy_scores[literacy_id] + delta))
                    literacy_evidence[literacy_id].append(qid)
                    literacy_breakdown[literacy_id]["skill_tag"] += 1
                    literacy_reason_tokens[literacy_id].append(f"{qid} 命中知识点 {tag}")

        error_analysis = answer.get("error_analysis") if isinstance(answer, dict) and isinstance(answer.get("error_analysis"), dict) else {}
        error_type = error_analysis.get("error_type")
        if isinstance(error_type, str):
            weights = error_type_penalties.get(error_type.strip().lower())
            if isinstance(weights, dict):
                for literacy_id, weight in weights.items():
                    try:
                        delta = float(weight)
                    except Exception:
                        continue
                    if literacy_id not in literacy_scores:
                        continue
                    literacy_scores[literacy_id] = max(0.0, min(1.0, literacy_scores[literacy_id] - delta))
                    literacy_evidence[literacy_id].append(qid)
                    literacy_breakdown[literacy_id]["error_type"] += 1
                    literacy_reason_tokens[literacy_id].append(f"{qid} 出现 {error_type} 错误")

        step_text_parts = []
        for key in ("wrong_step", "step_reason", "reason", "evidence"):
            value = error_analysis.get(key)
            if isinstance(value, str) and value.strip():
                step_text_parts.append(value.strip())
        combined_step_text = " ".join(step_text_parts)
        if combined_step_text:
            for rule in wrong_step_keyword_penalties:
                if not isinstance(rule, dict):
                    continue
                keyword = rule.get("keyword")
                if not isinstance(keyword, str) or not keyword.strip() or keyword not in combined_step_text:
                    continue
                weights = rule.get("literacy_weights")
                if not isinstance(weights, dict):
                    continue
                for literacy_id, weight in weights.items():
                    try:
                        delta = float(weight)
                    except Exception:
                        continue
                    if literacy_id not in literacy_scores:
                        continue
                    literacy_scores[literacy_id] = max(0.0, min(1.0, literacy_scores[literacy_id] - delta))
                    literacy_evidence[literacy_id].append(qid)
                    literacy_breakdown[literacy_id]["wrong_step"] += 1
                    literacy_reason_tokens[literacy_id].append(f"{qid} 在“{keyword}”环节失分")

    result: List[Dict[str, Any]] = []
    for item in PROFILE_LITERACY_DIMENSIONS:
        literacy_id = item["literacy_id"]
        evidence = list(dict.fromkeys([qid for qid in literacy_evidence[literacy_id] if isinstance(qid, str) and qid]))[:3]
        value = round(max(0.0, min(1.0, literacy_scores[literacy_id])), 2)
        if value >= 0.75:
            level = "high"
        elif value >= 0.45:
            level = "medium"
        else:
            level = "low"
        breakdown = literacy_breakdown[literacy_id]
        confidence_hits = sum(int(v) for v in breakdown.values())
        confidence = round(min(1.0, 0.35 + 0.1 * confidence_hits), 2) if confidence_hits > 0 else 0.3
        reason_tokens = list(dict.fromkeys(literacy_reason_tokens[literacy_id]))[:3]
        if reason_tokens:
            reason = "；".join(reason_tokens)
        else:
            reason = f"当前{item['name']}相关直接证据较少，先按全卷表现给出基线判断。"
        suggestion = f"围绕{item['name']}对应题型做专项训练，并在复盘中显式总结方法、易错点和改进步骤。"
        result.append(
            {
                "literacy_id": literacy_id,
                "name": item["name"],
                "definition": item["definition"],
                "value": value,
                "level": level,
                "evidence": evidence,
                "reason": reason,
                "suggestion": suggestion,
                "confidence": confidence,
                "source_breakdown": breakdown,
            }
        )
    return result


def _build_mock_exam_questions(
    skill_candidates: List[str],
    question_count: int,
) -> tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    fallback_skills = [sid for sid in skill_candidates if isinstance(sid, str) and sid.strip()]
    bank: List[Dict[str, Any]] = [
        {
            "question_type": "choice",
            "problem_text": "下列实数中，属于无理数的是",
            "problem_text_full": "1. 下列实数中，属于无理数的是（ ）\nA. 0.25\nB. 1/3\nC. √2\nD. -8",
            "skill_id": "number.concept.irrational",
            "correct_option": "C",
            "wrong_option": "A",
            "reference_final_answer": "C",
            "reference_steps": ["有理数可表示为分数", "√2不能写成分数形式", "故选C"],
        },
        {
            "question_type": "choice",
            "problem_text": "能与√5合并的二次根式是",
            "problem_text_full": "2. 能与 √5 合并的二次根式是（ ）\nA. √10\nB. 2√5\nC. √20\nD. √30",
            "skill_id": "root.method.add_sub",
            "correct_option": "B",
            "wrong_option": "C",
            "reference_final_answer": "B",
            "reference_steps": ["同类二次根式被开方数应相同", "A/C/D化简后被开方数不全为5", "故选B"],
        },
        {
            "question_type": "choice",
            "problem_text": "关于方程x²-4x+5=0的根，结论正确的是",
            "problem_text_full": "3. 关于方程 x²-4x+5=0 的根，结论正确的是（ ）\nA. 有两个不相等实根\nB. 有两个相等实根\nC. 无实根\nD. 有一实根一虚根",
            "skill_id": "eq.theorem.quadratic_discriminant",
            "correct_option": "C",
            "wrong_option": "A",
            "reference_final_answer": "C",
            "reference_steps": ["Δ=b²-4ac=16-20=-4", "Δ<0", "方程无实根，选C"],
        },
        {
            "question_type": "choice",
            "problem_text": "一次函数y=2x-3的图像特征是",
            "problem_text_full": "4. 一次函数 y=2x-3 的图像特征是（ ）\nA. 过原点\nB. 斜率为2且y轴截距为-3\nC. 斜率为-3\nD. 平行于x轴",
            "skill_id": "coord.method.line_equations",
            "correct_option": "B",
            "wrong_option": "A",
            "reference_final_answer": "B",
            "reference_steps": ["一次函数形式y=kx+b", "k=2,b=-3", "故选B"],
        },
        {
            "question_type": "choice",
            "problem_text": "数据2,3,3,5,9的中位数是",
            "problem_text_full": "5. 数据 2,3,3,5,9 的中位数是（ ）\nA. 3\nB. 4\nC. 5\nD. 9",
            "skill_id": "data.mean_median_variance",
            "correct_option": "A",
            "wrong_option": "B",
            "reference_final_answer": "A",
            "reference_steps": ["数据已按升序", "中间位置是第3个", "故中位数为3，选A"],
        },
        {
            "question_type": "choice",
            "problem_text": "下列条件能判定两三角形全等的是",
            "problem_text_full": "6. 下列条件能判定两三角形全等的是（ ）\nA. 两角对应相等\nB. 三边对应成比例\nC. 两边及其夹角对应相等\nD. 两边对应成比例且夹角相等",
            "skill_id": "geom.theorem.congruence",
            "correct_option": "C",
            "wrong_option": "D",
            "reference_final_answer": "C",
            "reference_steps": ["A仅能判相似", "B仅能判相似", "SAS可判全等", "故选C"],
        },
        {
            "question_type": "choice",
            "problem_text": "直角三角形两直角边为6和8，斜边长为",
            "problem_text_full": "7. 直角三角形两直角边长分别为6和8，则斜边长为（ ）\nA. 10\nB. 12\nC. 14\nD. 15",
            "skill_id": "geom.theorem.pythagorean",
            "correct_option": "A",
            "wrong_option": "B",
            "reference_final_answer": "A",
            "reference_steps": ["c²=6²+8²=100", "c=10", "故选A"],
        },
        {
            "question_type": "choice",
            "problem_text": "x²-9分解因式正确的是",
            "problem_text_full": "8. x²-9 分解因式正确的是（ ）\nA. (x-9)(x+1)\nB. (x-3)(x+3)\nC. (x-3)²\nD. x(x-9)",
            "skill_id": "algebra.formula.identity.diff_squares",
            "correct_option": "B",
            "wrong_option": "C",
            "reference_final_answer": "B",
            "reference_steps": ["平方差公式a²-b²=(a-b)(a+b)", "a=x,b=3", "故选B"],
        },
        {
            "question_type": "fill",
            "problem_text": "解方程2x+3=11",
            "problem_text_full": "9. 解方程：2x+3=11",
            "skill_id": "eq.method.linear_transpose",
            "reference_final_answer": "x=4",
            "wrong_final_answer": "x=3",
            "reference_steps": ["移项得2x=8", "两边同除以2", "x=4"],
        },
        {
            "question_type": "fill",
            "problem_text": "化简√50",
            "problem_text_full": "10. 化简：√50 = ____",
            "skill_id": "root.formula.mul",
            "reference_final_answer": "5√2",
            "wrong_final_answer": "25√2",
            "reference_steps": ["50=25×2", "√50=√25×√2", "结果5√2"],
        },
        {
            "question_type": "fill",
            "problem_text": "方程x²-5x+6=0的两根为",
            "problem_text_full": "11. 方程 x²-5x+6=0 的两根为 ____",
            "skill_id": "eq.formula.quadratic_formula",
            "reference_final_answer": "x=2,3",
            "wrong_final_answer": "x=1,6",
            "reference_steps": ["分解因式(x-2)(x-3)=0", "x-2=0或x-3=0", "x=2或3"],
        },
        {
            "question_type": "fill",
            "problem_text": "A(1,2),B(4,6)两点间距离",
            "problem_text_full": "12. 已知A(1,2),B(4,6)，则AB=____",
            "skill_id": "coord.formula.distance",
            "reference_final_answer": "5",
            "wrong_final_answer": "7",
            "reference_steps": ["AB=√((4-1)²+(6-2)²)", "AB=√(9+16)", "AB=5"],
        },
        {
            "question_type": "fill",
            "problem_text": "过点(1,2)且斜率为3的直线解析式",
            "problem_text_full": "13. 过点(1,2)且斜率为3的直线解析式是 ____",
            "skill_id": "coord.method.line_equations",
            "reference_final_answer": "y=3x-1",
            "wrong_final_answer": "y=3x+2",
            "reference_steps": ["设y=3x+b", "代入(1,2)得b=-1", "故y=3x-1"],
        },
        {
            "question_type": "fill",
            "problem_text": "2,4,6,8,10的平均数",
            "problem_text_full": "14. 数据2,4,6,8,10的平均数是 ____",
            "skill_id": "data.mean_median_variance",
            "reference_final_answer": "6",
            "wrong_final_answer": "5",
            "reference_steps": ["求和30", "除以5", "平均数6"],
        },
        {
            "question_type": "fill",
            "problem_text": "解不等式3x-5>7",
            "problem_text_full": "15. 解不等式：3x-5>7",
            "skill_id": "ineq.method.sign_chart",
            "reference_final_answer": "x>4",
            "wrong_final_answer": "x<4",
            "reference_steps": ["移项3x>12", "两边同除以3", "x>4"],
        },
        {
            "question_type": "solution",
            "problem_text": "已知一次函数过(0,1),(2,5)，求解析式并求x=4时y",
            "problem_text_full": "16. 已知一次函数图像过点(0,1)与(2,5)：\n(1) 求函数解析式；\n(2) 求x=4时函数值。",
            "skill_id": "coord.method.line_equations",
            "reference_final_answer": "y=2x+1, y(4)=9",
            "reference_steps": ["由两点求斜率k=2", "代入点(0,1)得b=1", "解析式y=2x+1并求y(4)=9"],
        },
        {
            "question_type": "solution",
            "problem_text": "证明两三角形全等并求角度",
            "problem_text_full": "17. 在△ABC与△DEF中，已知AB=DE，∠A=∠D，AC=DF。\n(1) 证明△ABC≌△DEF；\n(2) 若∠B=55°，求∠E。",
            "skill_id": "geom.theorem.congruence",
            "reference_final_answer": "SAS全等，∠E=55°",
            "reference_steps": ["由两边及夹角对应相等得SAS", "判定两三角形全等", "对应角相等得∠E=∠B=55°"],
        },
        {
            "question_type": "solution",
            "problem_text": "梯子问题（勾股定理）",
            "problem_text_full": "18. 一把长10m的梯子斜靠在墙上，梯脚距墙6m。\n(1) 求梯顶离地高度；\n(2) 若梯脚再外移2m，高度变为多少？",
            "skill_id": "geom.theorem.pythagorean",
            "reference_final_answer": "高度8m；外移后高度6m",
            "reference_steps": ["第一次h²=10²-6²=64，h=8", "外移后底边8m", "新高度√(10²-8²)=6"],
        },
        {
            "question_type": "solution",
            "problem_text": "应用题：长方形面积",
            "problem_text_full": "19. 一长方形长比宽多4cm，面积为96cm²，求长与宽。",
            "skill_id": "eq.theorem.quadratic_discriminant",
            "reference_final_answer": "宽8cm，长12cm",
            "reference_steps": ["设宽x，则长x+4", "列方程x(x+4)=96", "解得x=8（舍负），长12"],
        },
        {
            "question_type": "solution",
            "problem_text": "解分式方程并检验",
            "problem_text_full": "20. 解方程：1/(x-1) + 1/(x+1) = 1",
            "skill_id": "eq.method.linear_transpose",
            "reference_final_answer": "x=1±√2",
            "reference_steps": ["通分得2x=x²-1", "化为x²-2x-1=0", "解得x=1±√2并检验（x≠±1）"],
        },
        {
            "question_type": "solution",
            "problem_text": "坐标系中三角形面积",
            "problem_text_full": "21. 已知A(0,0),B(4,0),C(2,3)，求△ABC面积。",
            "skill_id": "coord.formula.distance",
            "reference_final_answer": "6",
            "reference_steps": ["AB为底边长4", "C到AB高为3", "面积=1/2×4×3=6"],
        },
        {
            "question_type": "solution",
            "problem_text": "数据统计与方差比较",
            "problem_text_full": "22. 甲、乙两组数据平均数都为70，甲方差4，乙方差9。\n比较两组成绩稳定性并说明理由。",
            "skill_id": "data.mean_median_variance",
            "reference_final_answer": "甲更稳定",
            "reference_steps": ["平均数相同可直接比较方差", "方差越小波动越小", "4<9，故甲更稳定"],
        },
        {
            "question_type": "solution",
            "problem_text": "新定义运算求值",
            "problem_text_full": "23. 定义a⊙b=2a-b+1，求(3⊙2)⊙1。",
            "skill_id": "algebra.concept.variable_expression",
            "reference_final_answer": "8",
            "reference_steps": ["先算3⊙2=2×3-2+1=5", "再算5⊙1=2×5-1+1", "结果8"],
        },
        {
            "question_type": "solution",
            "problem_text": "角平分线性质综合",
            "problem_text_full": "24. 在△ABC中，AD平分∠A，且BD=6,DC=4,AB=9。\n(1) 求AC；(2) 判断△ABC是否等腰并说明。",
            "skill_id": "geom.properties.angle_bisector",
            "reference_final_answer": "AC=6，不是等腰三角形",
            "reference_steps": ["角平分线定理AB/AC=BD/DC=6/4", "代入AB=9得AC=6", "AB≠AC且AB≠BC，故不是等腰"],
        },
        {
            "question_type": "solution",
            "problem_text": "二元一次方程组应用",
            "problem_text_full": "25. 某班买笔和本共40件，笔每支3元，本每本5元，总价164元，求各买多少。",
            "skill_id": "eq.method.linear_eliminate",
            "reference_final_answer": "笔18支，本22本",
            "reference_steps": ["设笔x本y，列x+y=40,3x+5y=164", "消元得2y=44", "y=22,x=18"],
        },
        {
            "question_type": "solution",
            "problem_text": "二次函数顶点与最值",
            "problem_text_full": "26. 已知y=x²-4x+7。\n(1) 写出顶点坐标；(2) 求最小值。",
            "skill_id": "function.domain_range.basic",
            "reference_final_answer": "顶点(2,3)，最小值3",
            "reference_steps": ["配方y=(x-2)²+3", "顶点为(2,3)", "开口向上，最小值3"],
        },
        {
            "question_type": "solution",
            "problem_text": "综合压轴：图形面积与方程",
            "problem_text_full": "27. 在直角坐标系中，点A(0,0),B(6,0),C(0,4)。点P在AB上，设P(t,0)。\n(1) 用t表示△PCB面积S；\n(2) 当S=6时求t。",
            "skill_id": "model.word_problem",
            "reference_final_answer": "S=12-2t，t=3",
            "reference_steps": ["BC所在直线到P的高为4，底PB=6-t", "S=1/2·(6-t)·4=12-2t", "令12-2t=6得t=3"],
        },
    ]

    questions: List[Dict[str, Any]] = []
    answer_meta: Dict[str, Dict[str, Any]] = {}
    for idx in range(question_count):
        source = bank[idx % len(bank)]
        qid = f"Q{idx + 1}"
        sid = source.get("skill_id")
        if not isinstance(sid, str) or not sid.strip():
            sid = fallback_skills[idx % len(fallback_skills)] if fallback_skills else "eq.method.linear_transpose"
        item = {
            "question_id": qid,
            "raw_question_id": str(idx + 1),
            "question_type": source["question_type"],
            "problem_text": source["problem_text"],
            "problem_text_full": source["problem_text_full"],
            "sub_questions": [],
            "skill_tags": [sid],
            "confidence": round(0.8 + (idx % 4) * 0.04, 2),
        }
        questions.append(item)
        answer_meta[qid] = {
            "reference_final_answer": source.get("reference_final_answer"),
            "reference_steps": source.get("reference_steps"),
            "correct_option": source.get("correct_option"),
            "wrong_option": source.get("wrong_option"),
            "wrong_final_answer": source.get("wrong_final_answer"),
        }
    questions = _attach_question_metadata(questions)
    return questions, answer_meta


def _mock_localize_skill_name(skill_id: Any, skill_alias_map: Dict[str, str]) -> Any:
    if not isinstance(skill_id, str):
        return skill_id
    raw = skill_id.strip()
    if not raw:
        return skill_id
    alias = skill_alias_map.get(raw)
    if isinstance(alias, str) and alias.strip():
        alias_text = alias.strip()
        if alias_text != raw or re.search(r"[\u4e00-\u9fff]", alias_text):
            return alias_text
    mock_fallback = {
        "number.concept.irrational": "无理数概念",
        "root.method.add_sub": "同类二次根式加减",
        "eq.theorem.quadratic_discriminant": "判别式与根的性质",
        "coord.method.line_equations": "一次函数解析式",
        "data.mean_median_variance": "平均数与方差",
        "geom.theorem.congruence": "全等三角形判定",
        "geom.theorem.pythagorean": "勾股定理应用",
        "algebra.formula.identity.diff_squares": "平方差公式",
        "eq.method.linear_transpose": "一元一次方程移项",
        "root.formula.mul": "二次根式化简",
        "eq.formula.quadratic_formula": "一元二次方程求根",
        "coord.formula.distance": "两点距离公式",
        "ineq.method.sign_chart": "一元一次不等式",
        "function.domain_range.basic": "二次函数最值",
        "model.word_problem": "应用题建模",
    }
    return mock_fallback.get(raw, raw)


def _mock_localize_skill_tags(tags: Any, skill_alias_map: Dict[str, str]) -> Any:
    if not isinstance(tags, list):
        return tags
    return [_mock_localize_skill_name(tag, skill_alias_map) for tag in tags]


def _mock_localize_skill_payload(
    *,
    question_analysis: List[Dict[str, Any]],
    structured_questions_full: List[Dict[str, Any]],
    answer_trace: List[Dict[str, Any]],
    answer_trace_display: List[Dict[str, Any]],
    student_profile: Dict[str, Any],
    skill_alias_map: Dict[str, str],
) -> None:
    def _localize_answer_item(answer_item: Dict[str, Any]) -> None:
        answer_item["skill_tags"] = _mock_localize_skill_tags(answer_item.get("skill_tags"), skill_alias_map)
        observations = answer_item.get("skill_observations")
        if isinstance(observations, list):
            for obs in observations:
                if not isinstance(obs, dict):
                    continue
                obs["skill_id"] = _mock_localize_skill_name(obs.get("skill_id"), skill_alias_map)

    for item in question_analysis:
        if not isinstance(item, dict):
            continue
        item["skill_tags"] = _mock_localize_skill_tags(item.get("skill_tags"), skill_alias_map)
        answer_item = item.get("answer_trace")
        if isinstance(answer_item, dict):
            _localize_answer_item(answer_item)
        sub_traces = item.get("sub_traces")
        if isinstance(sub_traces, list):
            for sub in sub_traces:
                if isinstance(sub, dict):
                    _localize_answer_item(sub)

    for item in structured_questions_full:
        if not isinstance(item, dict):
            continue
        item["skill_tags"] = _mock_localize_skill_tags(item.get("skill_tags"), skill_alias_map)
        answer_item = item.get("answer_trace")
        if isinstance(answer_item, dict):
            _localize_answer_item(answer_item)
        sub_traces = item.get("sub_traces")
        if isinstance(sub_traces, list):
            for sub in sub_traces:
                if isinstance(sub, dict):
                    _localize_answer_item(sub)

    for answer in answer_trace:
        if isinstance(answer, dict):
            _localize_answer_item(answer)

    for answer in answer_trace_display:
        if isinstance(answer, dict):
            _localize_answer_item(answer)

    mastery = student_profile.get("mastery")
    if isinstance(mastery, list):
        for item in mastery:
            if isinstance(item, dict):
                item["skill_id"] = _mock_localize_skill_name(item.get("skill_id"), skill_alias_map)

    weaknesses = student_profile.get("weaknesses")
    if isinstance(weaknesses, list):
        for item in weaknesses:
            if isinstance(item, dict):
                item["skill_id"] = _mock_localize_skill_name(item.get("skill_id"), skill_alias_map)
