# 前端重设计规范

## 设计目标

重构 testpaper 前端，核心原则：

1. **模式感知** — 前端根据用户选择的提取模式（标准 AI / MinerU）动态调整 UI
2. **阶段卡片** — 用语义阶段替代线性步骤条，支持灵活的子操作跳转
3. **现代活力风格** — 渐变色彩、大圆角、Pill 标签、卡片网格
4. **仿真数据驱动** — 先不做后端适配，用 mock data 完整展示所有交互

## 信息架构

### 导航结构

```
App Shell (左侧导航 + 主工作区)
├── 📊 工作台 (Dashboard)
├── 📁 项目 (ProjectList → ProjectWorkspace)
├── 📝 任务 (TaskCenter)
├── 📈 学情追踪 (Mastery)
└── 📋 报告中心 (ReportCenter)
```

左侧导航宽度 220px，带渐变 Logo，当前项高亮紫色背景。

### 页面清单

| 路由 | 页面 | 功能 |
|---|---|---|
| `/` | Dashboard | 概览统计、最近项目、快速入口 |
| `/projects` | ProjectList | 项目卡片网格、搜索筛选、新建 |
| `/projects/new` | ProjectCreate | 两步创建（信息+模式选择） |
| `/projects/:id` | ProjectWorkspace | 阶段卡片驱动的工作区 |
| `/projects/:id/review` | QuestionReview | 试题审查（全屏/侧边面板） |
| `/projects/:id/answers` | AnswerReview | 参考答案审查 |
| `/projects/:id/scoring` | ScoreReview | 评分审查 + 报告预览 |
| `/tasks` | TaskCenter | 分析任务列表 |
| `/tasks/:id` | TaskDetail | 任务详情/结果 |
| `/mastery` | MasteryHome | 学情概览 |
| `/mastery/:studentId` | StudentMastery | 单个学生掌握度详情 |
| `/reports` | ReportCenter | 报告列表 + 导出 |

## 项目创建流程（两步）

### Step 1：基本信息

- 表单字段：项目名称（必填）、学科（选填，预设：语文/数学/英语/物理/化学）、年级（选填）
- 简洁的表单卡片，居中布局
- "下一步" 按钮

### Step 2：选择提取方式

两张对比卡片：

```
┌──────────────────────┐  ┌──────────────────────┐
│ 🤖 标准 AI 提取       │  │ 🔬 MinerU 智能提取    │
│                      │  │                      │
│ AI 自动识别试卷图片中  │  │ 使用 MinerU OCR 引擎  │
│ 的试题和答案区域，提取 │  │ 精准解析，适合复杂排版 │
│ 后人工审查确认。      │  │ 、含图表的试卷。      │
│                      │  │                      │
│ 推荐 · 适合大多数场景  │  │ 需配置 MinerU 服务    │
│ [选择此方式]          │  │ [选择此方式]          │
└──────────────────────┘  └──────────────────────┘
```

选中后进入项目 workspace。默认推荐标准 AI 提取。

## 项目 Workspace（阶段卡片）

### 阶段定义

**标准 AI 提取模式：**

| 阶段 | 内容 | 可执行操作 |
|---|---|---|
| 一·准备 | 上传试卷图片、答案图片 | 上传文件、预览图片 |
| 二·提取与审查 | AI 提取试题、审查试题、生成答案、审查答案 | 审查试题、审查答案、重新提取 |
| 三·批改 | 上传答题卡、AI 评分 | 上传答题卡、查看评分、审查评分 |
| 四·报告 | 成绩汇总、报告导出 | 查看报告、导出 JSON/PDF |

**MinerU 智能提取模式：**

| 阶段 | 内容 | 可执行操作 |
|---|---|---|
| 一·准备 | 上传试卷图片 | 上传文件、预览图片 |
| 二·MinerU 提取 | Step1 解析 → Step2 LLM整理 → Step3 VLM配图 → Step4 保存 | 启动提取、查看进度 |
| 三·审查与确认 | 审查试题、生成答案、审查答案 | 审查试题、审查答案 |
| 四·批改 | 上传答题卡、AI 评分 | 上传答题卡、审查评分 |
| 五·报告 | 成绩汇总、报告导出 | 查看报告、导出 |

### 卡片的三种状态

- **已完成** — 绿色圆形勾、绿色左边框、灰色背景
- **进行中** — 紫色圆形数字、紫色左边框(2px)、淡紫背景、展开显示子操作按钮
- **待开始** — 灰色圆形数字、灰色边框、白色背景、不可点击

### 卡片交互

- 点击已完成阶段：折叠显示摘要
- 点击进行中阶段：展开显示子操作按钮和进度
- 待开始阶段不可交互
- 阶段之间通过操作自动推进（如上传完成→阶段一完成→阶段二自动高亮）

## 试题审查页

全屏双栏布局：

- 左侧：试卷页面图片（可翻页）
- 右侧：该页对应的试题列表，每道题可编辑
  - 题号、题型标签、题目内容 textarea
  - 配图缩略图（如有）
  - [确认] [标记有问题] 按钮
- 底部：整体操作栏 [全部确认] [返回项目]

## 仪表盘 (Dashboard)

顶部统计卡片行：
- 总项目数、进行中、已完成、学生数

下方两个区域：
- 左侧：最近项目列表（快捷进入）
- 右侧：快速操作入口（新建项目、查看报告、学情追踪）

## 视觉规范

### 色彩

```
主色: #6366f1 (Indigo)
主色浅: #f0f0ff
成功: #10b981
警告: #f59e0b
错误: #ef4444
中性文字: #111827 / #6b7280 / #9ca3af
背景: #fafbfc / #ffffff
边框: #e5e7eb
```

### 圆角

- 卡片：10px
- 按钮/输入框：8px
- 阶段圆标：50%（圆形）
- 标签/Pill：20px

### 阴影

- 卡片默认：无阴影 + 1px 边框
- 悬停/进行中卡片：0 0 0 2px rgba(99,102,241,0.15)
- 弹窗：0 4px 24px rgba(0,0,0,0.08)

### 字体

- 标题：600 weight, 13-16px
- 正文：400 weight, 13-14px
- 辅助文字：11-12px, #9ca3af
- 使用系统字体栈（-apple-system, "Segoe UI", sans-serif）

## 技术方案

### 技术栈

- React 18 + TypeScript
- Vite
- Tailwind CSS（替代 Ant Design，更灵活控制视觉）
- React Router v6
- Zustand（全局状态：auth、mock data、UI 状态）
- TanStack Query（数据获取缓存层，mock 阶段用占位）

### 组件树

```
App
├── AppShell (sidebar + outlet)
│   ├── Sidebar (logo, nav links, user)
│   └── <Outlet>
├── Dashboard
├── ProjectList
├── ProjectCreate (step 1 → step 2)
├── ProjectWorkspace
│   ├── ProjectHeader (title, mode badge, meta)
│   ├── PhaseCard × N (expandable)
│   │   └── PhaseActions (buttons, progress)
│   └── UploadZone (dragger, preview)
├── QuestionReview (dual-pane)
├── AnswerReview
├── ScoreReview
├── TaskCenter / TaskDetail
├── MasteryHome / StudentMastery
└── ReportCenter
```

### Mock Data 策略

- `src/mock/data.ts` — 所有仿真数据集中管理
- 包含：projects, questions, answers, students, scores, mastery, tasks
- Zustand mockStore 管理数据 — 前端操作直接修改内存中的数据
- 接口签名与后端 API 保持一致（`api/` 目录不变），调用 mockStore 而非 fetch
- 后端接入时只需修改 `api/` 目录下的实现：`mockStore.getProject()` → `apiClient.get(...)`

### 路由

```
/                         → Dashboard
/projects                 → ProjectList
/projects/new             → ProjectCreate
/projects/:id             → ProjectWorkspace
/projects/:id/review      → QuestionReview
/projects/:id/answers     → AnswerReview
/projects/:id/scoring     → ScoreReview
/tasks                    → TaskCenter
/tasks/:id                → TaskDetail
/mastery                  → MasteryHome
/mastery/:studentId       → StudentMastery
/reports                  → ReportCenter
```

## 待定事项

- 移动端响应式暂不考虑（教师主要桌面使用）
- 暗色模式暂不考虑
- 国际化暂不考虑（中文优先）
- 权限控制 UI 层暂不区分（mock 阶段所有用户显示完整界面）
