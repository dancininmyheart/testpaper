# 试卷智能分析平台二次重构开发文档

## 1. 背景与目标

当前项目已经验证了完整业务闭环：上传试卷/答题卡，识别题目与作答，结合标准答案判定对错，生成错因分析、学生画像和掌握度记录。但现有实现经历了 Demo 快速迭代，核心分析逻辑集中在 `demo/service.py`，平台 API、任务调度、模型调用、切题、判分、画像和导出之间耦合较重，后续继续扩展会明显增加维护成本。

二次重构的目标不是推翻已有能力，而是重写系统边界、数据模型和分析流水线，让项目形成可维护、可评测、可扩展的教学分析平台。

核心目标：

- 用清晰的数据模型承载“试卷-题目-答案块-学生作答-标准答案-判定-知识点”的关系。
- 用阶段化流水线替代单体大函数，每个阶段有明确输入、输出、状态和错误。
- 将 VLM/LLM、YOLO 切题、PDF 转图、报告生成等能力封装成可替换组件。
- 先完成稳定 v1，后续再扩展自动标准答案、批量分析、多模型策略和复杂修复。
- 建立样本集和指标，让效果优化可量化，而不是只依赖人工感觉。

## 2. 当前项目经验

### 2.1 应保留的能力

- 平台化任务模型：用户创建任务，后台异步执行，结果持久化，支持失败重试。
- 文件持久化：上传文件落地保存，分析任务只保存文件引用和元数据。
- 报告导出：JSON/PDF 导出对教师复核有价值，应继续保留。
- 掌握度闭环：分析结果最终沉淀为学生知识点掌握度事件。
- Mock 能力：用于演示、前端开发和接口联调，但必须和真实分析链路隔离。
- 结构化流程日志：`analysis_process.stages` 这类阶段日志应升级为一等模型。

### 2.2 应避免的问题

- 单个服务承担过多职责，尤其是 `demo/service.py` 式的长文件。
- 输入模式过多导致主流程发散，增加校验、分支和修复复杂度。
- 标准答案自动生成与上传标准答案混用，导致结果可信度不清晰。
- mock 默认开启，容易让演示效果和真实效果混淆。
- 模型配置和密钥混杂在本地 JSON 中，存在安全和部署风险。
- 缺少统一评测集，无法量化题目识别、答案映射和判分准确率。

## 3. v1 范围

### 3.1 v1 必做

v1 只支持最稳定、最容易验证的单学生单次分析链路：

```text
上传试卷 + 上传答题卡 + 上传标准答案
-> 文件标准化
-> 题目结构识别
-> 答题区域识别
-> 学生作答识别
-> 题目/作答/标准答案对齐
-> 判分与错因分析
-> 报告生成
-> 掌握度事件入库
```

必须交付：

- 登录与基础权限。
- 创建分析任务、查询任务、重试失败任务。
- 上传试卷、答题卡、标准答案。
- 异步分析任务。
- 分析结果 JSON 查询。
- 报告 PDF 导出。
- 掌握度事件写入和学生掌握度查询。
- 阶段级日志和错误可见。

### 3.2 v1 暂不做

以下能力后置，避免重构初期再次复杂化：

- 自动生成标准答案。
- 同页作答模式。
- 批量学生批改。
- 模板任务复用。
- 多模型动态对比。
- 人工框选答案块的完整工作流。
- 复杂多轮修复策略。
- 知识点图谱自动写回。

这些能力保留接口扩展空间，但不在 v1 主流程内实现。

## 4. 目标架构

### 4.1 分层结构

建议后端采用以下分层：

```text
backend/
  api/
    routers/
    schemas/
  application/
    commands/
    services/
    workflows/
  domain/
    models/
    policies/
    ports/
  infrastructure/
    db/
    repositories/
    storage/
    ai/
    documents/
  workers/
  config/
```

职责说明：

- `api`：HTTP 路由、请求响应 schema、认证依赖，不包含业务流程。
- `application`：用例编排，例如创建任务、执行分析、导出报告。
- `domain`：核心领域对象和业务规则，不依赖 Flask、SQLite 或具体模型供应商。
- `infrastructure`：数据库、文件存储、AI 客户端、PDF/图片处理、报告渲染。
- `workers`：后台任务执行器，只负责取任务、执行工作流、写回状态。
- `config`：环境变量配置和运行时开关。

### 4.2 核心模块

#### 任务平台模块

负责分析任务生命周期：

- 创建任务。
- 保存上传文件。
- 任务排队。
- 任务执行。
- 状态查询。
- 失败重试。
- 结果查询和导出。

任务状态：

```text
created -> queued -> running -> succeeded
                         |-> failed
                         |-> canceled
```

v1 可不实现主动取消，但数据库状态预留 `canceled`。

#### 文件标准化模块

负责把上传文件统一转为可分析资源：

- 支持图片和 PDF。
- PDF 按页转图片。
- 保存标准化后的页面图片。
- 记录页码、宽高、DPI、来源文件。

输出 `DocumentPage`，供后续阶段使用。

#### 题目结构识别模块

负责从试卷页面提取题目结构：

- 题号。
- 题型。
- 题干。
- 小题结构。
- 分值。
- 页码范围。
- 候选知识点。

输出 `QuestionSet`。

#### 答案块检测模块

负责从答题卡中检测作答区域：

- 可先复用 `major_seg_tool` 的 YOLO 权重。
- 检测结果统一转为 `AnswerBlock`。
- 对低置信度块保留警告，不直接丢弃。

输出 `AnswerBlock[]`。

#### 学生作答识别模块

负责从答案块中识别学生作答：

- 客观题选项。
- 填空题文本。
- 主观题步骤和最终答案。
- 教师批改痕迹和分数线索。

输出 `StudentAnswer[]`。

#### 标准答案解析模块

v1 只支持上传标准答案：

- 从标准答案文件中提取每题答案。
- 标准答案必须带来源和置信度。
- 如果解析不完整，报告必须显示缺失项。

输出 `ReferenceAnswer[]`。

#### 对齐与判定模块

负责建立核心关系：

```text
Question <-> StudentAnswer <-> ReferenceAnswer
```

然后执行：

- 题号匹配。
- 小题匹配。
- 分数一致性检查。
- 标准答案判定。
- 教师批改信号交叉验证。
- 错因分析。

输出 `Judgement[]` 和 `AlignmentReport`。

#### 学生画像与掌握度模块

负责将判定结果转换为可沉淀事件：

- 每道题生成知识点证据。
- 每个知识点生成掌握度更新事件。
- 学生报告基于事件和最近分析结果生成。

v1 保留现有掌握度更新公式，但把输入事件 schema 固定下来。

## 5. 核心领域模型

### 5.1 AnalysisJob

表示一次分析任务。

关键字段：

- `id`
- `student_id`
- `status`
- `input_mode`
- `created_by`
- `created_at`
- `updated_at`
- `started_at`
- `finished_at`
- `error_code`
- `error_message`

v1 固定 `input_mode = paper_answer_with_key`。

### 5.2 AnalysisArtifact

表示任务中的文件或中间产物。

关键字段：

- `id`
- `job_id`
- `kind`
- `original_name`
- `storage_path`
- `mime_type`
- `page_index`
- `metadata`

`kind` 可取：

- `paper_upload`
- `answer_sheet_upload`
- `answer_key_upload`
- `paper_page`
- `answer_sheet_page`
- `answer_key_page`
- `debug_json`
- `report_pdf`

### 5.3 Question

表示试卷题目。

关键字段：

- `id`
- `job_id`
- `question_no`
- `parent_question_no`
- `sub_question_no`
- `question_type`
- `content`
- `max_score`
- `page_index`
- `skill_tags`
- `confidence`

### 5.4 AnswerBlock

表示答题卡上的一个检测区域。

关键字段：

- `id`
- `job_id`
- `page_index`
- `bbox`
- `block_type`
- `detector`
- `confidence`
- `image_artifact_id`

### 5.5 StudentAnswer

表示学生某题作答。

关键字段：

- `id`
- `job_id`
- `question_id`
- `answer_block_id`
- `answer_text`
- `steps`
- `selected_option`
- `filled_value`
- `score`
- `max_score`
- `is_correct_by_teacher`
- `recognition_confidence`
- `warnings`

### 5.6 ReferenceAnswer

表示标准答案。

关键字段：

- `id`
- `job_id`
- `question_id`
- `answer_text`
- `final_answer`
- `steps`
- `source`
- `confidence`

v1 固定 `source = uploaded`。

### 5.7 Judgement

表示最终判定。

关键字段：

- `id`
- `job_id`
- `question_id`
- `student_answer_id`
- `reference_answer_id`
- `is_correct`
- `score`
- `max_score`
- `error_type`
- `reason`
- `suggestion`
- `confidence`
- `conflict_flags`

### 5.8 AnalysisStageRun

表示阶段日志。

关键字段：

- `id`
- `job_id`
- `stage_name`
- `status`
- `started_at`
- `finished_at`
- `elapsed_ms`
- `input_summary`
- `output_summary`
- `error_message`
- `warnings`

阶段状态：

```text
pending | running | succeeded | partial | failed | skipped
```

## 6. 分析流水线设计

### 6.1 阶段定义

v1 工作流固定为：

```text
01_validate_input
02_normalize_documents
03_extract_questions
04_detect_answer_blocks
05_recognize_student_answers
06_extract_reference_answers
07_align_answers
08_judge_answers
09_build_student_profile
10_persist_mastery_events
11_build_report
```

每个阶段必须满足：

- 输入来自数据库或上个阶段产物。
- 输出写入数据库或 artifact。
- 失败时写入明确 `error_code` 和 `error_message`。
- 可重复执行；重试任务时允许覆盖本任务的中间产物。

### 6.2 阶段接口

统一阶段接口：

```python
class AnalysisStage(Protocol):
    name: str

    def run(self, context: AnalysisContext) -> StageResult:
        ...
```

`AnalysisContext` 包含：

- `job_id`
- `settings`
- `repositories`
- `storage`
- `ai_clients`
- `stage_logger`

`StageResult` 包含：

- `status`
- `output_summary`
- `warnings`
- `artifacts`

这样做可以让每个阶段独立测试，也方便后续替换实现。

### 6.3 错误处理原则

- 输入缺失、格式错误：任务失败，不继续执行。
- 单页识别失败：阶段 `partial`，继续处理其他页，并在报告中展示。
- 标准答案缺失：对应题目判定为 `unjudged`，不伪造结果。
- 答案块未匹配：进入 `AlignmentReport.unmatched_blocks`。
- 题目无学生答案：生成空答案记录，状态为 `missing_answer`。
- 模型调用失败：按配置重试，仍失败则记录阶段失败或 partial。

## 7. API 设计

### 7.1 认证

```http
POST /api/v1/auth/login
POST /api/v1/auth/logout
GET  /api/v1/auth/me
```

保持现有能力，后续可接入真实学校账号系统。

### 7.2 分析任务

```http
POST /api/v1/analysis/jobs
GET  /api/v1/analysis/jobs
GET  /api/v1/analysis/jobs/{job_id}
POST /api/v1/analysis/jobs/{job_id}/retry
GET  /api/v1/analysis/jobs/{job_id}/stages
```

创建任务使用 `multipart/form-data`：

- `student_id`
- `paper_files[]`
- `answer_sheet_files[]`
- `answer_key_files[]`

v1 不暴露 `input_mode` 选择，后端固定为 `paper_answer_with_key`。

### 7.3 分析结果

```http
GET /api/v1/analysis/jobs/{job_id}/result
GET /api/v1/analysis/jobs/{job_id}/report.pdf
GET /api/v1/analysis/jobs/{job_id}/export.json
```

结果 JSON 顶层结构：

```json
{
  "job": {},
  "questions": [],
  "answer_blocks": [],
  "student_answers": [],
  "reference_answers": [],
  "judgements": [],
  "alignment_report": {},
  "student_profile": {},
  "stages": [],
  "warnings": []
}
```

### 7.4 掌握度

```http
POST /api/v1/mastery/events:ingest
GET  /api/v1/students/{student_id}/mastery
GET  /api/v1/students/{student_id}/report
GET  /api/v1/exams/{paper_id}/group-summary
```

v1 可保留现有接口，但内部事件 schema 要和 `Judgement` 对齐。

## 8. 存储设计

### 8.1 数据库

v1 可继续使用 SQLite，降低迁移成本。表按领域对象拆分：

- `users`
- `sessions`
- `analysis_jobs`
- `analysis_artifacts`
- `analysis_stage_runs`
- `questions`
- `answer_blocks`
- `student_answers`
- `reference_answers`
- `judgements`
- `mastery_events`
- `audit_logs`

后续如需多人并发和生产部署，可迁移到 PostgreSQL；领域层和仓储接口不应依赖 SQLite 细节。

### 8.2 文件存储

文件路径建议统一：

```text
outputs/platform/jobs/{job_id}/
  uploads/
  pages/
  blocks/
  debug/
  reports/
```

数据库只保存相对路径和元数据，避免业务表存储大文件内容。

## 9. AI 与模型调用设计

### 9.1 端口接口

将模型能力抽象为领域端口：

```python
class QuestionExtractor(Protocol): ...
class AnswerBlockDetector(Protocol): ...
class StudentAnswerRecognizer(Protocol): ...
class ReferenceAnswerExtractor(Protocol): ...
class AnswerJudge(Protocol): ...
class ProfileBuilder(Protocol): ...
```

基础设施层提供实现：

- `YoloAnswerBlockDetector`
- `VlmQuestionExtractor`
- `VlmStudentAnswerRecognizer`
- `LlmReferenceAnswerExtractor`
- `LlmAnswerJudge`
- `RuleBasedProfileBuilder`
- `LlmProfileBuilder`
- `Mock*` 系列实现

### 9.2 配置原则

- 密钥只从环境变量读取。
- `llm_config.json` 只保存非敏感配置。
- mock、dev、prod 使用不同配置文件或环境变量。
- 默认运行模式应是真实链路或显式失败，不应默认 mock。

推荐环境变量：

```text
APP_ENV=dev|test|prod
ANALYSIS_MODE=real|mock
VISION_PROFILE=...
TEXT_PROFILE=...
OPENAI_API_KEY=...
ARK_API_KEY=...
DASHSCOPE_API_KEY=...
MINERU_API_KEY=...
```

## 10. 前端重构方向

v1 前端保留三个主页面：

- 工作台：创建任务、上传文件、提交分析。
- 任务中心：查看状态、阶段日志、失败原因、重试。
- 报告中心：查看题目、作答、判定、错因、掌握度和导出。

前端不应理解复杂分析细节，只消费后端结构化结果：

- 用 `stages` 展示进度。
- 用 `alignment_report` 展示未匹配和冲突。
- 用 `judgements` 展示每题结果。
- 用 `student_profile` 展示学生画像。

## 11. 测试与评测

### 11.1 单元测试

必须覆盖：

- 输入校验。
- 文件标准化。
- 题号规范化。
- 答案块 bbox 裁剪。
- 题目/答案/标准答案对齐。
- 判定结果合并规则。
- 掌握度事件生成。
- 失败重试。

### 11.2 集成测试

必须覆盖：

- 创建任务到成功完成。
- 创建任务到阶段失败。
- 上传缺失标准答案失败。
- 报告 JSON/PDF 导出。
- 掌握度事件写入。

### 11.3 效果评测

建立 `evaluation/` 样本集：

```text
evaluation/
  samples/
    case_001/
      paper.pdf
      answer_sheet.pdf
      answer_key.pdf
      expected.json
```

核心指标：

- 题目识别完整率。
- 答案块检测召回率。
- 题号映射准确率。
- 标准答案抽取准确率。
- 判分一致率。
- 错因人工认可率。
- 端到端成功率。

每次模型、提示词或切题策略变更，都应跑评测集。

## 12. 迁移路线

### 阶段一：搭建新骨架

- 建立新目录结构。
- 定义领域模型和仓储接口。
- 保留现有 Flask 平台入口，逐步迁移 API。
- 建立新任务表和阶段日志表。
- 实现 mock 版完整工作流。

目标：不依赖真实模型即可跑通新架构闭环。

### 阶段二：迁移文件与任务平台

- 替换现有任务创建和文件存储逻辑。
- 引入 `AnalysisArtifact`。
- 后台 Worker 调用新 `AnalysisWorkflow`。
- 保留旧 `/api/demo/*` 为兼容接口，但不再作为新功能入口。

目标：平台主流程进入新架构。

### 阶段三：迁移分析阶段

按顺序替换旧 `DemoService` 能力：

1. 文件标准化。
2. 题目识别。
3. 答案块检测。
4. 学生作答识别。
5. 标准答案解析。
6. 对齐与判定。
7. 学生画像。
8. 报告导出。

每迁移一个阶段，就增加对应测试和评测指标。

### 阶段四：接入掌握度

- 将 `Judgement` 转换为掌握度事件。
- 保留现有掌握度公式。
- 固定事件 schema。
- 支持按学生和试卷查询结果。

目标：分析结果可稳定进入长期画像。

### 阶段五：清理旧实现

- 将 `demo/service.py` 降级为 legacy adapter。
- 删除无用 Demo HTML 和临时脚本。
- 移除明文密钥配置。
- 固化部署文档和运行方式。

目标：主系统不再依赖旧 Demo 大文件。

## 13. 验收标准

v1 重构完成的标准：

- 单学生“试卷 + 答题卡 + 标准答案”链路稳定跑通。
- 所有阶段都有结构化日志。
- 任意阶段失败时，用户能看到明确失败原因。
- 结果 JSON 能完整表达题目、作答、标准答案、判定和画像。
- 报告 PDF 可导出。
- 掌握度事件可入库并查询。
- mock 与真实模式显式区分。
- 密钥不再提交到配置文件。
- 核心模块单测覆盖主要业务规则。
- 至少有一组端到端评测样本。

## 14. 设计原则落地

- KISS：v1 只做最稳定链路，不复刻所有输入模式。
- YAGNI：批量、自动答案、模板复用、多模型对比后置。
- SRP：每个阶段只负责一个明确任务。
- OCP：通过端口接口替换模型和检测器，而不是修改主流程。
- ISP：AI 能力拆为小接口，避免一个“大模型服务”包办所有任务。
- DIP：应用层依赖抽象端口，基础设施层提供具体实现。
- DRY：文件标准化、阶段日志、模型调用、错误处理使用统一组件。

## 15. 推荐的近期任务清单

1. 创建新领域模型和数据库迁移草案。
2. 实现 `AnalysisWorkflow` 和 `AnalysisStage` 基础框架。
3. 用 mock 阶段跑通完整 v1 输出结构。
4. 将现有任务 API 接到新工作流。
5. 迁移文件标准化和报告导出。
6. 接入 YOLO 答案块检测。
7. 接入题目识别和作答识别。
8. 接入标准答案解析和判定。
9. 建立第一版评测样本集。
10. 清理明文密钥和 legacy 入口默认暴露。
