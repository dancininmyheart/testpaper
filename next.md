# 分析链路平衡提速优化方案

## Summary

目标是在不牺牲主要判题质量的前提下，把当前约 39 分钟的链路压到可接受范围。采用“平衡提速”：保留标准答案判定、错因诊断和学生画像，但把最慢的大模型阶段拆分、并行、按需执行，并修正日志里会误导耗时判断的问题。

重点处理两条答案路径：上传标准答案走快路径；没有标准答案时，自动生成参考答案改成分块并行和按需生成。

## Key Changes

- **新增 Gemini + DeepSeek 快速 profile**
  - 新增 `openai_vision_gemini_3_flash_fast` 和 `openai_text_deepseek_v4_pro_fast`。
  - 保留原 profile 不动，新 profile 关闭 `question_full_discovery_enabled`、`max_repair_rounds`、`answer_trace_save_debug_json`。
  - 文本 profile 使用更大的 chunk：`question_chunk_size=12`、`score_chunk_size=6`、`answer_chunk_size=12`，并把并发控制在 8 左右，避免 30 并发触发供应商排队或限流。
  - 视觉 fast profile 的 `text_profile` 指向新的 DeepSeek fast profile，用户下拉选择视觉 fast 后自动联动文本 fast。

- **优化参考答案阶段**
  - 上传标准答案时，继续优先解析上传答案，不触发自动生成。
  - 无标准答案时，`reference_answer_generate` 改为按题目分块并行生成，而不是一次性处理 27 题。
  - 自动生成只对“需要判定的题目”生成：有作答信号、进入前端展示、或后续判题需要的题；明显未作答且无诊断价值的题跳过。
  - 阶段日志增加 `chunk_count`、`generated_question_count`、`skipped_question_count`，避免再只看到一个 23 分钟的大阶段。

- **压缩和拆分作答结构化**
  - 当前 `answer_trace_structuring_alignment` 一次处理 13 个 raw item，耗时约 7.4 分钟；改成按 raw item/page 或题号范围分块并行。
  - 每个分块只携带对应候选题上下文，而不是全部 27 题上下文。
  - 保留现有合并后的结构化 schema，最终仍输出同样的 `answers`，下游映射逻辑不变。
  - 如果分块结构化失败，只对失败块走 legacy fallback，不回退整批。

- **减少知识点标注耗时**
  - 新增配置开关 `knowledge_tagging_mode`，默认 fast profile 使用 `fast`。
  - `fast` 模式跳过“知识点组粗筛 + 精筛”双 LLM 调用中的粗筛失败重试，只做一次精简候选匹配。
  - 对已有 `skill_tags` 的题目跳过 LLM 标注。
  - 如果知识点标注失败，用规则/空标签兜底，不阻塞判题链路。

- **按需诊断和画像**
  - 错因诊断继续只分析错误、扣分、冲突、低置信题；再增加上限配置，例如 `blind_diagnosis_max_items=12`，超过时优先诊断低分题和冲突题。
  - 学生画像优先使用规则画像；LLM 画像只生成摘要、薄弱项措辞和学习建议，不再要求它重算完整能力结构。
  - 新增 `profile_mode=rule_first`，fast profile 默认启用；LLM 失败时直接返回规则画像，不影响主结果。

- **修正耗时日志**
  - `new_knowledge_points` 当前实际很快，但因为等待 `reference_future` 后才记录，日志显示成 23 分钟；改为 future 完成后立即记录，或分别记录 `actual_elapsed_ms` 和 `wait_elapsed_ms`。
  - 所有并行阶段增加 `started_at`、`finished_at`、`actual_elapsed_ms`、`wait_elapsed_ms`，便于判断真瓶颈。

## Public Interfaces

- 前端请求和结果 JSON 保持兼容。
- 模型下拉栏新增 fast profile，不替换旧 profile。
- `analysis_process.stages` 增加若干观测字段，但不删除旧字段。
- `mapping_report` 可增加：
  - `reference_generate_chunk_count`
  - `reference_generate_skipped_count`
  - `answer_structuring_chunk_count`
  - `blind_diagnosis_target_count`
  - `profile_mode`

## Test Plan

- 单元测试：
  - fast profile 能被 `/api/demo/model-options` 返回，并能联动推荐文本 profile。
  - 参考答案生成分块后仍能合并为原 `reference_answers` schema。
  - 作答结构化分块后仍能被 `_normalize_answer_item` 和映射刷新逻辑消费。
  - 诊断筛选和上限策略优先保留错误、扣分、冲突、低置信题。
  - `new_knowledge_points` 日志的实际耗时不再被等待参考答案污染。

- 集成测试：
  - fake LLM 跑通 `paper_answer_with_key`，确认上传标准答案路径不触发自动生成。
  - fake LLM 跑通 `paper_answer_auto_key`，确认参考答案按 chunk 并行生成并合并。
  - 验证结果字段 `answer_trace`、`structured_questions_full`、`student_profile`、`analysis_process.stages` 保持兼容。

- 回归测试：
  - `python -m pytest test\test_demo_server_json_contract.py -q`
  - `python -m pytest test\test_demo_server_input_modes.py -q`
  - `python -m pytest tests\platform -q`

- 真实模型验收：
  - 用你这次同一组输入分别跑原 profile 和 fast profile。
  - 成功标准：总耗时明显下降；标准答案判定题数不减少；错题诊断和画像仍可用于页面展示。
  - 重点观察：`reference_answer`、`answer_trace structuring`、`blind_step_analysis`、`student_profile` 四个阶段耗时。

## Assumptions

- 默认选择“平衡提速”，不做极限跳过。
- 上传标准答案和自动生成标准答案两种路径都要优化。
- 不删除旧 profile，不删除 legacy fallback。
- 当前直接在 `llm_config.json` 写密钥可以继续用，但后续提交代码前应避免泄露真实 key。
