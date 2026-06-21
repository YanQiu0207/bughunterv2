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

---

# 实施任务清单 — ADR-0004 干净 SVN 缓存副本隔离实现

> 由 ADR-0004、`docs/standards/tool-contract.md` 与本 `spec.md` 生成
> 任务总数：5
> 核心原则：先建后迁后删——先补配置契约，再迁移 `apply_fix` 隔离来源，最后更新调用方、测试与文档核销

## 依赖关系总览

```text
Task 10 (配置扩展与 CLI 校验)
  ↓
Task 11 (apply_fix 从干净 SVN 缓存复制工作区)
  ↓
Task 12 (FixAgent 调用方与输出文案迁移)
  ↓
Task 13 (测试覆盖与回归)
  ↓
Task 14 (intent 沉淀核销与文档同步检查)
```

并行机会：无。`apply_fix` 工厂签名、配置字段、调用方与测试互相依赖，保守串行。

## 变更影响概览

### 文件变更清单

| 文件 | 操作 | 涉及任务 | 说明 |
|------|------|---------|------|
| `src/config.py` | 修改 | Task 10 | 新增 `svn_url`、`svn_cache_dir` 配置字段与默认值 |
| `config.yaml` | 修改 | Task 10 | 增加 SVN 缓存副本配置示例与注释 |
| `fix.py` | 修改 | Task 10, 12 | 校验 `svn_cache_dir`；更新验收后提示文案 |
| `src/tools/apply_fix.py` | 修改 | Task 11 | 从硬链接目标目录改为复制干净 SVN 缓存副本 |
| `src/agent/fix_agent.py` | 修改 | Task 12 | 注册 `apply_fix` 时传入 `config.svn_cache_dir` |
| `tests/test_config.py` | 修改 | Task 10, 13 | 覆盖新增配置字段 |
| `tests/test_fix_tools.py` | 修改 | Task 11, 13 | 更新硬链接相关测试，新增缓存干净检查 |
| `tests/test_fix_agent.py` | 修改 | Task 12, 13 | 更新 `_make_config` 与调用方断言 |
| `docs/adr/0004-svn-clean-cache-isolation-strategy.md` | 核对 | Task 14 | 若实现取舍变化，回填决策说明 |
| `docs/standards/tool-contract.md` | 核对 | Task 14 | 确认工具契约与实现一致 |
| `docs/roadmap.md` | 核对 | Task 14 | 实现完成后更新 M2 待办状态 |
| `docs/design-docs/bugfix-agent/pipeline/e2e-manual-acceptance.md` | 核对 | Task 14 | 确认验收步骤与实现一致 |
| `CLAUDE.md` | 核对 | Task 14 | 确认 Claude Code 入口提示与实现一致 |

### 受影响接口

| 接口 | 变更类型 | 调用方 | 涉及任务 |
|------|---------|--------|---------|
| `Config` | 新增字段 | `fix.py`, `src/agent/fix_agent.py`, 测试 | Task 10, 12, 13 |
| `load_config(path)` | 读取字段扩展 | 所有 CLI 入口 | Task 10, 13 |
| `make_apply_fix_tool(workspace_root, target_project_dir)` | 签名语义变更为 `make_apply_fix_tool(workspace_root, svn_cache_dir)` | `FixAgent.run()`、测试 | Task 11, 12, 13 |
| `apply_fix(fix_id, edits)` | 行为变更 | LLM 工具调用、测试 | Task 11, 13 |

### 构建系统变更

- 无新增 Python 包依赖。
- 新增 `svn status` 调用依赖本机已安装 SVN CLI；单元测试必须 mock，不依赖真实 SVN。

## 风险与假设

| # | 描述 | 影响任务 | 假设/处理 |
|---|------|---------|----------|
| 1 | 是否自动 `svn checkout` 初始化缓存副本 | Task 10, 11 | 本轮只消费已存在的 `svn_cache_dir`，不自动 checkout；`svn_url` 先作为预留字段，不作为 `fix.py` 必填 |
| 2 | `workspace/fix/<fix_id>` 是否保留 `.svn` | Task 11, 13 | 默认普通复制整个缓存副本，保留 `.svn`；仍禁止编辑 dot-path，避免修改元数据 |
| 3 | 缓存副本干净性依赖 SVN CLI | Task 11, 13 | 每次应用修改前执行 `svn status <svn_cache_dir>`；非零退出或 stdout 非空均拒绝创建或修改工作区 |
| 4 | 重复调用 `apply_fix` 的恢复基线 | Task 11, 13 | 继续使用 `.fix_modified_files` registry，但恢复来源从 `target_project_dir` 改为 `svn_cache_dir` |
| 5 | 现有文档已先于代码切换到 ADR-0004 | Task 14 | 代码实现完成后核对并去掉旧的待同步提示 |

## 任务列表

### 任务 10: [x] 配置扩展与 `fix.py` 校验

- 状态: 完成
- 文件:
  - `src/config.py`（修改）
  - `config.yaml`（修改）
  - `fix.py`（修改）
  - `tests/test_config.py`（修改）
- 依赖: 无
- spec 映射: spec §3.1（F3 应用修改）、§3.2（安全）、ADR-0004（干净 SVN 缓存副本配置）
- 说明: 增加 SVN 缓存副本相关配置字段，`fix.py` 在进入修复流程前校验 `svn_cache_dir` 已配置；`svn_url` 仅作为后续自动初始化缓存的预留配置。
- context:
  - `src/config.py:Config` — 直接修改目标，新增字段与默认值
  - `src/config.py:load_config()` — 上游配置解析，给 CLI 与 Agent 传入运行参数
  - `config.yaml` — 用户配置入口
  - `fix.py:main()` — 下游校验配置并创建 `FixAgent`
  - `tests/test_config.py` — 配置加载回归测试
- 验收标准:
  - [x] `python -c "from src.config import load_config; c = load_config('config.yaml'); assert c.svn_cache_dir"` 执行无异常
  - [x] `python -m pytest tests/test_config.py -q` 通过
  - [x] `Select-String -Path .\\fix.py -Pattern "svn_cache_dir"` 能找到校验逻辑
- 子任务:
  - [x] 10.1: 在 `Config` 增加 `svn_url: str` 与 `svn_cache_dir: str`
  - [x] 10.2: 在 `load_config()` 中解析新增字段，缺省值分别为 `""` 与 `"workspace/cache/svn-clean"`
  - [x] 10.3: 在 `config.yaml` 增加 `svn_url`、`svn_cache_dir` 示例与中文注释
  - [x] 10.4: 在 `fix.py` 必填校验中加入 `svn_cache_dir`，但不强制 `svn_url`
  - [x] 10.5: 更新 `tests/test_config.py` 覆盖默认值与显式配置值

### 任务 11: [x] `apply_fix` 从干净 SVN 缓存复制工作区

- 状态: 完成
- 文件:
  - `src/tools/apply_fix.py`（修改）
  - `tests/test_fix_tools.py`（修改）
- 依赖: Task 10
- spec 映射: spec §3.1（F3 应用修改）、§3.2（安全）、ADR-0004（隔离工作区创建与安全约束）
- 说明: 将 `apply_fix` 的工作区创建来源从 `target_project_dir` 硬链接复制改为 `svn_cache_dir` 普通复制；每次应用修改前检查缓存副本是干净 SVN 工作副本。
- context:
  - `src/tools/apply_fix.py:make_apply_fix_tool()` — 直接修改目标，调整参数语义与 workspace 创建逻辑
  - `src/tools/apply_fix.py:apply_fix()` — 下游 LLM 工具调用入口
  - `src/tools/apply_fix.py:_load_modified_registry()` — 重复调用恢复状态依赖
  - `tests/test_fix_tools.py:TestApplyFix` — 行为回归测试
- 验收标准:
  - [x] `python -m pytest tests/test_fix_tools.py -q` 通过
  - [x] mock `subprocess.run(["svn", "status", svn_cache_dir], ...)` 返回 stdout 非空时，`apply_fix` 返回错误且不创建 `workspace/fix/<fix_id>`
  - [x] 缓存源文件内容在 `apply_fix` 后保持不变
  - [x] 第二轮 `apply_fix` 从 `svn_cache_dir` 基线恢复，而不是叠加第一轮修改
- 子任务:
  - [x] 11.1: 将工厂参数语义改为 `workspace_root, svn_cache_dir`
  - [x] 11.2: 新增缓存干净检查：每次应用修改前执行 `svn status <svn_cache_dir>`，非零退出或 stdout 非空均返回错误
  - [x] 11.3: 首次创建 `workspace/fix/<fix_id>` 时使用普通 `shutil.copytree(svn_cache_dir, workspace_path)`
  - [x] 11.4: 重复调用时用 `svn_cache_dir` 恢复 registry 中记录的已修改文件
  - [x] 11.5: 保留路径穿越、dot-path、编辑数量、内容大小、原子写入与重叠范围校验
  - [x] 11.6: 更新 `tests/test_fix_tools.py`，删除硬链接 inode 专属断言，改为缓存副本不变与恢复基线断言

### 任务 12: [x] 迁移 `FixAgent` 调用方与输出文案

- 状态: 完成
- 文件:
  - `src/agent/fix_agent.py`（修改）
  - `fix.py`（修改）
  - `tests/test_fix_agent.py`（修改）
- 依赖: Task 11
- spec 映射: spec §3.1（人在环迭代循环）、ADR-0004（最终写回仍由 `target_project_dir` 承担）
- 说明: `FixAgent` 注册 `apply_fix` 时使用 `config.svn_cache_dir`；用户提示中区分「最终目标工作副本」与「干净缓存副本」；CLI 汇总文案不再推荐硬链接时代的原目录 diff。
- context:
  - `src/agent/fix_agent.py:FixAgent.run()` — 上游创建工具列表
  - `src/agent/fix_agent.py:_build_user_message()` — LLM 输入提示，消费配置语义
  - `fix.py:_print_summary()` — 下游人工 review 入口提示
  - `tests/test_fix_agent.py` — 调用方结构回归测试
- 验收标准:
  - [x] `python -m pytest tests/test_fix_agent.py -q` 通过
  - [x] `Select-String -Path .\\src\\agent\\fix_agent.py -Pattern "svn_cache_dir"` 能找到传参逻辑
  - [x] `fix.py` 不再输出旧的原目录 diff 提示
- 子任务:
  - [x] 12.1: `FixAgent.run()` 调用 `make_apply_fix_tool(self._workspace_root, self._config.svn_cache_dir)`
  - [x] 12.2: `_build_user_message()` 保留 `target_project_dir` 作为最终提交目录，并补充缓存副本路径说明
  - [x] 12.3: `_print_summary()` 改为提示 review `workspace/fix/<fix_id>`，后续用 `commit_fix.py --dry-run` / `--yes` 写回
  - [x] 12.4: 更新 `tests/test_fix_agent.py` 的 `_make_config()` 与相关断言

### 任务 13: [x] 测试覆盖与端到端回归

- 状态: 完成
- 文件:
  - `tests/test_config.py`（修改）
  - `tests/test_fix_tools.py`（修改）
  - `tests/test_fix_agent.py`（修改）
  - `tests/test_commit_fix.py`（按需修改）
- 依赖: Task 12
- spec 映射: spec §3.2（安全）、ADR-0004（验收与拒绝条件）
- 说明: 补齐 ADR-0004 行为的测试覆盖，并跑全量非集成回归，确认 M2 修复隔离实现没有破坏 M1/M3A。
- context:
  - `tests/test_fix_tools.py:TestApplyFix` — 直接验证缓存复制、dirty 拒绝、重复调用恢复
  - `tests/test_fix_agent.py:TestFixAgentStructure` — 验证调用方注册工具不触发 LLM
  - `tests/test_config.py` — 验证配置默认值与显式值
  - `tests/test_commit_fix.py` — 下游 M3A 写回链路，确认无需同步改动或完成必要调整
- 验收标准:
  - [x] `python -m pytest -q -m "not integration"` 通过
  - [x] `python -m py_compile src\\config.py src\\tools\\apply_fix.py src\\agent\\fix_agent.py fix.py` 通过
  - [x] `git diff --check` 通过
- 子任务:
  - [x] 13.1: 增加 `svn status` 成功、dirty、命令失败三类 mock 测试
  - [x] 13.2: 增加缓存文件不变、workspace 文件可编辑、跨轮恢复三类行为测试
  - [x] 13.3: 更新调用方测试，确保 `FixAgent` 能构造四个工具且不触发真实 LLM
  - [x] 13.4: 跑全量非集成回归并修复新增失败

### 任务 14: [x] intent 沉淀核销与文档同步检查

- 状态: 完成
- 文件:
  - `docs/adr/0004-svn-clean-cache-isolation-strategy.md`（核对/按需修改）
  - `docs/standards/tool-contract.md`（核对/按需修改）
  - `docs/roadmap.md`（核对/按需修改）
  - `docs/design-docs/bugfix-agent/pipeline/e2e-manual-acceptance.md`（核对/按需修改）
  - `CLAUDE.md`（核对/按需修改）
  - `docs/design-docs/bugfix-agent/pipeline/tasks.md`（修改状态）
- 依赖: Task 13
- spec 映射: spec §3.2（文档沉淀）、ADR-0004（已接受决策）
- 说明: 实现完成后核对文档中的旧待同步提示是否仍成立，并按 `project-knowledge` 做交付前沉淀检查。
- context:
  - `docs/adr/0004-svn-clean-cache-isolation-strategy.md` — intent 权威来源
  - `docs/standards/tool-contract.md` — 工具行为契约
  - `docs/roadmap.md` — 里程碑状态入口
  - `CLAUDE.md` — Claude Code 协作入口
- 验收标准:
  - [x] 文档中旧的待同步提示已移除；`硬链接` / `hardlink` 命中均为 ADR-0003 历史描述、放弃方案或已明确更新
  - [x] `git diff --check` 通过
  - [x] 交付报告逐条给出沉淀检查结论：架构决策、放弃方案、新红线约束、普通功能变更
- 子任务:
  - [x] 14.1: 将任务状态按实际执行结果更新为「完成 / 需人工 / 阻塞」
  - [x] 14.2: 核对 ADR-0004 与实现差异；若有新增取舍，补充到 ADR
  - [x] 14.3: 更新 roadmap 与验收清单中的「实现待同步」状态
  - [x] 14.4: 执行交付前沉淀检查并在最终汇总中逐条核销

## Spec 覆盖映射

| Spec 章节 / 决策来源 | 任务 | 说明 |
|----------------------|------|------|
| spec §3.1 F3 应用修改 | Task 10, 11, 12 | 配置、隔离工作区创建、调用方迁移 |
| spec §3.1 F6 版本纳入 | Task 12, 14 | CLI 提示保留人工 review 与 `commit_fix.py` 写回路径 |
| spec §3.2 安全 | Task 11, 13 | 缓存干净检查、路径安全、dot-path 拒绝、测试覆盖 |
| spec §3.2 文档沉淀 | Task 14 | ADR-0004 与相关文档核销 |
| ADR-0004 干净 SVN 缓存副本 | Task 10, 11, 12, 13, 14 | 从配置到实现、验证、文档同步全覆盖 |
