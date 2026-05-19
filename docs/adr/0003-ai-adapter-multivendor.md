# ADR-0003: AI 适配器模式与多供应商支持

**状态**：已采纳 · **日期**：2025-03-10 · **提出者**：Architect

## 背景

AI 评分管线依赖大语言模型进行题目提取、作答识别、正误评判等任务。需要支持：
- 多个 LLM 供应商（OpenAI、Azure、本地模型等）
- 不同模型用于不同任务（视觉模型处理 OCR，文本模型处理评分）
- 运行时切换而不改代码

## 决策

采用 Profile + Protocol 双层抽象：

1. **AI Profile**（`llm_config.json`）— 声明式配置
   - 每个 profile 定义 model、runtime（langchain/legacy）、超时、重试
   - 支持任意数量的 profile（vision_profile / text_profile 分开指定）
   - 使用 openai_compatible 协议作为标准，同时支持原生 LangChain

2. **Protocol 接口**（`domain/ports/ai.py`）— 类型安全抽象
   - `QuestionExtractor` — 提取试题
   - `StudentAnswerRecognizer` — 识别作答
   - `ReferenceAnswerExtractor` — 提取参考答案
   - `AnswerJudge` — 评判正误
   - `ProfileBuilder` — 生成学生画像

## 后果

正面：
- 可在 `llm_config.json` 中添加新供应商，零代码修改
- 视觉模型和文本模型可来自不同供应商
- Protocol 接口明确、可 mock，方便测试

负面：
- openai_compatible 协议层对非 OpenAI API 可能有兼容性问题
- Profile 配置项分散在多个位置（config.py、llm_config.json、API 请求参数）
- 缺少 Profile 校验机制，配置错误在运行时才暴露
