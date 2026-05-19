# Demo 使用说明

## 启动

```bash
python demo_server.py --host 127.0.0.1 --port 8010 --config llm_config.json --key-word key_word.json
```

调试可用 mock：

```bash
python demo_server.py --host 127.0.0.1 --port 8010 --mock
```

打开：`http://127.0.0.1:8010`

## 输入模式（新契约）

`POST /api/demo/run` 请求体：

- `student_id: string`
- `input_mode: "paper_answer_with_key" | "paper_answer_auto_key" | "paper_same_page" | "pre_split_questions"`
- `vision_profile: string`（可选，视觉模型 profile 名）
- `text_profile: string`（可选，LLM 模型 profile 名）
- `paper_files: [{name, data_url}]`（模式1/2必填）
- `answer_sheet_files: [{name, data_url}]`（模式1/2/4必填）
- `combined_files: [{name, data_url}]`（模式3必填）
- `answer_key_files: [{name, data_url}]`（模式1必填；模式3/4可选；模式2不传）
- `pre_split_questions: [{question_id, question_type?, problem_text?, problem_text_full?, sub_questions?, skill_tags?}]`（模式4必填）
- `selected_answer_blocks`（可选）

其中 `data_url` 支持：

- `data:image/*;base64,...`
- `data:application/pdf;base64,...`（服务端自动转图片页）

## 返回重点字段

- `answer_key_source: "uploaded" | "generated" | "none"`
- `reference_answers: [...]`
- `answer_trace[*].correctness`：
  - `by_answer_key`
  - `source`
  - `confidence`
  - `reason`
  - `conflict_with_teacher`
- `answer_trace[*].is_correct`：最终判定（标准答案优先，教师批改辅助）
