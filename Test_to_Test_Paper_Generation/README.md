# 试卷智能重组系统 (Agentic Exam Generator)

这是一个基于多智能体（Multi-Agent）协作的试卷自动重组系统。系统能够将原始 PDF 试卷解析为结构化数据，并利用大语言模型（LLM）对每一道题进行知识点分析、场景重塑，最终生成一套全新的、具有相同考察目标的试卷。

## 🚀 核心功能

- **深度知识标注**：对齐 2022 版课程标准，支持分步式（定位+细化）精准标注知识点、核心素养及数学思想。
- **多智能体流水线**：
    - **KnowledgeAnalyzer**：双阶段分析，首先定位主知识点，随后动态加载考点详情进行深度画像。
    - **ScenarioGenerator**：基于“数学思想”（如数形结合、建模）重构真实应用情境。
    - **QuestionGenerator**：在保持考察逻辑不变的前提下，根据新场景重写题目。
- **自动排版生成**：将生成的题目重新组合，输出为格式精美的 Markdown 试卷。
- **完善的断点续传**：支持在处理过程中随时保存状态，可在程序中断后从指定位置恢复。

## 🛠️ 环境准备

### 1. 安装依赖
确保已安装 Python 3.9+，然后安装所需依赖：

```bash
pip install -r requirements.txt
```
*(注意：请确保已安装 `openai`, `pyyaml`, `requests`, `pydantic` 等核心库)*

### 2. 配置 API 密钥
在 `exam_generator/config.yaml` 中配置您的 API 密钥：

- `mineru_token`: 用于 [MinerU](https://mineru.openxlab.org.cn/) 服务（PDF 解析）。
- `zhichuang_key`: 用于 LLM 调用（支持 OpenAI 格式接口）。
- `zhichuang_base_url`: LLM 服务地址。

## 📖 使用指南

通过 `cli.py` 启动系统：

### 1. 开始新任务
```bash
python cli.py --input "path/to/your/exam.pdf"
```

### 2. 从断点恢复
程序运行过程中会自动在 `checkpoint_0` 和 `checkpoint_1` 文件夹下生成进度文件。如果任务中断，运行 `cli.py` 后按提示输入断点文件路径：

```bash
python cli.py
# 提示：👉 请输入断点文件相对路径以恢复 (直接回车则开始新任务): checkpoint_1/demo_20240101_120000.json
```

## 🏗️ 智能体工作流 (Agentic Pipeline)

系统采用 **"纵向处理"** 模式，即对每一道题完整运行一遍智能体链条，确保生成质量。

```mermaid
graph TD
    A[cli.py] --> B[ExamGenerationPipeline]
    B --> C[Step 0: PDFParser]
    C -->|结构化数据| CP0[Checkpoint 0]
    
    subgraph 纵向处理循环 (Per Question)
        CP0 --> D1[Step 1a: Topic Classification]
        D1 --> D2[Step 1b: Deep Competency Analysis]
        D2 -->|深度画像| E[Step 2: ScenarioGenerator]
        E -->|新场景| F[Step 3: QuestionGenerator]
        F -->|新题目| G[Checkpoint 1]
    end
    
    G --> H[Step 4: ExamAssembler]
    H --> I[Output: final_exam.md]
```

1.  **PDFParser (ParserAgent)**: 调用 MinerU 将 PDF 转为 Markdown，再利用 LLM 转化为结构化数据。
2.  **KnowledgeAnalyzer (Two-Step)**: 
    - **阶段 A**: 快速识别主知识点 ID（如 `A1-1`）。
    - **阶段 B**: 动态加载 `knowledge.json` 中的具体考点、核心素养及数学思想，进行深度画像。
3.  **ScenarioGenerator**: 保持考点不变，并显式应用“数学思想”构思全新的题目背景。
4.  **QuestionGenerator**: 结合新背景和原题逻辑，生成新的题干、选项及详细解析。
5.  **ExamAssembler**: 将所有新生成的题目汇总，按标准格式渲染为最终的 Markdown 试卷。

## 📂 项目结构

- `cli.py`: 系统入口，负责参数解析和断点引导。
- `exam_generator/`
    - `pipeline.py`: 核心调度逻辑。
    - `config.yaml`: 全局配置文件（模型、温度、路径等）。
    - `agents/`: 存放各智能体的实现代码。
        - `base.py`: 智能体基类，封装了 LLM 调用和 JSON 提取逻辑。
    - `pdf_parser/`: PDF 解析相关工具。
- `checkpoint_0/`: 存储 PDF 原始解析后的结果。
- `checkpoint_1/`: 存储每道题处理后的中间结果。
- `output/`: 最终生成的 Markdown 试卷存放处。

## ⚙️ 进阶配置

您可以在 `exam_generator/config.yaml` 中为不同的智能体分配不同的模型和温度：

```yaml
models:
  pdf_parser: "gpt-4o-mini"      # 提取类任务使用轻量模型
  analyzer: "claude-3-5-sonnet"  # 分析类任务使用强逻辑模型
  scenario: "claude-3-5-sonnet"  # 创意类任务
  generator: "claude-3-5-sonnet"

temperature:
  scenario: 0.7                  # 提高场景生成的随机性/创意
  generator: 0.4                 # 生成题目时保持适度稳健
```


（记得代码修改之后，同步地需要修改readme.md中的文件内容）