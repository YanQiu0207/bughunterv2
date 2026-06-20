# 实施任务清单 — M1 诊断 MVP

> 由 `spec.md` 生成（`docs/design-docs/bugfix-agent/pipeline/spec.md`）
> 任务总数: 9
> 核心原则: 基础设施先于业务逻辑——先建数据模型与配置，再建解析器与工具，最后组装 Agent 和 CLI

## 依赖关系总览

```
Task 1 (数据模型 + 项目骨架)
  ├─────────────────────────────────────────────┐
  ↓                                             ↓
Task 2 (配置加载)    Task 4 (源码索引)    Task 7 (报告输出)
  ↓                       ↓
Task 3 (堆栈解析器)  Task 5 (工具: read_source + find_callers)
  ↓                       ↓
  └──────→ Task 6 (DiagnosisAgent · LangGraph ReAct) ←──┘
                          ↓
                    Task 8 (CLI 入口 diagnose.py)
                          ↓
                    Task 9 (集成测试 canonical example)

并行机会: Task 3、Task 4、Task 7 均仅依赖 Task 1/2，可并行实现
```

## 变更影响概览

### 文件变更清单

| 文件 | 操作 | 涉及任务 |
|------|------|---------|
| `pyproject.toml` | 新建 | Task 1 |
| `config.yaml` | 新建 | Task 2 |
| `src/__init__.py` | 新建 | Task 1 |
| `src/models.py` | 新建 | Task 1 |
| `src/config.py` | 新建 | Task 2 |
| `src/stack_parser.py` | 新建 | Task 3 |
| `src/source_index.py` | 新建 | Task 4 |
| `src/tools/__init__.py` | 新建 | Task 5 |
| `src/tools/read_source.py` | 新建 | Task 5 |
| `src/tools/find_callers.py` | 新建 | Task 5 |
| `src/agent/__init__.py` | 新建 | Task 6 |
| `src/agent/prompts.py` | 新建 | Task 6 |
| `src/agent/diagnosis_agent.py` | 新建 | Task 6 |
| `src/report_writer.py` | 新建 | Task 7 |
| `diagnose.py` | 新建 | Task 8 |
| `workspace/diagnosis/.gitkeep` | 新建 | Task 1 |
| `tests/fixtures/src/Demo.java` | 新建 | Task 3 |
| `tests/fixtures/stack_trace.txt` | 新建 | Task 3 |
| `tests/test_stack_parser.py` | 新建 | Task 3 |
| `tests/test_source_index.py` | 新建 | Task 4 |
| `tests/test_tools.py` | 新建 | Task 5 |
| `tests/test_integration.py` | 新建 | Task 9 |

### 构建系统变更

- `pyproject.toml`（Task 1）：声明依赖 langgraph、langchain-anthropic、pyyaml、pytest

## 风险与假设

| # | 描述 | 影响任务 | 假设/处理 |
|---|------|---------|----------|
| 1 | 目标项目源码目录结构 | Task 4 | 假设 Maven 标准结构 `src/main/java/{pkg}/{Class}.java`；非标路径通过配置项 `extra_source_roots` 补充 |
| 2 | `find_callers` 误报 | Task 5 | 使用文本 grep 搜索方法名，同名方法会误报；由 LLM 在读码后过滤，M1 可接受 |
| 3 | LangGraph 版本兼容性 | Task 6 | 固定使用 `langgraph>=0.2,<0.3`，`create_react_agent` API 在此范围内稳定 |
| 4 | Agent 输出结构化结果 | Task 6 | 通过 `submit_diagnosis` tool（LangGraph tool call）强制结构化输出，不依赖解析自然语言 |
| 5 | ANTHROPIC_API_KEY 环境变量 | Task 8/9 | 集成测试依赖真实 API key；task 9 要求运行环境已设置该变量 |

---

## 任务列表

### 任务 1: [x] 数据模型 + 项目骨架

- 文件:
  - `pyproject.toml`（新建）
  - `src/__init__.py`（新建）
  - `src/models.py`（新建）
  - `workspace/diagnosis/.gitkeep`（新建）
- 依赖: 无
- spec 映射: spec §4.8（落盘格式数据结构）、§4.10（核心组件）
- 说明: 建立项目可安装结构，定义贯穿全流程的数据模型（StackFrame、BacktraceStep、Conclusion、DiagnosisReport）。所有后续任务的类型依赖均来自此处。
- context:
  - `src/models.py` — 直接新建，无上游；下游：Task 3/4/5/6/7 均导入此模块
- 子任务:
  - [ ] 1.1: 创建 `pyproject.toml`，声明 `requires-python = ">=3.11"`，依赖：`langgraph>=0.2,<0.3`、`langchain-anthropic>=0.3`、`langchain-core>=0.3`、`pyyaml>=6.0`；dev 依赖：`pytest>=7.0`、`pytest-asyncio>=0.21`、`black`、`isort`、`mypy`
  - [ ] 1.2: 创建 `src/models.py`，用 `@dataclass` 定义：`StackFrame`、`EvidenceItem`、`BacktraceStep`（含 `decision: Literal["in_code","out_of_code"]`）、`Conclusion`（含 `confidence: Literal["high","medium","low"]`）、`DiagnosisReport`（含 `status: Literal["in_progress","completed"]`）
  - [ ] 1.3: 创建 `workspace/diagnosis/.gitkeep`
- 验收标准:
  - [ ] `pip install -e ".[dev]"` 安装成功无报错
  - [ ] `python -c "from src.models import DiagnosisReport"` 执行无异常

---

### 任务 2: [x] 配置加载

- 文件:
  - `config.yaml`（新建）
  - `src/config.py`（新建）
- 依赖: Task 1
- spec 映射: spec §3.1（`--config` 参数）、§4.5（框架包排除列表）、§4.10（max_steps 配置项）
- 说明: 定义运行参数的配置文件格式及加载逻辑。`config.yaml` 提供默认值，CLI 可通过 `--config` 覆盖。
- context:
  - `src/config.py` — 直接新建；下游：Task 3（`framework_packages`）、Task 6（`max_steps`）
- 子任务:
  - [ ] 2.1: 创建 `config.yaml`，包含字段：`framework_packages`（默认 `["java.", "javax.", "sun.", "com.sun.", "org.springframework.", "org.apache.", "org.slf4j."]`）、`max_steps`（默认 10）、`extra_source_roots`（默认 `[]`）
  - [ ] 2.2: 创建 `src/config.py`，定义 `Config` dataclass 及 `load_config(path: str) -> Config`，使用 `pyyaml` 读取，缺失字段用默认值填充
- 验收标准:
  - [ ] `python -c "from src.config import load_config; c = load_config('config.yaml'); assert c.max_steps == 10"` 执行无异常

---

### 任务 3: [x] Java 堆栈解析器

- 文件:
  - `src/stack_parser.py`（新建）
  - `tests/fixtures/stack_trace.txt`（新建）
  - `tests/fixtures/src/Demo.java`（新建）
  - `tests/test_stack_parser.py`（新建）
- 依赖: Task 1, Task 2
- spec 映射: spec §4.5（找业务顶帧）、§4.4（canonical example 堆栈）
- 说明: 解析 Java 异常堆栈文本，提取结构化帧列表，并按框架包排除列表找出第一个业务顶帧。
- context:
  - `src/stack_parser.py` — 直接新建；上游：`src/config.py`（framework_packages）；下游：Task 6（agent 输入）
- 子任务:
  - [ ] 3.1: 在 `tests/fixtures/` 创建 canonical example 文件：`Demo.java`（含 main/handle/printName 三个方法）和 `stack_trace.txt`（NPE 堆栈，含 Demo.printName:10 / handle:6 / main:2 三帧）
  - [ ] 3.2: 实现 `parse_stack_trace(text: str) -> list[StackFrame]`，正则匹配 `at ClassName.method(File.java:line)` 格式
  - [ ] 3.3: 实现 `find_business_top_frame(frames: list[StackFrame], framework_packages: list[str]) -> StackFrame | None`，从顶往下找第一个不在排除列表的帧
  - [ ] 3.4: 编写 `tests/test_stack_parser.py`，验证 canonical example 堆栈解析正确，业务顶帧为 `Demo.printName`
- 验收标准:
  - [ ] `pytest tests/test_stack_parser.py -v` 全部通过

---

### 任务 4: [x] 源码索引

- 文件:
  - `src/source_index.py`（新建）
  - `tests/test_source_index.py`（新建）
- 依赖: Task 1
- spec 映射: spec §4.10（SourceIndex 组件、Maven 标准目录假设）
- 说明: 启动时扫描源码目录，建立 `ClassName → 绝对文件路径` 索引，支持 Maven 标准目录结构。
- context:
  - `src/source_index.py` — 直接新建；下游：Task 5（`read_source` 用于路径解析）、Task 6（agent state 中持有）
- 子任务:
  - [ ] 4.1: 实现 `SourceIndex` 类，`__init__(src_dir: str, extra_roots: list[str])` 接受源码根目录；`build() -> None` 遍历所有 `.java` 文件，提取类名（文件名去 `.java` 后缀）→ 绝对路径的映射
  - [ ] 4.2: 实现 `resolve(class_name: str) -> str | None`，支持简单类名（`Demo`）和全限定名（`com.company.Demo`，取最后一段匹配）
  - [ ] 4.3: 编写 `tests/test_source_index.py`，以 `tests/fixtures/src/` 为根目录，验证 `Demo` 能被正确解析到 `Demo.java` 的绝对路径
- 验收标准:
  - [ ] `pytest tests/test_source_index.py -v` 全部通过

---

### 任务 5: [x] 工具实现（read_source + find_callers）

- 文件:
  - `src/tools/__init__.py`（新建）
  - `src/tools/read_source.py`（新建）
  - `src/tools/find_callers.py`（新建）
  - `tests/test_tools.py`（新建）
- 依赖: Task 4
- spec 映射: spec §4.9（M1 可用工具）、§4.7（源码截取 ±20 行）
- 说明: 实现供 LangGraph agent 调用的两个工具函数，包装为 LangChain `@tool` 装饰器格式。工具内部通过闭包引用 `SourceIndex` 实例，不从全局状态读取。
- context:
  - `src/tools/read_source.py` — 上游：`src/source_index.py`；下游：Task 6（agent tool list）
  - `src/tools/find_callers.py` — 上游：接受 `src_dir`；下游：Task 6
- 子任务:
  - [ ] 5.1: 实现 `make_read_source_tool(index: SourceIndex) -> Tool`，返回一个 `@tool` 函数，签名 `read_source(class_name: str, start_line: int, end_line: int) -> str`；用 `index.resolve()` 解析类名，读取文件指定行（含边界保护），返回带行号的代码片段
  - [ ] 5.2: 实现 `make_find_callers_tool(src_dir: str) -> Tool`，返回一个 `@tool` 函数，签名 `find_callers(method_name: str) -> str`；用 `grep` 递归搜索 `src_dir` 下所有 `.java` 文件中出现 `method_name(` 的位置，返回 `file:line` 列表（最多 20 条）
  - [ ] 5.3: 编写 `tests/test_tools.py`，验证：`read_source("Demo", 1, 10)` 返回含代码内容的字符串；`find_callers("printName")` 返回含 `Demo.java` 的结果
- 验收标准:
  - [ ] `pytest tests/test_tools.py -v` 全部通过
  - [ ] `find_callers` 返回结果条数 ≤ 20

---

### 任务 6: [x] DiagnosisAgent（LangGraph ReAct）

- 文件:
  - `src/agent/__init__.py`（新建）
  - `src/agent/prompts.py`（新建）
  - `src/agent/diagnosis_agent.py`（新建）
- 依赖: Task 2, Task 3, Task 4, Task 5, Task 7
- spec 映射: spec §4.2（回溯循环骨架）、§4.5（嫌疑变量策略）、§4.6（码内/码外判定）、§4.7（上下文控制）、§4.8（落盘格式）、§4.10（明确写算法进提示词、max_steps）
- 说明: 核心诊断 agent。用 `langgraph.prebuilt.create_react_agent` 构建 ReAct 图。系统提示词明确写入回溯算法步骤（嫌疑变量定位 → 码内/码外判定 → 调工具 → 终止条件）。通过第三个工具 `submit_diagnosis` 强制结构化输出，agent 调用此工具时图终止。
- context:
  - `src/agent/prompts.py` — 产出系统提示词字符串；下游：`diagnosis_agent.py`
  - `src/agent/diagnosis_agent.py` — 上游：prompts、tools（Task 5）、Config（Task 2）；下游：Task 8 CLI
- 子任务:
  - [ ] 6.1: 在 `prompts.py` 实现 `build_system_prompt() -> str`，明确包含：①角色定义；②回溯算法步骤（找业务顶帧→定位嫌疑变量→按异常类型推断→码内/码外判定规则）；③终止条件（坐实根因/到达码外/超过 max_steps）；④强制要求最终调用 `submit_diagnosis` 工具
  - [ ] 6.2: 实现 `make_submit_diagnosis_tool() -> Tool`，签名接收 `root_cause_hypothesis`、`evidence`（list）、`counter_check`、`fix_direction`、`confidence`、`confidence_reason`，将参数存入模块级变量后抛出 `DiagnosisComplete` 异常终止图（或返回特殊标记）
  - [ ] 6.3: 在 `diagnosis_agent.py` 实现 `DiagnosisAgent` 类，`__init__` 接收 `Config`、`SourceIndex`、`src_dir`；`run(stack_trace: str, frames: list[StackFrame]) -> DiagnosisReport` 组装工具列表，调用 `create_react_agent`，传入系统提示词，执行并解析输出为 `DiagnosisReport`
  - [ ] 6.4: 每步工具调用后追加 checkpoint 到 `workspace/diagnosis/<id>.json`（append 模式，行级 JSON）
- 验收标准:
  - [ ] `python -c "from src.agent.diagnosis_agent import DiagnosisAgent"` 无异常
  - [ ] 无需真实 API 的单元级烟雾测试：mock LangGraph 调用，验证工具列表包含三个工具（read_source、find_callers、submit_diagnosis）

---

### 任务 7: [x] 报告输出（ReportWriter）

- 文件:
  - `src/report_writer.py`（新建）
- 依赖: Task 1
- spec 映射: spec §3.1（终端打印摘要 + JSON 落盘）、§4.8（落盘格式）
- 说明: 将 `DiagnosisReport` 写成两种形式：终端可读摘要（根因+置信度+修复方向）和完整 JSON 文件。
- context:
  - `src/report_writer.py` — 上游：`src/models.py`（DiagnosisReport）；下游：Task 8 CLI
- 子任务:
  - [ ] 7.1: 实现 `print_summary(report: DiagnosisReport) -> None`，终端打印：根因假设、置信度（含理由）、修复方向；若 `conclusion` 为 None（诊断未完成），打印当前状态
  - [ ] 7.2: 实现 `write_json(report: DiagnosisReport, path: str) -> None`，将 report 序列化为符合 spec §4.8 格式的 JSON，写入指定路径（使用 `dataclasses.asdict`）
- 验收标准:
  - [ ] `python -c "from src.report_writer import print_summary, write_json"` 无异常
  - [ ] 用 mock DiagnosisReport 调用 `print_summary`，终端输出含「根因」「置信度」「修复方向」三个字段

---

### 任务 8: [x] CLI 入口（diagnose.py）

- 文件:
  - `diagnose.py`（新建）
- 依赖: Task 2, Task 3, Task 4, Task 5, Task 6, Task 7
- spec 映射: spec §3.1（CLI 接口：`--stack`、`--src`、`--config`）、§4.10（数据流）
- 说明: 串联所有组件的命令行入口，按数据流顺序：加载配置 → 解析堆栈 → 构建源码索引 → 运行 agent → 输出报告。
- context:
  - `diagnose.py` — 调用所有 src/ 模块；无下游（顶层入口）
- 子任务:
  - [ ] 8.1: 用 `argparse` 定义 CLI 参数：`--stack`（堆栈文件路径，必填）、`--src`（源码目录，必填）、`--config`（配置文件，默认 `config.yaml`）
  - [ ] 8.2: 实现主流程：`load_config` → `parse_stack_trace` → `find_business_top_frame` → `SourceIndex.build` → `DiagnosisAgent.run` → `print_summary` + `write_json`
  - [ ] 8.3: 错误处理：堆栈文件不存在 → 清晰错误信息退出；源码目录不存在 → 清晰错误信息退出；未找到业务顶帧 → 提示并退出
- 验收标准:
  - [ ] `python diagnose.py --help` 显示参数说明无报错
  - [ ] `python diagnose.py --stack 不存在.txt --src .` 打印错误信息，退出码非 0

---

### 任务 9: [x] 集成测试（canonical example）

- 文件:
  - `tests/test_integration.py`（新建）
- 依赖: Task 8
- spec 映射: spec §4.4（canonical example 验收）、§4.10（验收标准）
- 说明: 以 canonical NPE 例子（Demo.java）端到端验证 M1 诊断骨架。需要真实 ANTHROPIC_API_KEY。
- context:
  - `tests/test_integration.py` — 调用 `diagnose.py` 主流程；输入：Task 3 创建的 fixture 文件
- 子任务:
  - [ ] 9.1: 编写集成测试，直接调用 `DiagnosisAgent.run`（不经 CLI），传入 canonical example 堆栈和 `tests/fixtures/src/` 目录
  - [ ] 9.2: 断言：`report.conclusion` 不为 None；`report.conclusion.confidence` 为 `"high"`；`report.conclusion.root_cause_hypothesis` 包含 `"null"` 或 `"handle"` 关键词；`report.conclusion.fix_direction` 非空
  - [ ] 9.3: 验证 JSON 落盘文件存在且可被 `json.load` 解析
- 验收标准:
  - [ ] `pytest tests/test_integration.py -v -m integration`（需设置 `ANTHROPIC_API_KEY`）全部通过
  - [ ] 落盘 JSON 文件符合 spec §4.8 格式（包含 `diagnosis_id`、`status`、`backtrace_steps`、`conclusion` 字段）

---

## Spec 覆盖映射

| Spec 章节 | 任务 | 说明 |
|-----------|------|------|
| §3.1 F1 输入（CLI 接口） | Task 8 | `--stack`、`--src`、`--config` 参数 |
| §3.1 F1 输出（终端+落盘） | Task 7, 8 | ReportWriter + CLI 串联 |
| §3.2 上下文控制 | Task 5, 6 | 源码截取 ±20 行；每步 checkpoint |
| §4.2 回溯循环骨架 | Task 6 | 系统提示词 + ReAct 图 |
| §4.3 证据链结构 | Task 1, 6, 7 | DiagnosisReport 模型 + submit_diagnosis + 报告输出 |
| §4.4 canonical example | Task 3, 9 | fixture 文件 + 集成测试 |
| §4.5 嫌疑变量定位策略 | Task 3, 6 | find_business_top_frame + 系统提示词 |
| §4.6 码内/码外判定 | Task 6 | 系统提示词中的判定规则 |
| §4.7 上下文控制落点 | Task 5, 6 | read_source 截取逻辑 + checkpoint |
| §4.8 状态/落盘格式 | Task 1, 6, 7 | 数据模型 + 写盘逻辑 |
| §4.9 工具清单 | Task 5 | read_source + find_callers |
| §4.10 实现架构（组件、数据流、关键决策） | Task 1–8 全覆盖 | — |
