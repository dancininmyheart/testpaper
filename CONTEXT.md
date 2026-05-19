# CONTEXT — Testpaper Platform

## 项目定位

学生试卷分析与学情掌握度追踪系统。核心链路：答卷图像/数据输入 → AI 评分配置 → 学情诊断 → 掌握度时序建模 → 报告导出。

## 核心流程

```
Paper Project (试卷项目)
  ↓ 创建（draft）
  ↓ 上传试卷页 + 参考答案页
  ↓ 提取试题（extracting → review_questions）
  ↓ 人工审核试题（ready）
  ↓ 创建分析任务（analyzing）
  ↓ 每个学生一条 Job
      1. QuestionExtraction       — AI 从试卷页提取题目列表
      2. StudentAnswerRecognition — AI 从答卷页识别学生作答
      3. ReferenceAnswerExtract   — AI 从标答页提取参考答案
      4. ScoreRecognition         — AI 从判分页识别已有分数
      5. BlindDiagnosis           — AI 盲诊（不看标答，仅据题目分析步骤正确性）
      6. CorrectnessEvaluation    — AI 对照参考答案判对错
      7. Rating                   — AI 综合评分
      8. ProfileBuilding          — AI 生成学生画像（strengths/weaknesses）
  ↓（review_scores → completed）
  ↓ 掌握度写入
Mastery Engine
  ↓ 贝叶斯知识追踪更新
  ↓ 遗忘曲线衰减
  ↓ 分来源权重聚合
```

## 领域词汇表

### 聚合根与实体

| 术语 | 英文 | 说明 |
|------|------|------|
| 试卷项目 | Paper Project | 一次考试/练习的完整分析项目，包含试卷、参考答案、所有学生记录。状态机：draft → extracting → review_questions → ready → analyzing → review_scores → completed / error |
| 分析任务 | Analysis Job | 单个学生的分析作业。由 Intake API 创建，JobWorker 异步执行。状态机：queued → running → succeeded → failed / canceled |
| 试题 | QuestionItem | 从试卷中识别出的单道题目，含题号、类型、内容、满分、知识点标签 |
| 学生作答 | StudentAnswerItem | 学生答卷上的答题内容，含文本、选项、步骤、已给分数 |
| 参考答案 | ReferenceAnswerItem | 教师提供的标准答案，含最终答案、解题步骤、来源（uploaded / AI-extracted） |
| 评判结果 | JudgementItem | AI 对每道题的判分结论，含对错、得分、错误类型、评语、建议 |
| 学生画像 | StudentProfileDraft | AI 生成的学情报告概要，含优势、劣势、建议、知识点素养 |
| 试卷快照 | PaperProjectSnapshot | 已审核通过的试卷完整快照（questions + reference_answers + skill_alias_map），供后续所有学生分析管线使用 |

### 分析管线（Pipeline）

| 术语 | 英文 | 说明 |
|------|------|------|
| 管线上下文 | PipelineContext | 管线执行过程中的共享上下文，承载输入数据、中间产物和最终输出 |
| 管线编排器 | PipelineOrchestrator | 按序执行 stage，记录 stage 日志和 warning |
| 管线阶段 | Stage | 分析管线中的一个独立处理步骤，接收 PipelineContext 返回 StageResult |
| Stage 结果 | StageResult | 含 status（succeeded/partial/failed/skipped）、output、warnings、elapsed_ms |
| 输入模式 | input_mode | 学生答卷的输入方式（如 OCR 识别、结构化数据、预分题等） |
| AI Profile | vision_profile / text_profile | LLM 配置模板，指定 model、供应商、超时、重试等参数 |

### Pipeline 阶段详细

| 阶段 | 实现位置 | 输入 | 输出 |
|------|----------|------|------|
| QuestionExtraction | AI port / demo service | 试卷页面图片 | ExtractedQuestionSet（题目列表） |
| StudentAnswerRecognition | AI port / demo service | 答卷页面 + 题目列表 | RecognizedStudentAnswers（作答列表） |
| ReferenceAnswerExtract | AI port / demo service | 标答页面 + 题目列表 | ReferenceAnswerSet（参考答案列表） |
| ScoreRecognition | demo/stages/score_recognition.py | 判分页图片 | 已给分数列表 |
| BlindDiagnosis | demo/stages/blind_diagnosis.py | 题目 + 学生作答 | 盲诊结果（不看标答的诊断） |
| CorrectnessEvaluation | demo/stages/correctness.py | 作答 + 参考答案 | 正误评判 |
| Rating | demo service | 上述所有结果 | 综合评分 |
| ProfileBuilding | AI port / demo service | 题目 + 评判结果 | StudentProfileDraft（学生画像） |

### 掌握度（Mastery）

| 术语 | 英文 | 说明 |
|------|------|------|
| 掌握度 | Mastery | 学生对某个知识点的掌握水平，值域 [0.0, 1.0] |
| 技能 | Skill | 知识点/能力点标识，对应试题上的 skill_tags |
| 证据链 | Evidence Chain | 每次掌握度更新的来源记录，含时间戳、来源类型、得分 |
| 知识图谱 | Knowledge Graph | 知识点之间的关联关系，支持推导和推理 |
| 遗忘曲线 | Forgetting Curve | s ← s * exp(-lambda * delta_days)，按天数衰减掌握度 |
| 来源权重 | Source Weight | exam=1.0 > practice=0.75 > homework=0.55，不同来源的更新权重 |
| 掌握度等级 | Mastery Level | mastery值映射的等级标签（如 low/mid/high） |
| 风险等级 | Risk Level | 全班维度的知识点风险（low/mid/high），基于平均得分率和错误类型频率 |

### 试卷项目状态机

```
draft ──→ extracting ──→ review_questions ──→ ready ──→ analyzing ──→ review_scores ──→ completed
                               ↓                                            ↓
                             error                                       error
```

说明：
- draft：刚创建，未上传文件
- extracting：正在用 AI 提取试题和参考答案
- review_questions：提取完成，等待人工审核试题
- ready：试题已确认，可以创建分析任务
- analyzing：正在执行分析任务队列
- review_scores：所有分析任务完成，等待人工审核评分
- completed：审核通过，可查看报告
- error：处理过程中出现错误

### 分析任务状态机

```
queued ──→ running ──→ succeeded
                ↓
             failed / canceled
```

## 架构模式

## 框架统一

自 2026-05 起，项目已完成框架统一：

- **后端框架**：统一为 **Flask**（`backend/`）。原独立 demo http_server（端口 8010）和 mastery_api（端口 8000）的 API 功能已迁入 Flask Blueprints（`legacy`、`mastery`），单进程部署。
- **前端框架**：统一为 **React + TypeScript + Vite**（`frontend/`）。原 Flask Jinja2 原生 UI 已被替换，生产模式由 Flask serve React build 产物。
- **分析引擎**（`demo/service.py`、`demo/stages/`）和**掌握度引擎**（`mastery_engine.py`）保留为纯业务逻辑模块，无 Web 框架依赖。

**后端 — 六边形架构（DDD 分层）**

- `api/`（Flask Blueprints）— 入站适配器，处理 HTTP 请求
- `application/` — 应用服务层，编排领域逻辑
- `domain/` — 领域模型与端口接口（ports），零外部依赖
- `infrastructure/` — 出站适配器，实现端口接口（数据库、存储、AI）

**重构状态**

Phase 0-2 已完成（PipelineContext + PipelineOrchestrator + 4 个 extracted stage）。Phase 3 待办：将 DemoService.run 中剩余阶段逐步提取到独立 stage，最终完全替换 DemoService。

**前端 — React + TypeScript + Vite**
- 三个主视图：工作台（Workbench，任务创建）、任务中心（TaskCenter，状态监控）、报告中心（ReportCenter，报告查看）
- API 层：api/ 目录下按资源（auth、projects、tasks、mastery）拆分

## 边界与约定

- 所有 AI 调用通过 `domain/ports/ai.py` 中定义的 Protocol 接口进行，不直接依赖具体 LLM
- `llm_config.json` 配置多供应商 AI Profile，使用 openai_compatible 协议
- Mastery 引擎是独立组件（mastery_engine.py / mastery_api.py），通过磁盘 SQLite 与主应用交互
- 新开发优先使用 AnalysisWorkflow + PipelineOrchestrator，避免直接调用 DemoService
- **试卷项目状态写入必须通过 `backend/application/project_state_service.ProjectStateService.transition()`**，禁止直接调 `PaperRepository._update_project_status_internal`。合法转换矩阵在 `backend/domain/state_machine.py`，违法转换 raise `InvalidProjectTransition`。详见 ADR-0006
