# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Testpaper Platform — 学生试卷分析与学情掌握度追踪系统。支持答卷 OCR 识别、AI 评分、知识点诊断、时序掌握度建模、报告导出（JSON/PDF）。

## 启动方式

```bash
# 安装后端依赖
pip install -r backend/requirements.txt

# 全栈启动（Flask 提供后端 + React 前端构建产物）
python run_fullstack_dev.py --reload

# 或单独启动后端（需先构建前端）
python run_platform_server.py --host 0.0.0.0 --port 8020

# 前端单独开发（需要先启动后端）
cd frontend && npm run dev
```

## 构建前端

```bash
cd frontend && npm run build
```

## 测试

```bash
# 平台后端测试
python -m pytest tests/platform -q

# Demo 服务测试
python -m pytest test/test_demo_server_json_contract.py -q
python -m pytest test/test_demo_server_input_modes.py -q
```

## 架构

**后端（Python/Flask）— 六边形架构（DDD 分层），统一后端框架**

```
backend/
  api/routers/         # Flask Blueprints（auth, analysis, intake, mastery, legacy）
  application/         # 应用服务层
    workflows/         #   AnalysisWorkflow（新管线编排器，逐步替代 DemoService）
    analysis_service.py
    mastery_service.py
    auth_service.py
    job_worker.py      #   异步任务队列 worker
    legacy_api.py      #   DemoService 旧版 API 适配
  domain/              # 领域模型与端口接口
    models.py          #   JobStatus, UserRole
    ai_schemas.py      #   Pydantic schema（QuestionItem, JudgementItem 等）
    ports/ai.py        #   AI 适配器接口
  infrastructure/      # 基础设施
    db.py              #   SQLite 封装
    repositories.py    #   Repository 实现（User/Session/Analysis/MasteryEvent/Audit）
    storage.py         #   本地文件存储
    security.py        #   token/job_id 生成
    ai/                #   AI 适配器（langchain_adapter, profiles, chains）
  config.py            # AppSettings（环境变量驱动）
  app_context.py       # DI 容器：组装所有服务
  main.py              # Flask app factory（生产模式 serve React build）
```

Flask 在生产模式通过 `frontend/dist/` 提供 React SPA 构建产物，开发模式由 Vite dev server 代理 API 到 Flask。

**Demo 服务（旧版分析管线）**

`demo/service.py` (~347KB) 是核心分析引擎，包含完整的试卷分析链路。正在逐步将阶段提取到 `demo/stages/` 中的独立 stage 模块，通过 `PipelineOrchestrator` 编排。`AnalysisWorkflow`（`backend/application/workflows/`）逐渐接管各阶段，最终完全替换 DemoService。

重构阶段：Phase 0-2 已完成（PipelineContext + Orchestrator），Phase 3（DemoService.run阶段提取）待办。原独立 demo http_server（端口 8010）和 mastery_api（端口 8000）功能已迁入 Flask legacy/mastery Blueprint，统一通过 `run_platform_server.py`（端口 8020）提供。

**Mastery 引擎** — 时序掌握度分析
- 贝叶斯知识追踪（BKT）风格更新：`y = score/max_score`, `s <- clip(s + eta * r * (y - s))`
- 遗忘曲线：`s <- s * exp(-lambda * delta_days)`
- 来源权重：`exam=1.0 > practice=0.75 > homework=0.55`
- 存储表：`student_mastery`, `evidence_chain`, `knowledge_graph`

**前端（React + TypeScript + Vite）— 统一前端框架**

```
frontend/src/
  pages/            # 页面组件（Dashboard, ProjectList/Detail, TaskList/Detail, Mastery, ReportCenter, Login）
  api/              # API 客户端（auth, projects, tasks, mastery）
  stores/           # Zustand store（authStore, uiStore）
  hooks/            # React Query hooks（useTasks, useMastery, useProjects）
  components/       # 通用组件（AppLayout, ErrorBoundary, EmptyState）
  App.tsx           # 路由配置
  main.tsx          # 入口
```

**AI 配置** — `llm_config.json` 中定义 `openai_profiles`，支持多供应商（openai_compatible 协议），通过 `AIProfile` 类加载。每个 profile 配置 model、runtime（langchain/legacy）、超时、重试、结构化输出方式等。

**环境变量** — 复制 `.env.example` 为 `.env`，填入各 LLM 供应商 API key。

**Docker** — `docker-compose.yml` 和 `Dockerfile.backend` 提供容器化部署。

## Agent skills

### Issue tracker

Issues live as markdown files under `.scratch/<feature-slug>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

All five canonical role labels use their default name. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
