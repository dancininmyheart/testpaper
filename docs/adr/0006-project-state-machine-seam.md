# ADR-0006: 试卷项目状态机收敛与 transition() seam

**状态**：已采纳 · **日期**：2026-05-13 · **提出者**：架构 review (improve-codebase-architecture skill)

## 背景

试卷项目（Paper Project）有 12 个状态（`backend/domain/models.py:19-32`），CONTEXT.md 描述了状态机但缺少强制约束。`PaperRepository.update_project_status` 在 5 个不同位置被直接调用：

- `backend/application/paper_service.py`：approve_reference_answers (L233) / approve_questions (L320) / save_score_review_data (L331) / approve_scores_and_finalize (L345-353)
- `backend/api/routers/paper_projects.py`：直接写状态 (L347、L514)
- `backend/application/mineru_extraction.py:475`：step4_save 内
- `backend/application/analysis_service.py:278-310`：job 完成后

观察到的 friction：

- **没有统一前置条件校验**——任何调用方可以 `draft → analyzing` 直接跳过中间所有状态
- **Job 失败时项目状态不变**——卡在 `analyzing`，需要人工排查
- **状态变更无统一 audit trail**——出问题时不知道是谁、何时、为什么推进的

Locality 极差：要回答"什么时候允许从 X 转到 Y"，需要 grep 全仓 + 阅读 5 个文件的业务逻辑。

## 决策

引入 **`ProjectStateService.transition()`** 作为唯一的状态写入 seam：

```
backend/domain/state_machine.py        ← 纯函数转换矩阵（零外部依赖）
backend/application/project_state_service.py  ← Service：fetch + validate + write + audit
backend/infrastructure/repositories.py ← _update_project_status_internal（私有）
```

### Module shape

- **`backend/domain/state_machine.py`**（新增）：纯函数 `validate_transition(from_status, to_status) -> None`，含 12 状态完整合法转换矩阵；违法 raise `InvalidProjectTransition`。
- **`backend/application/project_state_service.py`**（新增）：`ProjectStateService.transition(project_id, to_status, *, actor_user_id)`。内部：fetch 当前状态 → 调 `domain.validate_transition` → 调 repo 内部写入 → 写一条 audit_log。
- **`PaperRepository.update_project_status`** 重命名为 `_update_project_status_internal`。仅 `ProjectStateService` 调用。

### 前置条件范围

**只校验状态对合法性**（state machine 层面），**不校验业务不变量**（如 questions 非空、所有 job succeeded）。后者由调用方负责。

边界明确：状态机 module 防"硬跳"，不防"业务不一致"。如未来发现某 invariant 被绕过，那是业务校验缺失，不是状态机缺失。

### Enforcement

5 处现有调用一次性迁移到 `state_service.transition()`，与 repo 私有化同 PR 落地。新代码无法绕过——`_update_project_status_internal` 私有命名即合同。

### Job lifecycle 联动

JobWorker 与项目状态显式联动：

- Job succeeded（`is_paper_extraction`）→ transition(`review_questions`)
- Job failed → transition(`error`)（仅当当前状态为 `analyzing`）
- `review_scores → completed`：HTTP router 也改调 transition()，不动语义

### Audit

每次 transition() 写一条 audit_log：`(actor_user_id, target_type=paper_project, target_id, action=project_transition, detail={from, to})`。复用现有 `AuditService`，无新表。

## 后果

正面：

- **Leverage**：调用方语义统一——`transition(p, "ready")`，不需要记得"还要不要更新别的字段"
- **Locality**：转换规则全在 `domain/state_machine.py`，新加状态或规则只改一处
- **可测性**：转换矩阵是纯函数，可为每条合法/非法转换写一个 case，不需要起 Flask
- **可观测性**：所有状态变更走同一审计路径，问题溯源容易
- **Deletion test**：删 ProjectStateService → 5 处需各自实现 validate + audit，复杂度扩散 ✓

负面：

- 5 处一次性迁移有风险（机械替换为主，但需要回归测试覆盖）
- 每次 transition() 多一次 audit_log 写入（DB 一次写）
- 业务不变量校验仍分散——本 ADR 只解决一半问题，另一半（业务一致性）留作后续议题

## 备选方案

| 方案 | 拒绝理由 |
|---|---|
| **不封死 `update_project_status`，仅新增 transition()** | 失去 enforcement——新代码可能绕过；review/约定不可靠 |
| **PaperProject 升级为 entity，转换写在 entity 方法上**（最 DDD 教科书） | PaperProject 现在是 dataclass，questions/jobs 不在 entity 上；需要更大范围重构 |
| **domain 接收 ProjectStatusSnapshot 校验业务不变量** | 增加 snapshot 字段集合的设计成本；业务不变量是否归状态机校验是另一争议，本次不开 |
| **事件驱动（JobWorker 发布事件，StateService 订阅）** | 增加事件表/订阅器基础设施，本项目规模不需要，直接调用更简单 |

## 不在范围

- Mastery 自动接入（架构 review 候选 ④，后续单独议题）
- MinerU 4-step unified context（候选 ②，后续单独议题）
- Stage 接口化 + AI ports 兑现（候选 ③+⑤，ADR-0002 Phase 3 未完成，独立议题）

## 关联

- 与 ADR-0001 一致（domain 层零外部依赖；application 编排领域逻辑）
- 不与现有 ADR 冲突
