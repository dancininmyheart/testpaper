# ADR-0002: 渐进式管线重构（DemoService → PipelineOrchestrator）

**状态**：进行中 · **日期**：2025-06-01 · **提出者**：Architect

## 背景

`demo/service.py`（~347KB）是核心分析引擎，包含完整的试卷分析链路。该文件耦合度过高，难以单独测试和维护。但全量重写风险太大，需要可渐进执行的迁移路径。

## 决策

采用**绞杀者模式**（Strangler Fig），分 4 个阶段逐步将 DemoService.run 替换为独立 stage：

```
Phase 0 — PipelineContext + StageResult 数据类型
Phase 1 — PipelineOrchestrator 编排器
Phase 2 — 提取前 4 个 stage（new_knowledge_points、blind_diagnosis、score_recognition、correctness）
Phase 3 — 提取剩余 stage，移除 DemoService.run 调用
```

AnalysisWorkflow 作为新管线的入口，通过 PipelineOrchestrator 运行已提取的 stage，尚未提取的经由 LegacyAnalysisRunner 委托给 DemoService。

## 后果

正面：
- 逐步迁移，风险可控
- 每个 stage 可独立测试
- 新系统（AnalysisWorkflow）和旧系统（DemoService）共存期可回滚
- 已完成阶段不受后续重构影响

负面：
- Phase 3 待办，迁移尚未完成，新旧代码并存
- LegacyAnalysisRunner 适配器增加了间接层
- 需要维护两套管线入口（DemoService.run 和 AnalysisWorkflow.run）

## 阶段状态

- Phase 0 ✅ — PipelineContext + StageResult
- Phase 1 ✅ — PipelineOrchestrator
- Phase 2 ✅ — 4 个 stage 已提取
- Phase 3 ⏳ — 待办
