from __future__ import annotations

from datetime import datetime, timedelta
from random import Random
from typing import Any, Dict, List


def _to_int(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _to_str(raw: Any, default: str) -> str:
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return default


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _clamp_float(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _level_by_score(score: float) -> str:
    if score >= 0.8:
        return "熟练"
    if score >= 0.65:
        return "稳定"
    if score >= 0.5:
        return "发展中"
    return "薄弱"


def _series_average(values: List[List[float]]) -> List[float]:
    if not values:
        return []
    length = len(values[0])
    result: List[float] = []
    for idx in range(length):
        result.append(round(sum(row[idx] for row in values) / len(values), 4))
    return result


def _build_mock_analysis_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now()
    seed = _to_int(payload.get("seed"), 20260418)
    periods = _clamp(_to_int(payload.get("periods"), 10), 6, 24)
    knowledge_points = _clamp(_to_int(payload.get("knowledge_points"), 6), 4, 10)
    students = _clamp(_to_int(payload.get("students"), 120), 30, 300)
    student_id = _to_str(payload.get("student_id"), "S001")
    class_name = _to_str(payload.get("class_name"), "八年级(1)班")
    rng = Random(seed)

    period_labels: List[str] = []
    for idx in range(periods):
        point_date = now - timedelta(days=(periods - 1 - idx) * 7)
        period_labels.append(point_date.strftime("%m-%d"))

    candidate_knowledges = [
        ("eq.linear_transform", "一次方程移项"),
        ("eq.fraction_solve", "分式方程求解"),
        ("func.domain_range", "函数定义域值域"),
        ("geo.triangle_similarity", "三角形相似"),
        ("geo.parallel_proof", "平行线性质证明"),
        ("stats.mean_variance", "均值方差"),
        ("algebra.factorization", "因式分解"),
        ("algebra.root_equation", "一元二次方程"),
        ("model.word_problem", "应用题建模"),
        ("logic.reasoning_chain", "推理链构造"),
    ]
    selected = candidate_knowledges[:knowledge_points]

    knowledge_history = []
    knowledge_series_rows: List[List[float]] = []
    for kid, name in selected:
        start = rng.uniform(0.35, 0.68)
        series = []
        current = start
        for _ in range(periods):
            current = _clamp_float(current + rng.uniform(-0.012, 0.035), 0.18, 0.98)
            series.append(round(current, 4))
        knowledge_series_rows.append(series)
        delta = round(series[-1] - series[0], 4)
        knowledge_history.append(
            {
                "knowledge_id": kid,
                "knowledge_name": name,
                "periods": period_labels,
                "series": series,
                "start_mastery": series[0],
                "current_mastery": series[-1],
                "delta_mastery": delta,
                "level": _level_by_score(series[-1]),
            }
        )

    literacy_dims = [
        ("logical_reasoning", "逻辑推理"),
        ("abstraction", "抽象建模"),
        ("computation", "运算规范"),
        ("representation", "表征转化"),
        ("reflection", "反思修正"),
    ]
    literacy_history = []
    literacy_series_rows: List[List[float]] = []
    for dim_id, dim_name in literacy_dims:
        start = rng.uniform(0.42, 0.72)
        series = []
        current = start
        for _ in range(periods):
            current = _clamp_float(current + rng.uniform(-0.01, 0.026), 0.20, 0.96)
            series.append(round(current, 4))
        literacy_series_rows.append(series)
        delta = round(series[-1] - series[0], 4)
        literacy_history.append(
            {
                "dimension_id": dim_id,
                "dimension_name": dim_name,
                "periods": period_labels,
                "series": series,
                "start_score": series[0],
                "current_score": series[-1],
                "delta_score": delta,
            }
        )

    overall_mastery = _series_average(knowledge_series_rows)
    overall_literacy = _series_average(literacy_series_rows)

    weakest = min(knowledge_history, key=lambda item: float(item["current_mastery"])) if knowledge_history else None
    warning_events = sum(1 for item in knowledge_history if float(item["delta_mastery"]) < 0.0)

    event_notes = [
        "阶段测验错因集中在计算步骤",
        "课堂提问表现提升明显",
        "迁移题型出现思路中断",
        "作业订正后同类题稳定",
        "表达步骤不完整导致失分",
        "复习后概念辨析改善",
    ]
    recent_events = []
    event_count = min(8, periods)
    for idx in range(event_count):
        k = knowledge_history[idx % len(knowledge_history)]
        sample_pos = max(1, periods - event_count + idx)
        before = float(k["series"][sample_pos - 1])
        after = float(k["series"][sample_pos])
        recent_events.append(
            {
                "date": period_labels[sample_pos],
                "knowledge_id": k["knowledge_id"],
                "knowledge_name": k["knowledge_name"],
                "mastery_before": round(before, 4),
                "mastery_after": round(after, 4),
                "literacy_impact": round(rng.uniform(-0.03, 0.05), 4),
                "note": event_notes[idx % len(event_notes)],
            }
        )

    student_names = ["王子涵", "李思睿", "张雨桐", "赵锦程", "孙若彤", "周泽宇"]
    student_name = student_names[seed % len(student_names)]

    temporal_analysis = {
        "student": {
            "student_id": student_id,
            "name": student_name,
            "class_name": class_name,
        },
        "summary": {
            "window_start": period_labels[0],
            "window_end": period_labels[-1],
            "mastery_gain": round(overall_mastery[-1] - overall_mastery[0], 4),
            "literacy_gain": round(overall_literacy[-1] - overall_literacy[0], 4),
            "knowledge_points_count": len(knowledge_history),
            "current_literacy": overall_literacy[-1],
            "weakest_knowledge": weakest["knowledge_name"] if weakest else "",
            "warning_events": warning_events,
        },
        "series": {
            "periods": period_labels,
            "overall_mastery": overall_mastery,
            "overall_literacy": overall_literacy,
        },
        "knowledge_history": knowledge_history,
        "literacy_history": literacy_history,
        "recent_events": recent_events,
    }

    class_knowledge = []
    for item in knowledge_history:
        class_avg = _clamp_float(float(item["current_mastery"]) + rng.uniform(-0.08, 0.06), 0.2, 0.95)
        pass_rate = _clamp_float(class_avg * rng.uniform(0.85, 1.02), 0.1, 0.98)
        low_mastery = int(round((1 - class_avg) * students * rng.uniform(0.3, 0.7)))
        if class_avg < 0.5:
            priority = "高"
        elif class_avg < 0.65:
            priority = "中"
        else:
            priority = "低"
        class_knowledge.append(
            {
                "knowledge_id": item["knowledge_id"],
                "knowledge_name": item["knowledge_name"],
                "avg_mastery": round(class_avg, 4),
                "pass_rate": round(pass_rate, 4),
                "low_mastery_count": low_mastery,
                "priority": priority,
            }
        )
    class_knowledge.sort(key=lambda x: float(x["avg_mastery"]))

    radar_dims = []
    for dim in literacy_history:
        score = _clamp_float(float(dim["current_score"]) + rng.uniform(-0.06, 0.08), 0.2, 0.96)
        radar_dims.append(
            {
                "dimension_id": dim["dimension_id"],
                "dimension_name": dim["dimension_name"],
                "score": round(score, 4),
            }
        )

    class_avg_mastery = round(sum(float(x["avg_mastery"]) for x in class_knowledge) / max(len(class_knowledge), 1), 4)
    class_avg_literacy = round(sum(float(x["score"]) for x in radar_dims) / max(len(radar_dims), 1), 4)
    risk_rate = round(_clamp_float(0.08 + (0.65 - class_avg_mastery) * 0.5 + rng.uniform(-0.04, 0.05), 0.05, 0.55), 4)
    focus_weak = [item["knowledge_name"] for item in class_knowledge[:3]]

    group_analysis = {
        "class_profile": {
            "class_id": "CLS-01",
            "class_name": class_name,
            "student_count": students,
            "avg_mastery": class_avg_mastery,
            "avg_literacy": class_avg_literacy,
            "risk_rate": risk_rate,
            "focus_weak_knowledge": focus_weak,
        },
        "knowledge_mastery_overview": class_knowledge,
        "literacy_radar": {
            "dimensions": radar_dims,
        },
    }

    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "parameters": {
            "seed": seed,
            "periods": periods,
            "knowledge_points": knowledge_points,
            "students": students,
            "student_id": student_id,
            "class_name": class_name,
        },
        "temporal_analysis": temporal_analysis,
        "group_analysis": group_analysis,
    }


def _build_mock_profile_export(payload: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now().astimezone()
    seed = _to_int(payload.get("seed"), 20260418)
    student_id = _to_str(payload.get("student_id"), "41201200")
    input_mode = _to_str(payload.get("input_mode"), "paper_answer_sheet")
    question_count = _clamp(_to_int(payload.get("question_count"), 27), 18, 36)
    paper_image_count = _clamp(_to_int(payload.get("paper_image_count"), 4), 1, 8)
    rng = Random(seed)

    started_at = now - timedelta(seconds=rng.randint(420, 980))
    finished_at = now

    skill_pool = [
        ("eq.method.linear_transpose", "一次方程移项解法", "方程建模与求解步骤规范，检验意识较好"),
        ("root.formula.mul", "二次根式乘除", "根式化简过程完整，符号处理稳定"),
        ("geom.theorem.congruence", "全等三角形判定", "证明链清晰，条件使用准确"),
        ("stats.mean_variance", "均值与方差", "数据读取准确，计算较稳定"),
        ("root.method.add_sub", "同类二次根式加减", "同类项判定偶有混淆"),
        ("eq.theorem.quadratic_discriminant", "判别式与根的性质", "综合判断易遗漏限制条件"),
        ("geom.theorem.pythagorean", "勾股定理综合", "图形关系识别不够稳，复杂情境波动明显"),
        ("geom.properties.angle_bisector", "角平分线性质", "分类讨论意识不足，易出现漏解"),
        ("geom.method.construction", "几何作图与构造", "新定义题作答结构不完整"),
        ("model.word_problem", "应用题建模", "数量关系抽象速度偏慢"),
    ]
    skill_alias_map = {skill_id: alias for skill_id, alias, _ in skill_pool}

    base_mastery = {
        "eq.method.linear_transpose": 0.93,
        "root.formula.mul": 0.9,
        "geom.theorem.congruence": 0.87,
        "stats.mean_variance": 0.81,
        "root.method.add_sub": 0.68,
        "eq.theorem.quadratic_discriminant": 0.61,
        "geom.theorem.pythagorean": 0.56,
        "geom.properties.angle_bisector": 0.52,
        "geom.method.construction": 0.46,
        "model.word_problem": 0.58,
    }
    mastery_rows = []
    for skill_id, _, reason in skill_pool:
        val = _clamp_float(base_mastery[skill_id] + rng.uniform(-0.04, 0.04), 0.3, 0.97)
        mastery_rows.append(
            {
                "skill_id": skill_id,
                "value": round(val, 2),
                "reason": reason,
            }
        )
    mastery_rows.sort(key=lambda item: float(item["value"]), reverse=True)

    question_templates = [
        ("choice", "下列各式中属于最简二次根式的是", "root.method.add_sub"),
        ("choice", "已知一元二次方程，判别式满足的结论是", "eq.theorem.quadratic_discriminant"),
        ("fill", "化简并求值：二次根式运算", "root.formula.mul"),
        ("fill", "解方程并写出检验过程", "eq.method.linear_transpose"),
        ("solve", "在直角三角形中求未知边长", "geom.theorem.pythagorean"),
        ("solve", "证明两三角形全等并求角", "geom.theorem.congruence"),
        ("solve", "角平分线相关性质证明", "geom.properties.angle_bisector"),
        ("solve", "新定义几何背景下的构造与证明", "geom.method.construction"),
        ("solve", "阅读材料并完成建模求解", "model.word_problem"),
        ("choice", "某组数据的均值和方差判断", "stats.mean_variance"),
    ]

    mastery_lookup = {item["skill_id"]: float(item["value"]) for item in mastery_rows}
    question_analysis: List[Dict[str, Any]] = []
    structured_questions_full: List[Dict[str, Any]] = []
    answer_trace: List[Dict[str, Any]] = []
    answer_trace_display: List[Dict[str, Any]] = []
    error_counts = {"concept": 0, "calculation": 0, "reading": 0, "strategy": 0, "unknown": 0}

    for idx in range(question_count):
        qid = f"Q{idx + 1}"
        qtype, anchor, skill_id = question_templates[idx % len(question_templates)]
        max_score = 20 if qtype == "choice" else (24 if qtype == "fill" else 28)
        mastery_score = mastery_lookup.get(skill_id, 0.62)
        correctness_prob = _clamp_float(0.25 + mastery_score * 0.7, 0.35, 0.95)
        correct = rng.random() < correctness_prob

        if correct:
            if rng.random() < 0.2:
                score = max_score - rng.randint(1, 2)
                error_type = "strategy"
                reason = "核心思路正确，但关键步骤表述不完整导致过程分损失"
                suggestion = "保持当前思路，补齐推导步骤与结论论证"
            else:
                score = max_score
                error_type = "unknown"
                reason = "作答正确，无明显错误"
                suggestion = "保持当前优势，继续巩固同类型题"
        else:
            drop = max(2, int(round(max_score * rng.uniform(0.2, 0.55))))
            score = max(0, max_score - drop)
            roll = rng.random()
            if roll < 0.42:
                error_type = "concept"
                reason = "概念边界识别不清，关键定义应用出现偏差"
                suggestion = "先回顾定义，再做2-3道同类基础题强化判别"
            elif roll < 0.67:
                error_type = "strategy"
                reason = "解题路径选择不稳定，未先建立清晰的中间关系"
                suggestion = "练习先列条件-目标-关系，再展开计算"
            elif roll < 0.86:
                error_type = "calculation"
                reason = "计算过程有符号/代数化简失误，导致结果偏差"
                suggestion = "分步书写并在关键转换处复核符号"
            else:
                error_type = "reading"
                reason = "审题未覆盖全部约束，遗漏条件导致答案不完整"
                suggestion = "圈画题干约束词，列检查清单后再作答"
        error_counts[error_type] += 1

        trace_item = {
            "question_id": qid,
            "question_type": qtype,
            "skill_tags": [skill_id],
            "status": "answered",
            "score": score,
            "max_score": max_score,
            "is_correct": None,
            "selected_option": None,
            "filled_value": None,
            "student_answer_text": None,
            "answer_text": None,
            "steps": [],
            "skill_observations": [],
            "trace": {
                "scratchwork": None,
                "corrections": None,
                "readability": None,
                "confidence": None,
                "notes": None,
            },
            "raw_question_id": qid,
            "sub_question_id": None,
            "raw_sub_question_id": None,
            "error_analysis": {
                "error_type": error_type,
                "reason": reason,
                "evidence": f"本题得分{score}分，满分{max_score}分",
                "suggestion": suggestion,
            },
        }

        q_item = {
            "question_id": qid,
            "raw_question_id": qid,
            "question_type": qtype,
            "problem_text": anchor,
            "problem_text_full": f"{idx + 1}. {anchor}",
            "skill_tags": [skill_id],
            "confidence": round(rng.uniform(0.74, 0.98), 2),
            "max_score": None,
            "sub_questions": [],
            "paper_page_index": idx // 7,
            "question_order_index": idx,
            "question_anchor_text": anchor,
            "neighbor_question_ids": [f"Q{idx}"] if idx > 0 else ([f"Q{idx + 2}"] if question_count > 1 else []),
            "answer_page_hint": idx // 14,
            "answer_page_hint_confidence": round(rng.uniform(0.75, 0.95), 2),
            "answer_page_hint_evidence": "题号定位与答题区域一致",
            "answer_trace": trace_item,
            "sub_traces": [],
        }
        question_analysis.append(q_item)
        structured_questions_full.append(dict(q_item))
        answer_trace.append(dict(trace_item))

        display_item = dict(trace_item)
        display_item.update(
            {
                "display_question_id": qid,
                "parent_question_id": qid,
                "question_anchor_text": anchor,
                "problem_text": anchor,
                "sub_question_text": None,
                "is_question_summary": False,
            }
        )
        answer_trace_display.append(display_item)

    weakness_templates = {
        "root.method.add_sub": {
            "priority": "medium",
            "symptom": "同类二次根式判定不稳定，选择与填空题失分波动较大",
            "cause": "未先化简到最简形式就进行同类项判断，规则触发顺序混乱",
            "improvement_steps": [
                "整理同类二次根式判定流程：化简 -> 比较被开方数 -> 合并",
                "完成4道判定+2道合并专项题，并口述每一步依据",
            ],
            "practice_plan": "连续3天每天15分钟：2道判定题+1道合并题",
            "success_criteria": "同类题连续两次正确率达到90%以上",
            "suggestion": "把“先化简再判断”固定为首步骤，避免凭直觉处理",
        },
        "eq.theorem.quadratic_discriminant": {
            "priority": "high",
            "symptom": "根的个数与性质类综合判断题易漏条件",
            "cause": "判别式与参数取值联动推理不够完整，缺少边界检查",
            "improvement_steps": [
                "复盘判别式三种取值对应结论，并标注参数边界",
                "完成5道结论判断题，逐选项给出证伪或证明过程",
            ],
            "practice_plan": "连续4天每天20分钟：3道基础+2道综合判断",
            "success_criteria": "同类综合题正确率稳定在85%以上",
            "suggestion": "每次先列Delta与参数范围，再推导结论",
        },
        "geom.theorem.pythagorean": {
            "priority": "high",
            "symptom": "复杂图形中边角关系提取慢，建模方程不完整",
            "cause": "图形分解与辅助线意识不足，关系转换链断裂",
            "improvement_steps": [
                "训练三类经典构型的边角关系抽取模板",
                "每题先写“已知-目标-关键关系”再代入计算",
            ],
            "practice_plan": "连续3天每天15分钟：1道基础+1道综合图形题",
            "success_criteria": "复杂图形题能完整列出关键等量关系",
            "suggestion": "先结构化标注图形，再进入公式计算",
        },
        "geom.properties.angle_bisector": {
            "priority": "medium",
            "symptom": "分类讨论场景有漏解，证明链不闭合",
            "cause": "审题阶段未显式列出可能情形，讨论分支管理不足",
            "improvement_steps": [
                "归纳需分类讨论的关键词并建立检查清单",
                "专项训练3道分类题，确保分支全覆盖后再求解",
            ],
            "practice_plan": "连续2天每天12分钟：1道分类题+复盘1道错题",
            "success_criteria": "分类题连续3题无漏解",
            "suggestion": "写出分支树后再解题，避免中途遗漏情形",
        },
        "geom.method.construction": {
            "priority": "high",
            "symptom": "新定义几何题只给结论，过程与论证不足",
            "cause": "作答框架未先规划，步骤分层与表达意识偏弱",
            "improvement_steps": [
                "按“定义解释-构造-证明-计算-结论”模板训练",
                "完成2道新定义题并对照评分点自查",
            ],
            "practice_plan": "连续3天每天20分钟：1道新定义几何完整作答",
            "success_criteria": "作答环节完整，过程分丢失显著下降",
            "suggestion": "先列作答提纲，再逐段输出过程",
        },
        "model.word_problem": {
            "priority": "medium",
            "symptom": "文字条件转方程耗时长，易遗漏隐含约束",
            "cause": "变量定义和单位检查不系统，建模步骤跳跃",
            "improvement_steps": [
                "固定变量定义模板并记录单位",
                "完成4道应用题并逐步校验约束完整性",
            ],
            "practice_plan": "连续3天每天15分钟：2道中等难度应用题",
            "success_criteria": "建模题约束覆盖完整，错因集中下降",
            "suggestion": "把题干信息先表格化，再写方程",
        },
    }

    sorted_mastery = sorted(mastery_rows, key=lambda item: float(item["value"]))
    weaknesses: List[Dict[str, Any]] = []
    for row in sorted_mastery[:5]:
        sid = str(row["skill_id"])
        tpl = weakness_templates.get(sid)
        if not tpl:
            continue
        weaknesses.append(
            {
                "skill_id": sid,
                "evidence": [f"Q{rng.randint(1, question_count)}", f"Q{rng.randint(1, question_count)}"],
                "priority": tpl["priority"],
                "symptom": tpl["symptom"],
                "cause": tpl["cause"],
                "improvement_steps": tpl["improvement_steps"],
                "practice_plan": tpl["practice_plan"],
                "success_criteria": tpl["success_criteria"],
                "suggestion": tpl["suggestion"],
            }
        )
    weaknesses = weaknesses[:4]

    unknown_count = max(0, question_count - sum(error_counts.values()))
    error_counts["unknown"] += unknown_count

    profile_summary = (
        "学生在基础方程求解、根式运算和常规几何证明方面表现稳定，说明基本功较扎实；"
        "在判别式综合判断、复杂图形建模、分类讨论与新定义题规范作答方面仍有波动。"
        "建议按“概念澄清-模板化训练-错因复盘”三步推进，以提升综合题稳定性与表达完整度。"
    )
    student_profile = {
        "student_id": student_id,
        "mastery": mastery_rows,
        "error_profile": error_counts,
        "weaknesses": weaknesses,
        "summary": profile_summary,
    }

    mapping_report = {
        "total_questions": question_count,
        "mapped_questions": question_count,
        "missing_from_step1": [],
        "unmatched_traces": [],
        "sub_question_mapped_count": max(2, question_count // 6),
        "question_pass_chunks": max(4, question_count // 5),
        "answer_pass_chunks": max(8, question_count // 2),
        "route_pass_chunks": max(6, question_count // 3),
        "repair_rounds_used": 1,
        "repaired_questions_count": max(6, question_count // 2),
        "route_hinted_count": question_count,
        "score_conflict_count": 0,
        "score_conflict_question_ids": [],
        "knowledge_tagging_count": question_count - rng.randint(0, 2),
        "objective_pass_chunks": max(1, question_count // 20),
        "subjective_pass_chunks": max(4, question_count // 3),
        "matching_repair_rounds": 1,
        "error_analysis_count": question_count,
        "paper_parallel_tasks": paper_image_count,
        "answer_parallel_tasks": max(4, question_count // 2),
        "answer_segment_saved_crop_count": max(6, question_count // 2),
        "answer_segment_saved_crop_dir": f"D:\\project\\testpaper\\outputs\\answer_sheet_crops\\{student_id}\\{now.strftime('%Y%m%d_%H%M%S')}",
    }

    stages = [
        {
            "stage": "validate_input",
            "status": "ok",
            "input_mode": input_mode,
            "paper_image_count": paper_image_count,
            "answer_image_count": 2,
            "elapsed_ms": round(rng.uniform(0, 40), 1),
        },
        {
            "stage": "question_analysis",
            "status": "ok",
            "index_batches_total": paper_image_count,
            "index_batches_success": paper_image_count,
            "index_batches_failed": 0,
            "question_pass_chunks": mapping_report["question_pass_chunks"],
            "question_repair_rounds": 0,
            "repaired_questions_count": 0,
            "paper_parallel_tasks": mapping_report["paper_parallel_tasks"],
            "question_count": question_count,
            "missing_question_count": 0,
            "elapsed_ms": round(rng.uniform(82000, 150000), 1),
        },
        {
            "stage": "knowledge_tagging",
            "status": "ok",
            "question_count": question_count,
            "tagged_question_count": mapping_report["knowledge_tagging_count"],
            "elapsed_ms": round(rng.uniform(18000, 36000), 1),
        },
        {
            "stage": "new_knowledge_points",
            "status": "ok",
            "added_count": 0,
            "elapsed_ms": round(rng.uniform(0.1, 1.5), 1),
        },
        {
            "stage": "answer_route",
            "status": "ok",
            "batches_total": 2,
            "batches_success": 2,
            "batches_failed": 0,
            "route_pass_chunks": mapping_report["route_pass_chunks"],
            "route_hinted_count": mapping_report["route_hinted_count"],
            "answer_parallel_tasks": mapping_report["answer_parallel_tasks"],
            "elapsed_ms": round(rng.uniform(90000, 180000), 1),
        },
        {
            "stage": "error_analysis",
            "status": "ok",
            "error_analysis_count": mapping_report["error_analysis_count"],
            "elapsed_ms": round(rng.uniform(30000, 85000), 1),
        },
        {
            "stage": "answer_trace",
            "status": "ok",
            "batches_total": mapping_report["answer_parallel_tasks"],
            "batches_success": mapping_report["answer_parallel_tasks"],
            "batches_failed": 0,
            "answer_count": question_count,
            "mapped_question_count": question_count,
            "unmatched_trace_count": 0,
            "answer_pass_chunks": mapping_report["answer_pass_chunks"],
            "objective_pass_chunks": mapping_report["objective_pass_chunks"],
            "subjective_pass_chunks": mapping_report["subjective_pass_chunks"],
            "answer_repair_rounds": mapping_report["repair_rounds_used"],
            "repaired_questions_count": mapping_report["repaired_questions_count"],
            "score_conflict_count": 0,
            "answer_parallel_tasks": mapping_report["answer_parallel_tasks"],
            "saved_crop_count": mapping_report["answer_segment_saved_crop_count"],
            "saved_crop_dir": mapping_report["answer_segment_saved_crop_dir"],
            "elapsed_ms": round(rng.uniform(260000, 520000), 1),
        },
        {
            "stage": "student_profile",
            "status": "ok",
            "used_fallback": False,
            "elapsed_ms": round(rng.uniform(38000, 90000), 1),
        },
    ]

    request_payload = {
        "student_id": student_id,
        "input_mode": input_mode,
        "paper_image_count": paper_image_count,
        "paper_image_names": [f"paper_page_{idx + 1}.png" for idx in range(paper_image_count)],
        "answer_front_name": "answer_front.png",
        "answer_back_name": "answer_back.png",
    }
    process_payload = {
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "mock_mode": True,
        "stages": stages,
    }
    analysis_result = {
        "student_id": student_id,
        "input_mode": input_mode,
        "question_analysis": question_analysis,
        "structured_questions_full": structured_questions_full,
        "answer_trace": answer_trace,
        "answer_trace_display": answer_trace_display,
        "mapping_report": mapping_report,
        "student_profile": student_profile,
        "new_knowledge_points": [],
        "skill_alias_map": skill_alias_map,
        "warnings": [],
        "analysis_process": process_payload,
    }
    return {
        "meta": {
            "exported_at": finished_at.isoformat(timespec="seconds"),
            "schema_version": "analysis-export-v1",
        },
        "request": request_payload,
        "analysis_process": process_payload,
        "analysis_result": analysis_result,
    }
