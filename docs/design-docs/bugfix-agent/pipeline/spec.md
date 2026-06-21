# Feature: 工具增强的根因诊断与人在环（HITL）修复流水线

**作者**: michaeltesla1995
**日期**: 2026-06-19
**状态**: Draft

---

## 1. 背景 (Background)

### 1.1 问题描述

线上系统出现异常，抛出一个**异常堆栈**。这是排查的**唯一起点**——不知道是什么问题，也不知道根因在哪。

堆栈告诉你：异常类型、抛出位置、调用链；但**不告诉你为什么**。要回答「为什么出错」，需要结合源码逻辑、DB 里的实际数据状态、运行时日志等多方信息综合推断。

排查过程通常是：看堆栈 → 读源码 → 按需查 DB / 日志 / 接口 / 反编译 → 综合推断根因。过程**复杂、耗时、强依赖资深经验**。

**期望**：用一个能调度上述信息源的 agent，承担「看堆栈 → 读码 → 按需取证 → 定位根因 → 提修复方案」的重活，人专注 review 与拍板。

### 1.2 现状分析

- 本项目（`bughunterv2`）是**全新的 Python 3 工具**，目录为空，无现有代码。被它分析/修复的是一个独立的目标项目（Java + Maven + SVN）。
- **核心能力依赖一组外部工具**：查询 DB 表数据、查看堆栈、查看日志、调用接口、反编译、SVN、构建。这些工具**涉及公司数据/环境，需单独对接**；前期一律用 **mock 占位**，按统一接口契约实现，真实实现后可热替换。部分操作前期可由老板**手工执行**。
- **构建/验证**：经 IDEA MCP `build_project`，或老板提供命令行启动命令；**编译由老板手工触发**，编译报错可回灌给 agent 迭代。
- **源码访问**：可配置源码目录。
- **隔离思路**（老板提出，细节待设计）：从主分支拉一份**独立工作区目录**作为 agent 的改动区，避免污染主工作副本；SVN 操作可作为工具提供给 agent，或老板手工执行。

**Agent 框架**：LangChain Deep Agents（基于 LangGraph），内置 planning / 文件系统工具 / 子 agent / context 管理。

**已识别的关键矛盾**：构建依赖 IDEA，而 IDEA 构建的是其当前打开的目录；隔离副本需让构建能作用到改动上。此点列入设计阶段专项讨论。

### 1.3 主要使用场景（人在环迭代循环）

```
输入异常堆栈
  → agent 结合源码 + 按需调用工具（DB/日志/接口/反编译）诊断
  → 产出：根因结论 + 支撑证据 + 修复方案
  → 老板 review（可提修改意见）
  → agent 修改（落到隔离工作区）
  → 再 review
  → 老板手工触发编译
      ├─ 失败：编译报错回灌 agent → 再分析 → 再改
      └─ 通过 ↓
  → 老板手工测试，确认问题修复
  → 纳入版本管理（工作区提交 / 合回主分支）
```

特征：**多处人工 gate**；流程**可暂停、可恢复**；**各阶段产出落盘**。前期形态为**各阶段独立接口，由人工手动串联**。

## 2. 目标 (Goals)

把线上 bug 的根因诊断与修复，从**纯人工**转为「**agent 主导分析 + 人 review 拍板**」的协作模式，显著降低资深人力投入与排查耗时。

> 可量化指标待老板补充（如：对一类典型 bug，给出可信根因 + 修复方案的耗时 / 人工步骤数下降）。

### 2.1 非目标 (Non-Goals)

- 不做端到端全自动：保留人工确认、人工编译、人工测试等 gate。
- 前期不接真实公司环境：外部工具全部用 mock。
- 不追求「能修复任意 bug」：接受部分 bug 只给到诊断结论。
- 不做无证据的「猜测式」修改。

## 3. 需求细化 (Requirements)

### 3.1 功能性需求

前期把每个阶段做成**独立接口**，可单独调用、产出落盘、人工串联。

- **F1 诊断（工具增强，核心）**：
  - **输入**：命令行参数 `--stack <堆栈文件路径> --src <源码目录>`；配置文件指定框架包排除列表。
  - **执行**：agent 以 ReAct 方式带着假设按需调工具取最小必要数据。
  - **输出**：终端打印摘要（根因结论 + 置信度 + 修复方向）；完整证据链写入 `workspace/diagnosis/<id>.json`。
- **F2 生成修复方案**：基于诊断给出具体改法（diff / 伪 patch）+ 影响范围；支持接收人工意见后修订。
- **F3 应用修改**：把确认后的改动落地到隔离工作区。
- **F4 编译反馈环**：接收人工编译结果；失败时解析报错 → 重新定位 → 再修。
- **F5 测试 / 验证**：以人工测试为主；agent 可辅助生成单测（是否需要待定）。
- **F6 版本纳入**：工作区改动提交 / 合回（SVN 工具，半自动，敏感操作需人工确认）。
- **横切**：每阶段产出结构化、可落盘、可恢复；所有工具遵循**统一契约**，mock 与真实实现可热替换。

### 3.2 非功能性需求

- **上下文控制（关键）**：源码不整文件读入，每次仅取目标方法体 ± 20 行。引入外部数据工具（本地 DB、线上日志）后，大结果落盘，context 仅留摘要 + 引用，工具层强制返回规模上限。
- **工具可替换**：mock 与真实实现遵循同一契约。
- **可恢复 / 状态化**：HITL 长流程可中断、续跑。
- **安全**：写库、调真实接口、提交等敏感操作必须人工 gate。
- **文档沉淀**：作为项目第二大块（见 `docs/README.md`），规范 / 标准 / 决策需持续沉淀。
- **不过度设计**：前期手工串联各阶段接口，不强求自动编排。

## 4. 设计方案 (Design)

> 状态：草案，随设计推进演进。本章自 2026-06-19 起填写（聚焦 M1 诊断）。

### 4.1 核心洞察

**抛出点 ≠ 根因点。** 诊断的本质是「**沿调用链回溯，找坏值的源头**」。异常堆栈栈顶只是「症状发作的位置」，根因可能在调用链更深处，甚至在代码之外（数据库 / 接口 / 配置）。

### 4.2 诊断骨架：统一回溯循环（F1 核心）

```
读堆栈 → 定位嫌疑变量 → 回溯它从哪来
   ├─ 来源在代码内              → 继续读码，顺数据流回溯
   └─ 来源在代码外（DB/接口/配置）→ 调工具取证（查表 / 查日志 / 调接口 / 反编译）
→ 直到坐实根因，或线索耗尽 → 输出证据链
```

- **简单 bug 是该循环的退化情况**：回溯几步在代码内到底，不触发工具。
- **复杂 bug 是完整情况**：回溯到某变量来自一次 DB 查询等外部来源，触发工具取证。
- 二者走**同一套循环** → 从最简例子起步即可搭通骨架，且骨架天然适配复杂场景。

### 4.3 证据链结构（F1 输出）

| 字段 | 含义 |
|------|------|
| 根因假设 | 一句**可证伪**的原因陈述 |
| 支撑证据 | 具体到「哪行代码 / 哪条数据」的证据列表 |
| 反证检查 | 主动排除其他可能、确认假设的唯一性 |
| 修复方向 | 修复思路（具体改法属 F2，不在 F1 内） |

### 4.4 首个验证案例（canonical example）

最小 NPE 例子，作为 M1 诊断的第一个回归样例（坏值源头是「代码写死的 null」，回溯全程不离开源码，是退化情况）：

```java
public class Demo {
    public static void main(String[] args) { handle(); }
    static void handle() { printName(null); }
    static void printName(String name) { System.out.println(name.length()); }
}
```
```
Exception in thread "main" java.lang.NullPointerException
    at Demo.printName(Demo.java:10)   // 抛出点：name 为 null
    at Demo.handle(Demo.java:6)       // 根因点：printName(null) 写死传 null
    at Demo.main(Demo.java:2)
```

期望证据链：`假设 name 实参为 null` + `证据①第10行 name.length() 是唯一 NPE 处、②第6行 printName(null) 传入 null` + `反证：name 无其他赋值路径，假设唯一成立` + `修复方向：handle 不传 null 或 printName 加防御`。

> 复杂场景的对照：若第 6 行是 `printName(userDao.findById(id).getName())`，代码无错，根因在「表里那条数据」，回溯会**跳出代码去查表**——这就是 M1 诊断的核心价值所在，也是后续要补的验证案例。

### 4.5 嫌疑变量定位策略

**目标**：从堆栈 + 对应代码行，确定回溯循环的第一个嫌疑变量。

**步骤**：

1. **找业务顶帧**：从堆栈顶往下扫，跳过配置文件中声明的框架包前缀（默认含 `java.*`、`javax.*`、`org.springframework.*`、`com.sun.*`、`sun.*` 等，可扩展），取第一个不在排除列表里的帧视为业务帧。
2. **读对应代码行**：取该帧指向的源码行（± 5 行上下文）。
3. **按异常类型推断嫌疑变量**：

| 异常类型 | 嫌疑变量推断规则 |
|----------|------------------|
| `NullPointerException` | 被解引用（`.`）的那个表达式 |
| `ArrayIndexOutOfBoundsException` | 数组变量，或 index 表达式 |
| `ClassCastException` | 被强转的对象变量 |
| `IllegalArgumentException` / 自定义业务异常 | 触发 `throw` 的条件所涉变量 |
| 其他 | 读代码 + 异常 message 综合判断（随案例积累） |

4. **链式调用拆解**：若代码行含多链式调用（如 `a.getB().getC().size()`），从最内层逐段检查，锁定第一个可能为 null / 非法的子表达式。

### 4.6 码内 / 码外判定

**目标**：定位到嫌疑变量的赋值处后，判定「继续读码」还是「调工具取证」。

判定依据是嫌疑变量的**赋值语句右侧**：

**码内**（继续读码，顺调用链上溯）：
- 字面量赋值：`String name = "alice"`、`printName(null)`
- 本地运算 / 条件表达式
- 方法形参——该变量来自调用方，往上一帧继续回溯
- 系统内部 RPC 调用——有本地源码，继续追被调方实现
- 本地文件读取——可读取文件内容继续追
- 配置注入（`@Value`、`Environment.getProperty()`）——值来自本地配置文件，可读取继续追
- 调用了非 DAO 的内部 Service 方法——读该 Service 源码继续追

**码外**（M1 阶段：记录该节点、停止该分支；后续里程碑：调工具取证）：
- 返回值来自 DAO / Repository / Mapper 方法调用（如 `userDao.findById(id)`）——依赖运行时 DB 数据
- 返回值来自外部 HTTP 接口（非系统内部，无本地源码可追）
- 来自消息队列消费（运行时数据，无法静态追溯）
- 来自外部缓存（运行时数据）

### 4.7 上下文控制落点

**原则**：源码不整文件读入；每步结束 checkpoint，支持中断续跑。

| 时机 | 控制动作 |
|------|----------|
| 读源码时 | 每次仅取目标方法体 ± 20 行，不整文件读入 |
| 每步回溯结束时 | 将本步状态 checkpoint 追加写入诊断落盘文件（支持中断续跑） |

> M1 无外部数据工具，暂无「大结果落盘」场景。引入外部工具后（本地 DB、线上日志），补充对应的 limit / 落盘规则。

### 4.8 状态 / 落盘格式

**文件路径**：`workspace/diagnosis/<diagnosis_id>.json`

每步回溯结束后追加写入，支持从任意步断点续跑。

```json
{
  "diagnosis_id": "uuid",
  "created_at": "ISO8601",
  "status": "in_progress | completed | paused",
  "input": {
    "stack_trace": "原始堆栈文本",
    "source_dir": "/path/to/src"
  },
  "backtrace_steps": [
    {
      "step": 1,
      "suspect_variable": "name",
      "location": { "file": "Demo.java", "line": 10, "method": "printName" },
      "decision": "in_code",
      "finding": "name 由调用方 handle() 以字面量 null 传入",
      "evidence": [
        { "type": "code", "file": "Demo.java", "line": 6, "snippet": "printName(null)" }
      ],
      "tool_calls": []
    }
  ],
  "conclusion": {
    "root_cause_hypothesis": "handle() 在第 6 行以字面量 null 调用 printName，导致 name 为 null",
    "evidence_refs": ["backtrace_steps[0].evidence[0]"],
    "counter_check": "name 无其他赋值路径，假设唯一成立",
    "fix_direction": "handle() 不传 null，或 printName() 对 null 做防御",
    "confidence": "high",
    "confidence_reason": "证据直接（代码行明确），反证覆盖主要替代假设"
  }
}
```

**字段说明**：

- `status`：`in_progress` = 回溯未完成可续跑；`completed` = 已输出证据链；`paused` = 在人工 gate 处等待确认（M1 暂不使用）。
- `tool_calls`：本步骤调用工具的记录（名称、参数、结果文件路径）；码内回溯时为空数组。
- `confidence` 取值：`high` = 证据直接且反证完整；`medium` = 证据间接或反证不完整；`low` = 线索耗尽但未坐实根因。

### 4.9 工具清单与环境约束

#### M1 可用工具（纯代码分析）

| 工具名 | 用途 | 关键参数 |
|--------|------|----------|
| `read_source` | 读取源码片段 | `file`, `start_line`, `end_line` |
| `find_callers` | 查找方法的调用点 | `method_signature` |

#### 后续可引入工具（按里程碑演进）

| 工具名 | 用途 | 可用时机 |
|--------|------|----------|
| `start_local_server` | 启动本地服务，尝试复现问题 | 本地环境搭好后 |
| `query_local_db` | 查询本地 DB 数据（复现用） | 本地服务可跑后 |
| `search_logs` | 搜索线上日志 | 长期目标 |
| `decompile_class` | 反编译 class | 待评估 |

**永久约束**：线上 DB 不可查询，不纳入任何里程碑的工具范围。

#### 码外来源的处理（M1 行为）

回溯到「码外来源」（如 `userDao.findById(id)` 的返回值）时，agent **记录该节点并停止该分支回溯**，在证据链中标注：「根因疑似在数据层 [具体位置]，当前环境无法验证」，置信度降为 `low`。不暂停流程，不请求人工介入。

所有工具遵循统一契约：工具外部返回人类可读文本，失败时返回带 `[tool_name]` 前缀的错误字符串；完整契约见 `docs/standards/tool-contract.md`。

### 4.10 M1 实现架构

#### 核心组件

| 组件 | 职责 |
|------|------|
| `diagnose.py` | CLI 入口，解析 `--stack`、`--src`、`--config` 参数，串联各组件 |
| `config.yaml` | 框架包排除列表、`max_steps` 等运行参数 |
| `SourceIndex` | 启动时扫描 `--src` 目录，建立 `ClassName → 绝对文件路径` 索引 |
| `StackParser` | 解析 Java 堆栈文本 → 结构化帧列表 `[{class, method, file, line}]` |
| `DiagnosisAgent` | LangGraph ReAct 图，执行回溯循环 |
| `read_source` | 读取源码片段工具 |
| `find_callers` | 查找方法调用点工具（grep 实现） |
| `ReportWriter` | 终端摘要输出 + JSON 落盘 |

#### 数据流

```
CLI 参数 + config.yaml
  → SourceIndex: 遍历 --src 目录 → {ClassName: "/abs/path/Foo.java"}
  → StackParser: 堆栈文本 → [{class, method, file, line}, ...]
  → DiagnosisAgent (LangGraph ReAct):
        系统提示词: 回溯算法 + 码内/码外规则 + 工具说明（明确写算法，不依赖 LLM 自由发挥）
        State: {frames, source_index, backtrace_steps[], status}
        ReAct 循环（上限 max_steps 步）:
          read_source(file, start_line, end_line) → 代码片段
          find_callers(method_signature) → [file:line, ...]
        终止: 坐实根因 | 到达码外 | 超过 max_steps
  → ReportWriter:
        终端: 根因结论 + 置信度 + 修复方向
        文件: workspace/diagnosis/<uuid>.json
```

#### 关键实现决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| `find_callers` 实现 | **文本 grep**（搜索方法名字符串） | 简单无额外依赖；误报由 LLM 读码后自行判断过滤；M1 够用 |
| 类名 → 文件路径解析 | **假设 Maven 标准目录结构** `src/main/java/{pkg}/{Class}.java` | 覆盖目标项目的实际情况；非标路径通过配置项补充 |
| 系统提示词策略 | **明确写入回溯算法步骤** | M1 是确定性任务，减少 LLM 幻觉；不依赖 LLM 自主发现算法 |
| 回溯最大步数 | **`max_steps = 10`**（配置项可覆盖） | 防止死循环 / token 爆炸；超出则置信度降为 `low` 并停止 |
