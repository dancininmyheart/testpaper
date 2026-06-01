# 相似试卷生成 — Prompt & 处理逻辑升级接入方案

> **目标**:把 `Test_to_Test_Paper_Generation/` 下新版的 **prompt 设计** 与 **处理逻辑**(双阶段 analyzer / 决策式 scenario / 课程大纲硬约束 generator / SVG 黑白规范)移植到平台已接入的相似试卷生成功能里,**不改动平台对外接口、不改动 `ExamGenerationService` 的调用约定**,确保接入期间老路径继续可用,新逻辑可灰度切流并随时回滚。
>
> 适用版本:`exam_generator/` 5月29日修订(`agents/analyzer.py`、`agents/scenario.py`、`agents/generator.py`、`agents/base.py`、`config.yaml`、`pdf_parser/parser.py` 已更新)。
>
> 文档版本:2026-05-29 初稿(v2)。

---

## 0. 摘要(TL;DR)

- 平台 `backend/application/exam_generation_service.py:150-156` 假定的 pipeline 契约是:
  `ExamGenerationPipeline(config, api_key, base_url, max_workers).run(questions, host_url) -> md_path`,同时产同名 `.pdf`。
- 当前磁盘上**新版** `pipeline.py` 把构造与 `run()` 签名都改了(`(config_path)` / `run(file_path, resume_path)`),并强行接入 MinerU PDF 解析 + Playwright PDF 渲染 — 直接对接会立刻 TypeError,且引入两个重型外部依赖。
- 平台已经有结构化 questions(来自 OCR + LLM),也已经有 reportlab PDF 通道(`demo/export_builders.py`),**不需要也不应该**让新版整体顶替进来。
- 推荐做法:**保持旧版对外接口契约**,在 `Test_to_Test_Paper_Generation/` 内部**重写实现**,只移植新版的 prompt 与 agent 处理逻辑;Step 0(PDF 解析)与 Step 5(Playwright PDF 导出)整体丢弃。
- 通过 **新旧 prompt 并存 + 环境变量切流** 在风险可控下灰度,默认保持旧 prompt 直到 V2 prompt 完成验收。

---

## 1. 调研结论

### 1.1 平台对外契约(必须不变)

```python
# backend/application/exam_generation_service.py:150-156
pipeline = ExamGenerationPipeline(
    config=config,           # dict (来自 config.yaml)
    api_key=api_key,         # str  (单 provider)
    base_url=base_url,       # str
    max_workers=max_workers, # int  (并发度)
)
result_path = pipeline.run(questions=adapted, host_url=host_url)  # -> str(md 绝对路径)
# 紧接着:os.path.splitext(result_path)[0] + ".pdf" 期望存在同名 PDF
```

`adapted` 是平台 DB → 题目 list 的映射结果(`_adapt_platform_question`,`backend/application/exam_generation_service.py:37-98`),字段约定:

```python
{
    "id": str,
    "type": str,            # "单选题"/"多选题"/"填空题"/"解答题"/"判断题"/"简答题"
    "stem": str,
    "options": list[str],   # ["A. xxx", "B. xxx", ...]
    "answer": str,
    "score": int|float,
    "knowledge_points": list[str],
}
```

下游 router(`backend/api/routers/paper_projects.py:1180-1213`)只读 `result_path` 与同名 `.pdf` 路径,**只要这两件产物存在,平台所有接口都不需要改**。

### 1.2 新版可用的 prompt 与逻辑(要移植)

| 模块 | 新版关键贡献 | 移植价值 |
|---|---|---|
| `agents/analyzer.py` | **双阶段**:Phase A 用便宜模型从 `knowledge.json` 选 `topic_id`;Phase B 用强模型做 `key_points_hit` / `core_competencies` / `key_math_ideas` / `difficulty` / `syllabus_compliance` 标注 | 让 generator 后续可以严格落在课程标准内,避免超纲 |
| `agents/scenario.py` | **决策式**:0-10 评分 → `CREATE_SCENARIO`(>=阈值)或 `MAINTAIN_ABSTRACT`(<阈值);硬约束禁止给纯代数/几何证明题强加情境 | 解决旧版"为所有题强加情境"的违和感 |
| `agents/generator.py` | 课程大纲硬约束 + SVG 黑白规范 + `new_questions[].svg_code` 字段 | 几何题可以原地生成 SVG,出题质量显著提升 |
| `agents/assembler.py` | 按题型分组排版,LaTeX 行内 `$...$` / 独行 `$$...$$` 规范 | 与旧版差异不大,可选择性移植 |
| `knowledge_manager.py` + `knowledge.json` | 初中数学知识体系(domains → subdomains → topics → key_points + 核心素养 + 数学思想) | analyzer / generator 都依赖,无可替代 |
| `agents/base.py` | 多 provider 客户端缓存 + per-agent `provider/model/temperature` 配置 | 让 analyzer/generator 用不同模型,平衡成本与质量 |

### 1.3 新版需要**丢弃**的部分

| 模块 | 丢弃原因 |
|---|---|
| `exam_generator/pdf_parser/parser.py` + `utils.py` (MinerU) | 平台已有 OCR/LLM 出来的结构化 questions,不需要再走 MinerU,且 token 是付费配额,无谓消耗 |
| `exam_generator/pdf_parser/exporter.py` (Playwright) | 平台已具备 reportlab PDF 通道(`demo/export_builders.py`),Playwright 引入 Chromium 二进制(~200MB+ 容器体积)和系统依赖,得不偿失 |
| `pipeline.py` 当前的 `run(file_path, resume_path)` 签名 | 与平台契约不兼容,且 `checkpoint_0/1` 写到 CWD 是脚本而非服务的设计 |
| `KnowledgeManager` 的相对路径默认值 | 需要替换为基于 `__file__` 的绝对路径解析 |
| `cli.py` 的 `input("...断点路径...")` 交互 | 服务环境不能阻塞 stdin |

---

## 2. 接入策略

### 2.1 总体方案 — "对外契约不变,对内整体重写"

```
                              ┌───────────────────────────────────────────┐
                              │   exam_generator/  (重写后)                 │
   平台 (零改动)               │                                            │
   ExamGenerationService      │  ExamGenerationPipeline                    │
        │                     │     __init__(config, api_key,              │
        ▼                     │                base_url, max_workers)      │
   pipeline = ExamGen         │     run(questions: list, host_url: str)    │
       Pipeline(...)          │       └─► _step1_analyze   (双阶段,新版)   │
   md = pipeline.run(         │       └─► _step2_scenario  (决策式,新版)   │
       questions=adapted,     │       └─► _step3_generate  (大纲约束,新版) │
       host_url=host_url)     │       └─► _step4_assemble  (新版 prompt)   │
                              │       └─► _step5_export_pdf (走平台         │
                              │                              reportlab)    │
                              │                                            │
                              │  knowledge.json / knowledge_manager.py     │
                              │     (原样保留,只修绝对路径)                 │
                              │                                            │
                              │  agents/base.py / analyzer / scenario /    │
                              │  generator / assembler                     │
                              │     (基本原样保留,适配 max_workers/         │
                              │      api_key 入参 + 不依赖 CWD)             │
                              └───────────────────────────────────────────┘
                              ✗ pdf_parser/ (MinerU + Playwright)  → 删除
                              ✗ cli.py                              → 保留独立,不被服务调用
```

**核心原则**:
1. **接口契约保持原状**,`ExamGenerationService` 不动一行。
2. **复用新版 agent 模块**,只调整入参/路径,以让它们脱离 CLI 假设。
3. **跳过 Step 0**(PDF 解析)—— `run(questions=...)` 进来就是已结构化的题目。
4. **PDF 渲染走平台已有通道**,不引入 Playwright。
5. **prompt 双轨**:`PROMPT_VARIANT=v1|v2` 环境变量决定每个 agent 走旧版 prompt 还是新版 prompt(各 agent 独立切流,见 §4.4)。

### 2.2 与上一版方案(平台侧适配)的差异

| 维度 | 上一版(V1/V2 service 双轨) | 当前方案(pipeline 内部重写) |
|---|---|---|
| 改动范围 | 平台侧新增 `ExamGenerationServiceV2` + Router 分支 | 只改 `Test_to_Test_Paper_Generation/` 内部 |
| 平台代码改动 | 中等(新 service + router 选择器) | **零** |
| 与 cli 独立运行兼容 | 是 | 是(cli.py 留接口) |
| MinerU/Playwright 依赖 | 引入 Playwright | **不引入** |
| 灰度颗粒度 | 整条 pipeline 切流 | 可按 agent 级别 prompt 切流(更细) |
| 回滚成本 | env var 即可 | env var + 各 agent prompt 单独回滚 |

---

## 3. 详细实施

### 3.1 目录与文件操作

```
Test_to_Test_Paper_Generation/
  exam_generator/
    __init__.py
    config.yaml                  # 改:env 占位符 + 移除真实密钥
    knowledge.json               # 不动
    knowledge_manager.py         # 改:默认 path = Path(__file__).parent / "knowledge.json"
    pipeline.py                  # 重写:旧接口 + 5步内部流程
    agents/
      __init__.py
      base.py                    # 改:接受外部传入 api_key/base_url 覆盖
      analyzer.py                # 不动(prompt 已是 v2;process_single 已对 schema)
      scenario.py                # 不动(同上)
      generator.py               # 不动
      assembler.py               # 改:新增 v1 prompt 兜底(可选)
      prompts/                   # 新增:prompt 双轨目录(见 §4.4)
        __init__.py
        v1.py                    # 旧 prompt(从 git history 或老用户提供)
        v2.py                    # 新版 prompt(本仓库现状提取)
    pdf_export.py                # 新增:复用 demo/export_builders 的 PDF 通道
  cli.py                         # 不动 / 或同步改成走重写后的 pipeline(可选)
  pdf_agent.py                   # 不动(独立调试用)
  debug_pdf_export.py            # 不动
  pdf_parser/  → 整目录删除      # MinerU 路径丢弃
```

### 3.2 重写后的 `pipeline.py`

```python
# Test_to_Test_Paper_Generation/exam_generator/pipeline.py
from __future__ import annotations

import concurrent.futures as cf
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .agents.analyzer import KnowledgeAnalyzer
from .agents.scenario import ScenarioGenerator
from .agents.generator import QuestionGenerator
from .agents.assembler import ExamAssembler

log = logging.getLogger("exam_generator.pipeline")


class ExamGenerationPipeline:
    """Backward-compatible facade.

    保持平台已接入的契约:
        ExamGenerationPipeline(config, api_key, base_url, max_workers)
        .run(questions: list[dict], host_url: str = "") -> str
    """

    def __init__(
        self,
        *,
        config: dict[str, Any],
        api_key: str = "",
        base_url: str = "",
        max_workers: int = 4,
    ):
        self.config = self._merge_inline_credentials(config, api_key, base_url)
        self.max_workers = max(1, int(max_workers or 1))

        output_dir = self.config.get("paths", {}).get("output_dir", "output")
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # checkpoints 放 output_dir 下,不污染 CWD
        self.checkpoint_dir = self.output_dir / "_checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # agents 直接吃 dict config
        self.analyzer = KnowledgeAnalyzer(config=self.config)
        self.scenario = ScenarioGenerator(config=self.config)
        self.generator = QuestionGenerator(config=self.config)
        self.assembler = ExamAssembler(config=self.config)

    # ---------- public ----------

    def run(self, *, questions: list[dict], host_url: str = "") -> str:
        if not questions:
            raise ValueError("ExamGenerationPipeline.run: no questions provided")

        log.info("[pipeline] start: %d questions, max_workers=%d",
                 len(questions), self.max_workers)

        cp0 = self._save_checkpoint({"questions": questions}, stage="step0_input")
        new_questions = self._run_per_question_loop(questions)
        cp1 = self._save_checkpoint({"new_questions": new_questions}, stage="step3_generated")

        markdown = self.assembler.run({"new_questions": new_questions})
        md_path = self._write_markdown(markdown)
        pdf_path = self._write_pdf(markdown, md_path)

        log.info("[pipeline] done: md=%s pdf=%s", md_path, pdf_path)
        return str(md_path)

    # ---------- internal ----------

    def _merge_inline_credentials(self, config, api_key, base_url):
        """允许平台直接传 api_key/base_url(覆盖 config.yaml)。

        优先级:run-time 入参 > config.yaml > env var(由 base.BaseAgent 解析)。
        """
        if not (api_key or base_url):
            return config
        cfg = json.loads(json.dumps(config))  # deep copy
        cfg.setdefault("api", {})
        active = cfg["api"].get("active_provider", "ds")
        if api_key:
            cfg["api"][f"{active}_key"] = api_key
        if base_url:
            cfg["api"][f"{active}_base_url"] = base_url
        return cfg

    def _run_per_question_loop(self, questions: list[dict]) -> list[dict]:
        """对每道题串行执行 analyze → scenario → generate;题目之间并行。"""

        def _process_one(idx_q):
            idx, q = idx_q
            try:
                qa = self.analyzer.process_single(dict(q))
                qs = self.scenario.process_single(qa)
                nq = self.generator.process_single(qs)
                return idx, nq
            except Exception as e:  # 单题失败不阻塞全局
                log.warning("[pipeline] question %s failed: %s", q.get("id"), e)
                return idx, None

        results: list[tuple[int, dict | None]] = []
        if self.max_workers > 1:
            with cf.ThreadPoolExecutor(max_workers=self.max_workers) as ex:
                for r in ex.map(_process_one, enumerate(questions)):
                    results.append(r)
        else:
            for r in map(_process_one, enumerate(questions)):
                results.append(r)

        results.sort(key=lambda x: x[0])
        return [nq for _, nq in results if nq]

    def _save_checkpoint(self, data, *, stage: str) -> Path:
        path = self.checkpoint_dir / f"{stage}_{self.timestamp}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("[pipeline] checkpoint: %s", path)
        return path

    def _write_markdown(self, markdown: str) -> Path:
        # 文件名 sentinel 必须与旧版兼容,因为 service 复制时按这两个文件名定位
        path = self.output_dir / f"generated_exam_{self.timestamp}.md"
        path.write_text(markdown, encoding="utf-8")
        return path

    def _write_pdf(self, markdown: str, md_path: Path) -> Path | None:
        from .pdf_export import render_markdown_to_pdf
        pdf_path = md_path.with_suffix(".pdf")
        try:
            render_markdown_to_pdf(markdown, pdf_path)
            return pdf_path
        except Exception as e:
            log.warning("[pipeline] pdf export failed: %s", e)
            return None
```

要点:
- `__init__` 签名与平台契约一致(`config` 是 dict,不是 path)。
- `run()` 接受 `questions: list[dict]` + `host_url: str`,返回 md 绝对路径,产同名 PDF。
- checkpoint 写到 `output_dir/_checkpoints/`,不污染 CWD。
- 题目之间用 `ThreadPoolExecutor(max_workers)` 并行;单题内部三步串行(保留新版 per-question vertical 设计的优势)。
- 单题失败不阻塞全局,沉默跳过(与新版 `pipeline.py:118-120` 行为一致)。

> **不实现**新版的 `resume_path` 续传 —— 平台已经有任务级失败重跑,跨进程续传场景在 SaaS 模式下不常见;如有需要,后续扩展。

### 3.3 `agents/base.py` 适配:接受 dict config

新版 `BaseAgent.__init__` 当前签名:`(config_path: str, agent_name: str)`。改为支持两路:

```python
class BaseAgent(ABC):
    def __init__(
        self,
        *,
        config: dict | None = None,
        config_path: str | None = None,
        agent_name: str = "base",
    ):
        if config is None and config_path is None:
            raise ValueError("BaseAgent requires either config or config_path")
        if config is not None:
            self.config = config
        else:
            with open(config_path, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f)
        # ...其余不变...
```

同步把 `KnowledgeAnalyzer.__init__` / `ScenarioGenerator.__init__` / `QuestionGenerator.__init__` / `ExamAssembler.__init__` 改为也支持 `config=` 入参,内部 `super().__init__(config=config, agent_name=...)`。

`cli.py` 继续传 `config_path=...`,二者并存。

### 3.4 `knowledge_manager.py` 绝对路径

```python
# Test_to_Test_Paper_Generation/exam_generator/knowledge_manager.py
from pathlib import Path

class KnowledgeManager:
    def __init__(self, file_path: str | Path | None = None):
        if file_path is None:
            file_path = Path(__file__).resolve().parent / "knowledge.json"
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Knowledge file not found: {file_path}")
        with file_path.open("r", encoding="utf-8") as f:
            self.data = json.load(f)
        # ...其余不变...
```

让 KnowledgeManager 不再依赖 CWD,代价是新增 `pathlib` import,改动量极小。

### 3.5 PDF 导出 — 复用 demo/export_builders

新增 `exam_generator/pdf_export.py`:

```python
"""Markdown → PDF,走平台已有 reportlab 通道。

不引入 playwright;不渲染 LaTeX 公式为图片。
公式保持原文 `$...$` / `$$...$$`,由前端 / 阅卷端的 MathJax 解决渲染。
"""
from __future__ import annotations

from pathlib import Path


def render_markdown_to_pdf(markdown: str, pdf_path: Path) -> None:
    # 第一版可以直接调用 demo 已有的简单文本→PDF builder。
    # 若 demo/export_builders 没有公开的"纯文本/markdown 入口",
    # 这里就退化为:用 markdown-it-py 渲染成 HTML → 用 reportlab 文本流。
    # 详细实现见 §5。
    from backend.application.markdown_pdf import write_markdown_pdf  # 待新增的薄包装
    write_markdown_pdf(markdown, pdf_path)
```

> **选项**:若不想在 `Test_to_Test_Paper_Generation/` 中 `import backend.*`(避免反向依赖),可以反过来让平台暴露一个 `paper_md_to_pdf` 入口在 `backend/infrastructure/pdf_render.py`,然后 pipeline `import` 它。哪条边都行,关键是**不依赖 Playwright**。

### 3.6 配置文件 — env 占位符化

`exam_generator/config.yaml` 当前**硬编码** packy/DeepSeek/zhichuang key 与 MinerU token。改为:

```yaml
api:
  active_provider: "${EXAM_GEN_ACTIVE_PROVIDER:-packy}"
  mineru_token: ""               # 本接入路径不使用,留空
  zhichuang_key: "${ZHICHUANG_KEY:-}"
  zhichuang_base_url: "${ZHICHUANG_BASE_URL:-https://s.lconai.com/v1}"
  ds_key: "${DEEPSEEK_KEY:-}"
  ds_base_url: "${DEEPSEEK_BASE_URL:-https://api.deepseek.com}"
  packy_key: "${PACKY_KEY:-}"
  packy_base_url: "${PACKY_BASE_URL:-https://www.packyapi.com/v1}"

models:
  analyzer: "deepseek-v4-flash"
  scenario: "deepseek-v4-flash"
  generator: "deepseek-v4-flash"
  assembler: "deepseek-v4-flash"
  pdf_parser: "deepseek-v4-flash"   # analyzer Phase A 复用此条目,即便 PDF 解析已废弃,字段名保留以兼容 base.py

model_providers:
  analyzer: "ds"
  scenario: "ds"
  generator: "ds"
  assembler: "ds"
  pdf_parser: "ds"

temperature:
  analyzer: 0.1
  scenario: 0.6
  generator: 0.3
  assembler: 0.1
  pdf_parser: 0.0

paths:
  output_dir: "output"

batch_size:
  analyzer: 10
  scenario: 5
  generation: 4                   # 与平台旧 config 字段名对齐:pipeline.max_workers 从这里读

scenario_threshold: 6
curriculum_level: "Junior High"
graph_mode: "svg"

# === Prompt 双轨切流(见 §4.4) ===
prompts:
  analyzer: "${EXAM_GEN_PROMPT_ANALYZER:-v2}"
  scenario: "${EXAM_GEN_PROMPT_SCENARIO:-v2}"
  generator: "${EXAM_GEN_PROMPT_GENERATOR:-v2}"
  assembler: "${EXAM_GEN_PROMPT_ASSEMBLER:-v1}"   # assembler 旧版本地排版更稳,首版保留 v1
```

平台侧 `ExamGenerationService.build_generation_config` 已经会读这个 yaml(`backend/application/exam_generation_service.py:111-121`);只要 yaml 解析后 `config["api"]["${VAR}"]` 形态的字符串被 `BaseAgent` 看到,会立即抛 `API key not found`,因此需要在 yaml 加载点(pipeline 入口或 service)统一做一次 `${VAR}` 展开。

最小化改动:在 `ExamGenerationService.build_generation_config` 里加 5 行 env 展开,或者在新 pipeline `__init__` 中加。**推荐放 pipeline `__init__`**,这样独立 CLI 也受益。

### 3.7 `.env.example` 与运维

`.env.example` 追加:

```
# 相似试卷生成:provider 与 key
EXAM_GEN_ACTIVE_PROVIDER=packy
PACKY_KEY=
PACKY_BASE_URL=https://www.packyapi.com/v1
DEEPSEEK_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
ZHICHUANG_KEY=
ZHICHUANG_BASE_URL=https://s.lconai.com/v1

# Prompt 双轨切流:v1 = 旧 prompt,v2 = 新 prompt(本次升级)
EXAM_GEN_PROMPT_ANALYZER=v1
EXAM_GEN_PROMPT_SCENARIO=v1
EXAM_GEN_PROMPT_GENERATOR=v1
EXAM_GEN_PROMPT_ASSEMBLER=v1
```

> **安全告警(必须先做)**:`exam_generator/config.yaml` 已提交了真实 API key 与 MinerU token,接入前**必须先轮转这些密钥**并把 yaml 改成 placeholder。这件事不依赖代码改动,运维侧立即可执行。

---

## 4. Prompt 双轨切流(核心安全机制)

### 4.1 动机

新版 prompt 在某些题型上输出风格变化大(尤其是 scenario 决策模式直接拒绝给纯代数题加情境),业务方/教研侧可能需要 A/B 试用之后再决定全量切流。直接覆盖旧 prompt 风险高。

### 4.2 结构

```
exam_generator/agents/prompts/
  __init__.py
  v1.py                # 旧 prompt 常量(从老仓库 / git history 拷过来)
    ANALYZER_SYSTEM = "..."
    SCENARIO_SYSTEM = "..."
    GENERATOR_SYSTEM = "..."
    ASSEMBLER_SYSTEM = "..."
  v2.py                # 新版 prompt(本仓库现状提取)
    ANALYZER_PHASE_A_PROMPT = "..."     # 注意:analyzer v2 是双阶段动态 prompt
    ANALYZER_PHASE_B_PROMPT_FN = lambda topic_id, details, comps, ideas, standard: "..."
    SCENARIO_SYSTEM = "..."
    GENERATOR_SYSTEM = "..."
    ASSEMBLER_SYSTEM = "..."
```

> **重要**:analyzer v2 不是静态 prompt,而是依赖 `KnowledgeManager` 动态构造的两段提示。`prompts/v2.py` 暴露**函数**而非常量;v1 暴露常量。各 agent 内部按 variant 走不同分支。

### 4.3 agent 内部分发逻辑(以 analyzer 为例)

```python
class KnowledgeAnalyzer(BaseAgent):
    def __init__(self, *, config=None, config_path=None):
        self.km = KnowledgeManager()  # 现已不依赖 CWD
        super().__init__(config=config, config_path=config_path, agent_name="analyzer")
        self.variant = self.config.get("prompts", {}).get("analyzer", "v2")

    def process_single(self, question):
        if self.variant == "v1":
            return self._process_single_v1(question)
        return self._process_single_v2(question)

    def _process_single_v1(self, question):
        from .prompts.v1 import ANALYZER_SYSTEM
        # 单阶段,直接喂题
        user_msg = f"...{json.dumps(question, ensure_ascii=False)}..."
        resp = self._call_llm(user_msg, system_prompt=ANALYZER_SYSTEM)
        result = self._extract_json(resp)
        if isinstance(result, dict):
            question.update(result)
        return question

    def _process_single_v2(self, question):
        # 现有新版双阶段实现(analyzer.py:88-118)整段搬过来
        ...
```

scenario / generator / assembler 同理。

### 4.4 切流粒度

环境变量 → yaml `prompts.<agent>` → agent 构造时读取:

```
EXAM_GEN_PROMPT_ANALYZER=v2   # 仅 analyzer 用新 prompt
EXAM_GEN_PROMPT_SCENARIO=v1   # scenario 仍走旧 prompt
EXAM_GEN_PROMPT_GENERATOR=v1
EXAM_GEN_PROMPT_ASSEMBLER=v1
```

这样可以**逐 agent 灰度**:先切 analyzer(只影响标注,不直接生成新题,风险最低),稳定后切 generator,最后再切 scenario(影响最大,因为决策模式会改变题目风格)。

### 4.5 旧 prompt 的来源

如果旧 prompt 已被新版覆盖、无 git 历史可查,有三个回填来源:

1. **`Test_to_Test_Paper_Generation/__pycache__/exam_generator/agents/*.cpython-39.pyc`** — 用 `uncompyle6` 或 `decompyle3` 反编译可拿到旧实现。
2. **`outputs/platform/storage/generated_exams/<old_pid>/checkpoint_*.json`** — 看历史产物的 system prompt 痕迹。
3. **直接以 `pipeline.md` 文档中的 Agent 0~4 system prompt 作为 v1 prompt**:`pipeline.md` 是设计文档版本,与 5月29日代码实现里的 prompt 已有差异 — 实际现网用的可能更接近文档版本。

> **建议**:先按 (3) 用 `pipeline.md` 中的 Agent 1~4 系统提示词作 v1 prompt,作为"已知良好"的兜底基线;后续若产品反馈某场景下 v1 更好,再回滚特定 agent 即可。

---

## 5. 改动清单(逐文件)

### 5.1 新增

| 文件 | 用途 |
|---|---|
| `Test_to_Test_Paper_Generation/exam_generator/agents/prompts/__init__.py` | 空 init |
| `Test_to_Test_Paper_Generation/exam_generator/agents/prompts/v1.py` | 旧 prompt 常量 |
| `Test_to_Test_Paper_Generation/exam_generator/agents/prompts/v2.py` | 新版 prompt(提取自当前 analyzer/scenario/generator/assembler) |
| `Test_to_Test_Paper_Generation/exam_generator/pdf_export.py` | Markdown → PDF,走平台 reportlab 通道 |
| `backend/infrastructure/markdown_pdf.py`(可选,若选择反向暴露) | 给 `pdf_export.py` 调用的平台侧 PDF 渲染入口 |

### 5.2 改写

| 文件 | 改动 |
|---|---|
| `Test_to_Test_Paper_Generation/exam_generator/pipeline.py` | 全量重写,见 §3.2 |
| `Test_to_Test_Paper_Generation/exam_generator/knowledge_manager.py` | `__init__` 默认路径改为 `Path(__file__).parent / "knowledge.json"`,见 §3.4 |
| `Test_to_Test_Paper_Generation/exam_generator/agents/base.py` | 支持 `config=` 入参;`_call_llm` 接受 `system_prompt` 覆盖(已支持);yaml `${VAR}` 占位符在加载点统一展开 |
| `Test_to_Test_Paper_Generation/exam_generator/agents/analyzer.py` | 增加 v1 / v2 prompt 分发(§4.3);构造支持 `config=` |
| `Test_to_Test_Paper_Generation/exam_generator/agents/scenario.py` | 同上 |
| `Test_to_Test_Paper_Generation/exam_generator/agents/generator.py` | 同上 |
| `Test_to_Test_Paper_Generation/exam_generator/agents/assembler.py` | 同上 |
| `Test_to_Test_Paper_Generation/exam_generator/config.yaml` | env 占位符化(§3.6),移除真实密钥 |
| `Test_to_Test_Paper_Generation/cli.py` | 改用重写后 pipeline 入口(或保留 deprecation 提示) |

### 5.3 删除

| 文件/目录 | 原因 |
|---|---|
| `Test_to_Test_Paper_Generation/exam_generator/pdf_parser/` 整目录 | 平台已有结构化 questions,不再走 MinerU |
| `Test_to_Test_Paper_Generation/__pycache__/`,各子目录的 `__pycache__` | 老编译产物,清理一下避免误加载 |

### 5.4 平台侧

| 文件 | 改动 |
|---|---|
| `backend/application/exam_generation_service.py` | **零改动**(本方案的核心承诺) |
| `backend/api/routers/paper_projects.py` | **零改动** |
| `backend/requirements.txt` | 若选 §3.5 反向暴露方案,不新增依赖;若 `pdf_export.py` 自行用 markdown-it-py + reportlab,则追加 `markdown-it-py>=3.0.0,<4.0.0` |
| `.env.example` | 追加 §3.7 中的环境变量 |
| `Dockerfile.backend` | 无新增系统依赖 |

---

## 6. 测试计划

### 6.1 单元测试

新增 `tests/exam_generator/`:

| 用例 | 描述 |
|---|---|
| `test_pipeline_backward_compat_signature` | 用旧 kwargs 构造 + `run(questions=, host_url=)` 调用,验证返回 md 路径存在、同名 pdf 存在 |
| `test_pipeline_credentials_override` | `api_key="K"` / `base_url="U"` 入参覆盖 config.yaml 中的对应 provider 字段 |
| `test_pipeline_max_workers_parallel` | mock agents,`max_workers=4` 时调用顺序乱序,但返回结果按输入顺序排列 |
| `test_pipeline_single_question_failure_skipped` | 一道题抛异常,其余正常完成,最终 markdown 不含失败题 |
| `test_pipeline_checkpoint_saved` | `_checkpoints/` 下 `step0_input_*.json` 与 `step3_generated_*.json` 存在,内容正确 |
| `test_knowledge_manager_absolute_path` | 在任意 CWD 下能构造,默认加载 `exam_generator/knowledge.json` |
| `test_prompt_variant_selection_per_agent` | 仅 `EXAM_GEN_PROMPT_ANALYZER=v2` 时,只 analyzer 走新 prompt,其余 agent 走 v1(用 monkeypatch 验证 system_prompt 内容) |
| `test_config_env_placeholder_expansion` | yaml 中 `${PACKY_KEY:-foo}`,无环境变量时返回 `"foo"`,有时返回 env 值 |
| `test_pdf_export_fallback_silent` | 当 `pdf_export.render_markdown_to_pdf` 抛异常时,`run()` 仍正常返回 md 路径,记录 warning |

> **不调用真实 LLM**:所有 agent 在测试中 monkeypatch `_call_llm` 返回预制 JSON 字符串。

### 6.2 契约/回归测试

`tests/platform/test_exam_generation_service.py`(新增,若没有的话):

| 用例 | 描述 |
|---|---|
| `test_service_run_generation_calls_pipeline_with_legacy_kwargs` | mock `ExamGenerationPipeline`,验证 service 仍以 `config=`/`api_key=`/`base_url=`/`max_workers=` 构造,`run(questions=, host_url=)` 调用 |
| `test_service_copies_md_and_pdf_to_storage` | mock pipeline 返回临时 md 路径 + 同名 pdf,验证 service 把它们复制到 `storage/generated_exams/<pid>/generated_exam.{md,pdf}` |

### 6.3 端到端

1. **白名单单项目灰度** — 在 staging 环境挑一个已完成 OCR + 评分的真实项目,设 `EXAM_GEN_PROMPT_ANALYZER=v2`,其余 agent 保持 v1;POST 生成接口,观察:
   - 日志中 analyzer 输出包含 `topic_id` / `syllabus_compliance` 字段
   - 最终 markdown 题目风格与旧版基本一致(因为 generator 还是 v1)
2. **逐 agent 切流** — 先后切 generator → scenario → assembler 到 v2,每切一档跑同一项目,人工对比产物差异。
3. **回归 v1 全开** — 把所有 prompt 切回 v1,产物与历史 baseline 比对(diff 比例 < 5%)。
4. **并发** — 同时跑 3 个项目的生成,确认 `_checkpoints/` 不互踩、ThreadPoolExecutor 内部 LLM 客户端复用无竞态。
5. **依赖缺失降级** — 故意删 `reportlab`,验证只产 md,前端 PDF 接口返回 404 + 明确错误信息。

### 6.4 验收标准

- [ ] 平台 `ExamGenerationService` 无任何代码改动,所有 `tests/platform/` 已有测试通过。
- [ ] 新增 `tests/exam_generator/` 单元测试通过率 100%,覆盖率 ≥ 80%。
- [ ] 至少 5 个真实项目在 staging 完成端到端验证(单选/多选/填空/解答/判断 全覆盖)。
- [ ] V2 prompt 下 markdown 输出在 MathJax 中正确渲染,SVG 题目可显示(generator v2)。
- [ ] 同等题量下端到端用时 ≤ 旧版 1.5×(双阶段 analyzer 多一次调用是可接受成本)。

---

## 7. 风险与缓解

| 风险 | 严重性 | 缓解 |
|---|---|---|
| `config.yaml` 硬编码密钥 | 高 | §3.6 强制 env 占位符;接入前先轮转所有出现在仓库历史的 key/token |
| `pipeline.md` 中文档级 prompt 与实际线上旧 prompt 有差异 | 中 | §4.5 列了三个回填来源,优先用反编译 pyc,文档作兜底;v1 上线前用真实项目对照产物 |
| `KnowledgeManager` 加载 `knowledge.json` 失败 | 中 | §3.4 绝对路径解析;启动时显式断言文件存在,失败抛清晰错误而非 silent fallback |
| analyzer v2 双阶段调用次数翻倍,成本上升 | 中 | Phase A 走便宜模型(`pdf_parser` 模型条目);可在 config 中给 `analyzer.phase_a_model` 单独配 |
| 并发下 `_call_llm` streaming print 互相穿插难读 | 低 | 在 `_call_llm` 中给每次输出前缀 `[agent={name} qid={q_id}]`;或把 streaming 输出降级为只在 DEBUG 时打开 |
| LLM 输出违反 `$...$` 规范返回 `\(...\)` | 中 | 新版 prompt 已显式禁止;在 pipeline 收尾时跑一次正则修正(`\\\(...\\\)` → `$...$`,`\\\[...\\\]` → `$$...$$`) |
| 单题失败 silent skip 导致最终题数 < 输入题数 | 中 | 在 pipeline 末尾若 `len(new_questions) < len(input_questions) * 0.8`,抛 `RuntimeError`,触发 router 走 `error` 状态;否则继续 |
| reportlab 渲染 LaTeX 公式无法可视化 | 中 | 第一版接受"PDF 中公式以原文 `$...$` 显示";若产品端要求公式渲染,后续单独接入 KaTeX-CLI / MathJax-node,**仍不引入 Playwright** |
| `cli.py` 调用旧 `(config_path)` 签名而新 pipeline 是关键字参数 | 低 | cli 同步改:`ExamGenerationPipeline(config=load_config(args.config), max_workers=4)` |
| 平台 `host_url` 入参在新 pipeline 中未被使用 | 低 | 接受;`host_url` 旧版可能用于生成 SVG/图片的回链,如果未来 generator v2 引用图床,再把 host_url 透传进去 |

---

## 8. 时间线建议

| 阶段 | 工作量(人日) | 输出 |
|---|---|---|
| Stage 1 — 密钥轮转 + yaml env 化 | 0.5 | 安全基线对齐 |
| Stage 2 — pipeline 重写 + base 适配 + KM 绝对路径 | 1.5 | 旧接口可调用,默认全 v1 prompt 跑通 |
| Stage 3 — Prompt v1/v2 双轨拆分 | 1 | `prompts/v1.py` + `prompts/v2.py` + agent 分发逻辑 |
| Stage 4 — PDF 导出接平台通道 | 0.5 | reportlab 路径打通,Playwright 完全摘除 |
| Stage 5 — 单元测试 | 1 | 覆盖率 ≥ 80% |
| Stage 6 — Staging 灰度 + 人工验收 | 1 | 各 agent 切流验证、回归对比 |
| Stage 7 — 文档 + 默认切到 v2 | 0.5 | 部署文档 / runbook / 默认值 |
| **总计** | **~6 人日** | |

---

## 9. 回滚预案

1. **逐 agent 回滚**:把 `EXAM_GEN_PROMPT_<AGENT>=v1` 即可,运行中任务不受影响,下一次任务立即生效。
2. **全量回滚到旧 prompt**:四个 env 变量全设 `v1`。
3. **代码级回滚**:本方案改动全部在 `Test_to_Test_Paper_Generation/` 内部 + `.env.example`,`git revert` 一两个 commit 即可。平台侧 0 改动,不需要任何回滚。
4. **数据**:pipeline 失败时 `paper_projects.status` 已经迁移到 `error`,异常写入 `extra_data.generated_paper_error`。运维通过 `POST /paper-projects/<id>/reset-to-ready` 拉回 `ready`,再次重试即可。

---

## 10. 后续可选优化(out of scope)

- **结构化结果入库**:把 `_checkpoints/step3_generated_*.json` 持久化到 `paper_generated_questions` 表,支持"按题预览/编辑/再生成单题"。
- **多模型混搭**:利用 `models.<agent>: {provider, model}` 写法,让 Generator 用 GPT-4o,Analyzer Phase A 用 deepseek-v4-flash。
- **Assembler 本地排版**:`assembler` 的 LLM 排版每题一次 LLM 调用,可被一段 Jinja 模板替代,显著降本(尤其试卷题量大时)。
- **Prompt A/B 评估**:在 pipeline 中支持 `prompt_label` 字段(如 `v2-2026-05-29`),把生成结果带 label 存档,做线下评估。
- **公式渲染到 PDF**:接入 KaTeX-CLI(纯 Node,无浏览器)或 MathJax-node 把 `$...$` / `$$...$$` 离线渲染成 SVG/PNG,再嵌入 reportlab。
- **Per-question 进度回写**:pipeline 每完成一题就 update `paper_projects.extra_data.generation_progress`,前端轮询展示进度。

---

## 11. 落地检查清单

- [ ] `Test_to_Test_Paper_Generation/exam_generator/config.yaml` 真实密钥已轮转,文件改为 `${VAR}` placeholder。
- [ ] `pipeline.py` 重写完毕,与平台契约一致(`(config, api_key, base_url, max_workers)` / `run(questions, host_url)`)。
- [ ] `agents/base.py` / `analyzer.py` / `scenario.py` / `generator.py` / `assembler.py` 支持 `config=` 入参 + prompt 双轨。
- [ ] `knowledge_manager.py` 默认路径用 `__file__` 解析,任意 CWD 可加载。
- [ ] `exam_generator/pdf_parser/` 已删除。
- [ ] `pdf_export.py` 与平台 reportlab 通道打通,Playwright 完全不被引用。
- [ ] `tests/exam_generator/` 全套单元测试通过。
- [ ] `tests/platform/test_exam_generation_service.py` 契约测试通过(确认平台调用方零改动)。
- [ ] Staging 灰度验收通过(逐 agent 切流 + 全量切流场景均跑过)。
- [ ] `.env.example` 与 README / runbook 更新。
- [ ] 默认环境变量在生产/staging 设为目标值(渐进式从 `v1` 升到 `v2`)。
- [ ] PR 描述引用本文档,标注 `risk = medium` / `reversibility = high(env-only)`。
