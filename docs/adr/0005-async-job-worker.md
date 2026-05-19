# ADR-0005: 异步任务队列与 Job Worker

**状态**：已采纳 · **日期**：2025-03-15 · **提出者**：Architect

## 背景

学生试卷分析涉及多次 AI 调用（题目提取、作答识别、评分、画像生成），单次分析耗时可达数分钟。同步阻塞 API 不可接受。

## 决策

采用**数据库轮询 + 进程内 Worker**模式，而非引入外部消息队列：

```
POST /api/jobs → 创建 job，状态 = queued
                 ↓
JobWorker（后台线程轮询）
    ↓ 读取 queued job
    ↓ AnalysisWorkflow.run（或 DemoService.run）
    ↓ 更新状态为 succeeded / failed
                 ↓
GET /api/jobs/:id → 返回当前状态
```

关键设计：
- Job 状态存在 SQLite（queued → running → succeeded / failed / canceled）
- Worker 是主进程中的后台线程，零额外基础设施
- 重试机制：失败时记录 `error_message` 和 `attempt_count`
- 通过 `JobStatus` 枚举提供类型安全的状态转换

## 后果

正面：
- 无需 Redis/RabbitMQ 等外部依赖
- 进程内 Worker 简化开发和部署
- 状态可轮询，前端简化实现

负面：
- 进程内 Worker 在应用重启时丢失队列
- 单进程无法处理并行 Worker 和水平扩展
- 长时间运行的任务阻塞进程退出
- 数据库轮询增加 SQLite 读压力
