# ADR-0001: 六边形架构与领域驱动设计分层

**状态**：已采纳 · **日期**：2025-01-15 · **提出者**：Architect

## 背景

后端最初是单体 Flask 应用，所有逻辑混合在路由和 DemoService 中。随着 AI 评分管线复杂度上升，需要清晰的架构边界来支持独立测试、AI 供应商切换和逐步重构。

## 决策

采用六边形架构（Ports & Adapters）配合领域驱动设计的分层原则：

```
api/             ← 入站适配器（Flask Blueprints）
application/     ← 应用服务层
domain/           ← 领域模型与端口接口
infrastructure/  ← 出站适配器
```

关键约束：

- `domain/` 零外部依赖，只包含纯 Python 类型和 Protocol
- 所有外部交互（AI、数据库、文件系统）通过 `domain/ports/` 中定义的 Protocol 接口进行
- `application/` 编排领域逻辑，不直接依赖基础设施实现
- `infrastructure/` 实现端口接口，依赖倒置

## 后果

正面：
- AI 适配器可独立替换（LangChain ↔ 原生 API）
- 领域逻辑可脱离 Flask 测试
- 新开发者可通过目录结构理解架构

负面：
- 小功能需要跨 3-4 层
- DTO 转换开销
- 团队需要理解依赖倒置原则

## 备选方案

- **扁平 Flask**：路由直接调用 DB — 拒绝，不可测试
- **MVC**：Django 风格 — 拒绝，模型层无法隔离外部依赖
