# Frontend Redesign: 混合式布局 + 分步工作流

## 背景

当前前端采用 Ant Design 标准布局（左侧导航 + 全页内容），存在布局结构混乱、交互流程不便、中间结果展示不直观的问题。需要在保持现有技术栈（React + TypeScript + Vite + Ant Design）的前提下重新设计布局和交互。

## 布局结构

### 整体框架（混合式）

```
┌──────────────────────────────────────────────────┐
│  顶栏：Logo + 用户信息                            │
├──────┬───────────────────────────────────────────┤
│  🏠  │  步骤条（药丸形标签，当前步骤高亮）            │
│  📋  ├───────────────────────────────────────────┤
│  📊  │  主内容区（根据当前步骤动态渲染）              │
│  📈  │    - 上传/处理时：进度 + 阶段日志             │
│      │    - 审查时：中间结果表格 + 确认按钮           │
│  ⚙  │                                            │
├──────┴───────────────────────────────────────────┤
│  底部浮动进度条（显示后台任务进度）                    │
└──────────────────────────────────────────────────┘
```

### 各区域规格

- **顶栏**：高度 48px，深色背景（#1a1a2e 或 #001529），左侧 Logo + 产品名，右侧用户信息
- **侧栏**：宽度 56px，仅图标，悬停显示文字标签。激活项高亮。底部放置设置图标
- **步骤条**：高度 44px，浅灰背景，使用 Ant Design Steps 组件但定制为紧凑药丸形
- **主内容区**：flex:1，padding 20px，白底，溢出滚动
- **底部进度条**：高度 40px，深色（#115f63），始终固定在底部。显示旋转动画 + 进度文字 + 百分比 + 任务数。无任务时隐藏

## 页面设计

### 1. 项目列表页

- **筛选标签**：全部 | 进行中 | 已完成（Ant Design Tabs 或 Segmented）
- **项目卡片**：Ant Design Card，每张显示：
  - 标题、科目、年级
  - 进度条（根据状态 draft=0% / extracting/review=动态 / completed=100%）
  - 状态标签（草稿/进行中/已完成）
- **新建按钮**：右上角，Button type="primary"
- **空状态**：Empty 组件 + "创建第一个项目"按钮
- **错误状态**：每个 Card 可显示 error_message 在底部

### 2. 项目详情页（核心）

采用分步工作流，每一步对应一个项目状态：

| 步骤 | 项目状态 | 组件 | 说明 |
|------|----------|------|------|
| 上传文件 | `draft`, `error` | 文件上传 Dragger × 2 | 试卷 + 可选答案 |
| 提取试题 | `extracting` | 进度条 + 阶段日志 | 实时显示处理进度 |
| 审查试题 | `review_questions` | 表格（可编辑） | 核对 AI 提取的试题 |
| 审查答案 | `review_answers` | 表格（只读） | 核对 AI 生成的参考答案 |
| 识别答题卡 | `ready` → `recognizing` | 上传 + 进度 | 上传答题卡 + 识别 |
| 审查评分 | `review_scores` | 统计 + 表格 | 核对评分与错因分析 |
| 完成 | `completed` | 完成页 | 报告查看 + 下载 |

#### 上传文件（draft）

- 两个 Dragger 组件并排：试卷文件、标准答案（可选）
- 文件列表显示已选文件
- 操作按钮组：[上传文件] [开始提取试题与答案]
- 先上传再提取，两个独立操作
- 验证：无试卷文件时禁用提取按钮并提示

#### 处理中进度（extracting / generating_answers / recognizing）

- 居中布局：旋转图标 + 标题 + 描述文字
- Progress 组件（percent=100，status="active"）
- 阶段日志表格（Ant Design Table）：
  - 阶段名、状态（✅/🔄/⏳）、耗时
  - 实时追加新行（通过轮询）
- 底部浮动进度条同步显示

#### 审查试题（review_questions）

- Card 标题：审查 AI 提取的试题 + 题目计数 Tag
- Table 列：题号 | 题型 | 内容 | 配图按钮 | 满分 | 知识点
- 编辑模式切换：点击"编辑试题"按钮，表格单元格变为 Input/Select
- 确认按钮："确认试题无误"，调用 approve-questions API
- 查看原图按钮：打开图片 Modal

#### 审查答案（review_answers）

- Card 标题：审查 AI 生成的参考答案
- Table 列：题号 | 题型 | 内容 | 参考答案 | 详细步骤 | 来源
- 确认按钮："确认参考答案无误"，调用 stage/approve-answers API
- 重新生成按钮（可选）

#### 上传答题卡（ready / review_recognition）

- 单学生模式：学生 ID 输入 + 文件上传 + [开始识别] 按钮
- 批量模式：折叠面板（details），学生 ID 列表文本框 + 文件上传 + [批量提交]
- 点击后状态变为 `recognizing`，显示处理中进度

#### 审查评分（review_scores）

- 统计卡片行：学生 | 总分 | 正确率 | 已作答 | 题目数
- 答题详情 Table：题号 | 状态 | 得分/满分 | 正确率条 | 错因 Tag | 说明
- 正确率条：彩色进度条（绿 ≥70% / 黄 ≥40% / 红 <40%）
- 错因标签：概念错误(红) / 计算失误(橙) / 审题遗漏 / 思路偏差 / 其他(蓝)
- 确认按钮："确认评分，生成报告"
- 下载按钮：JSON / PDF

#### 完成页（completed）

- 居中：大号 ✅ 图标 + "分析完成" 标题
- 统计行：已分析学生数 | 题目数 | 参考答案数
- 操作按钮：[查看完整报告] [下载报告]
- 提示继续上传答题卡

### 3. 底部浮动进度条

- 位置：固定在页面底部，始终可见
- 显示内容：旋转图标 + 任务描述 + 进度条 + 百分比 + 活跃任务数
- 显示条件：当有任务处于 queued / running 时显示
- 数据源：从 useTasks hook 获取活跃任务列表
- 交互：点击可跳转到任务中心
- 隐藏条件：无活跃任务时自动消失（使用 CSS transition）

## 状态处理

### Loading 状态
- 页面级：Spin + 全屏居中
- 区块级：Spin + inline-block
- 按钮级：Button loading 属性

### Empty 状态
- 无项目：Empty + "创建第一个项目"
- 无审查数据：Empty + "暂无提取结果，请等待提取完成"
- 无评分数据：Empty + "暂无评分数据"

### Error 状态
- 项目 error 状态：Alert type="error" 显示 error_message
- API 失败：message.error + 控制台错误
- 网络错误：全局 ErrorBoundary 组件包裹

### Edge Cases
- 同时多个任务运行：底部进度条显示 "N 个任务进行中"
- 上传大文件：显示文件大小和上传进度
- 页面刷新：React Query 缓存保持数据，重新轮询活跃任务
- 步骤回退：不允许（状态机单向流动）。用户可以导航到其他页面再回来

## 技术实现

### 文件结构

```
frontend/src/
  components/
    layout/
      AppLayout.tsx       ← 重构：顶栏 + 侧栏 + 浮动进度条
      BottomTaskBar.tsx   ← 新建：底部浮动进度条组件
    project/
      ProjectSteps.tsx    ← 新建：步骤条组件
      UploadSection.tsx   ← 从 ProjectDetailPage 提取
      ProcessingProgress.tsx ← 新建：实时进度展示组件
      QuestionReview.tsx  ← 从 ProjectDetailPage 提取
      AnswerReview.tsx    ← 新建：参考答案审查组件
      ScoreReview.tsx     ← 从 ProjectDetailPage 提取
      CompletionView.tsx  ← 从 ProjectDetailPage 提取
  
  pages/
    ProjectDetailPage.tsx ← 简化：引入子组件，步骤调度
    ProjectListPage.tsx   ← 重构：卡片式项目列表
    
  hooks/
    useTasks.ts           ← 不变，但增加活跃任务查询
    useProjects.ts        ← 不变
```

### 关键组件说明

**BottomTaskBar**：
- 从 useTasks hook 获取所有任务
- 过滤出 queued / running 状态的任务
- 显示活跃任务数和总进度（简单平均）
- 无任务时通过 CSS 动画隐藏（height: 0 → auto）

**ProcessingProgress**：
- 接收 stage_logs 数组
- 渲染进度条 + 阶段日志表格
- 通过 refetchInterval 定期刷新

### 交互流程

1. 用户打开项目 → 看到当前步骤的内容
2. 操作（上传/提取/审查/确认）→ 调用 API
3. API 返回后 → React Query 使缓存失效 → 项目状态变化
4. 状态变化 → STATUS_STEP_MAP 计算新步骤 → 重新渲染步骤内容
5. 处理中 → 轮询项目状态 + 阶段日志 → 实时更新进度
6. 处理完成 → 自动切换步骤内容到审查界面

## 不需要改动的部分

- `frontend/src/api/` — API 客户端保持不变
- `frontend/src/stores/` — Zustand store 不变
- `frontend/src/hooks/` — React Query hooks 基本不变，仅增加活跃任务查询
- 路由结构 — App.tsx 路由保持不变
- 后端 API — 不做修改
