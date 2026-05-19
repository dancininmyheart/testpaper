# Mastery MVP（P0 闭环）

## 1. 导入记录并更新掌握度
```bash
python mastery_engine.py --db mastery.db --input mvp_records_example.json
```

## 2. 启动查询 API
```bash
python mastery_api.py --db mastery.db --host 127.0.0.1 --port 8000
```

## 3. 可用接口
- `GET /student/{id}/mastery`
- `GET /student/{id}/report?range=30d`
- `GET /exam/{paper_id}/analysis`
- `GET /health`

## 4. 统一记录 schema（输入）
每条记录最少字段：
- `student_id`
- `timestamp`（ISO8601）
- `problem_id`
- `source_type`：`exam|practice|homework`

推荐字段：
- `problem_text`
- `student_answer`
- `score` + `max_score`（或 `correct`）
- `source_id`（如试卷 id）
- `skill_id`
- `evidence`（LLM 输出结构化诊断）

`evidence` 固定 JSON：
```json
{
  "skill_tags": ["eq.method.linear_transpose"],
  "error_type": "concept",
  "method_correctness": 0.4,
  "solution_completeness": 0.6,
  "confidence": 0.85,
  "notes": "可选说明"
}
```

## 5. 规则说明
- 观测值：`y = score/max_score`（无分数时回退到 correct）
- 可靠性：`r = source_weight * confidence * (0.5 + 0.5*method_correctness)`
- 更新：`s <- clip(s + eta * r * (y - s))`
- 遗忘：`s <- s * exp(-lambda * delta_days)`
- 来源权重默认：`exam=1.0 > practice=0.75 > homework=0.55`

## 6. 存储表
- `student_mastery(student_id, skill_id, mastery, last_update, uncertainty)`
- `evidence_chain(student_id, event_time, source_type, source_id, problem_id, skill_id, s_before, s_after, evidence_json, ...)`
- `knowledge_graph(skill_id_from, skill_id_to, confidence, source)`
