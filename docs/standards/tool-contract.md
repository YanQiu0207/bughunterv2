# 工具接口契约规范

> **ADR-0001 §4 要求**：所有外部能力统一抽象为接口契约；前期 mock 占位，真实实现按同一契约热替换。
>
> 本文档是所有工具契约的权威定义，M1 mock 实现与未来真实实现均须符合此规范。

---

## 通用规则

### 规模上限（Context 保护）

每个工具必须强制限制返回数据量，防止大结果撑爆 agent context：

| 限制类型 | 强制上限 | 超限处理 |
| -------- | -------- | -------- |
| 文本行数 | 视工具定义 | 截断并附注「结果已截断，共 N 条」 |
| 列表条目 | 视工具定义 | 截断并附注「已达上限，可能有更多结果」 |
| 大数据结果 | 不进 context | 落盘，返回摘要 + 文件路径引用 |

### 返回格式

- 成功：纯文本，人类可读，附行号前缀（源码类工具）或 `file:line:content` 格式（搜索类工具）
- 失败：以 `[tool_name] ` 为前缀的错误说明字符串，不抛异常
- 不返回 JSON（除非字段定义明确要求）

### 人工 gate（敏感操作）

涉及**写库、调真实接口、SVN 提交**的工具，执行前必须输出确认提示并等待人工批准。M1 阶段工具均为只读，不涉及此规则；M2+ 工具引入时须在本文档明确标注。

### mock 与真实实现的切换约定

- 工厂函数签名固定（`make_<tool_name>_tool(...)`），调用方通过注入不同依赖切换实现
- mock 实现与真实实现**不改调用方代码**，仅替换工厂函数内部逻辑或依赖对象
- mock 实现须在返回内容中注明 `[MOCK]` 标识，方便调试时区分

---

## M1 工具契约

### `read_source` — 读取 Java 源码片段

**用途**：按类名 + 行范围读取源文件内容，供 agent 分析代码逻辑。

**工厂函数**：`make_read_source_tool(index: SourceIndex) -> Tool`

**输入参数**：

| 参数 | 类型 | 说明 |
| ---- | ---- | ---- |
| `class_name` | `str` | 简单类名或全限定类名（如 `OrderService` 或 `com.example.OrderService`） |
| `start_line` | `int` | 起始行号，1-based |
| `end_line` | `int` | 结束行号，1-based，含 |

**返回格式（成功）**：

```
// path/to/File.java (lines 10-30)
  10 | public void processOrder(Order order) {
  11 |     if (order == null) {
  ...
```

**返回格式（失败）**：

```
[read_source] Cannot resolve class 'Foo' to a source file.
[read_source] Requested range [100, 50] is out of bounds (file has 80 lines).
```

**规模上限**：行范围由调用方控制；无强制截断，但 agent prompt 须引导合理窗口（建议每次不超过 50 行）。

**M1 实现类型**：真实实现（读本地文件系统）。

---

### `find_callers` — 查找方法调用点

**用途**：在源码目录中搜索某个方法名的调用位置，支撑回溯循环中的「来源追踪」步骤。

**工厂函数**：`make_find_callers_tool(src_dir: str) -> Tool`

**输入参数**：

| 参数 | 类型 | 说明 |
| ---- | ---- | ---- |
| `method_name` | `str` | 方法名，不含括号（如 `getUserById`） |

**返回格式（成功）**：

```
/path/to/Service.java:42:    result = getUserById(userId);
/path/to/Controller.java:17:    User u = getUserById(request.getId());
[find_callers] Results capped at 20; there may be more matches.
```

**返回格式（无结果）**：

```
[find_callers] No callers found for 'getUserById'.
```

**规模上限**：最多返回 **20 条**，超限附注截断提示。

**注意**：可能包含误报（同名方法），agent 须结合上下文过滤。

**M1 实现类型**：真实实现（递归 `os.walk` 文本搜索）。

---

### `submit_diagnosis` — 提交最终诊断结论

**用途**：agent 完成回溯后，通过此工具提交结构化结论并终止调查。属于「强制输出」机制，不对应任何外部资源。

**工厂函数**：`make_submit_diagnosis_tool(result_holder: dict) -> Tool`

**输入参数**：

| 参数 | 类型 | 说明 |
| ---- | ---- | ---- |
| `root_cause_hypothesis` | `str` | 一句可证伪的根因假设 |
| `evidence` | `list[dict]` | 证据列表，每项含 `type`、`file`、`line`、`snippet` |
| `counter_check` | `str` | 如何排除替代解释 |
| `fix_direction` | `str` | 高层修复方向（不含具体代码） |
| `confidence` | `str` | `"high"` / `"medium"` / `"low"` |
| `confidence_reason` | `str` | 置信度理由（一句话） |

**返回格式（成功）**：

```
Diagnosis submitted successfully. Do not call any more tools. Your work is complete.
```

**返回格式（重复调用）**：

```
Diagnosis already submitted. Do not call any more tools.
```

**规模上限**：无（agent 自行控制 evidence 条目数）。

**特殊约定**：首次提交胜出，重复调用静默忽略。此工具是 agent 循环的**终止信号**。

---

## M2 工具契约

### `apply_fix` — 将修复写入隔离工作区

**用途**：创建硬链接隔离工作区，并将行级编辑指令应用到隔离区文件，原目录全程不动。

**工厂函数**：`make_apply_fix_tool(workspace_dir: str, target_project_dir: str) -> Tool`

**输入参数**：

| 参数 | 类型 | 说明 |
| ---- | ---- | ---- |
| `fix_id` | `str` | 本次修复的唯一 ID，用于创建 `workspace/fix/<fix_id>/` |
| `edits` | `list[dict]` | 行级编辑指令列表，每项含 `file`、`start_line`、`end_line`、`new_content` |

**行为**：
1. 若隔离工作区不存在，用 `shutil.copytree(..., copy_function=os.link)` 从 `target_project_dir` 创建
2. 按 `file` 分组，**从后往前**（行号降序）应用编辑，避免行号偏移
3. 修改文件时先 `os.unlink`，再写入新内容（断开硬链接，保护原文件）

**返回格式（成功）**：

```
[apply_fix] Applied 3 edit(s) to workspace/fix/<fix_id>/.
  Modified: src/com/example/OrderService.java
```

**返回格式（失败）**：

```
[apply_fix] Error: file 'src/Foo.java' not found in workspace.
[apply_fix] Error: start_line 50 > end_line 42 in edit for 'src/Bar.java'.
```

**规模上限**：单次调用编辑条目不超过 **50 条**；超限返回错误，不执行任何修改。

**人工 gate**：否（写隔离工作区，不碰原目录）。

**M2 实现类型**：真实实现。

---

### `run_build` — 在隔离工作区执行编译命令

**用途**：在隔离工作区目录下运行 `build_command`，返回编译结果供 agent 分析。

**工厂函数**：`make_run_build_tool(workspace_dir: str, build_command: str) -> Tool`

**输入参数**：

| 参数 | 类型 | 说明 |
| ---- | ---- | ---- |
| `fix_id` | `str` | 隔离工作区 ID |

**行为**：在 `workspace/fix/<fix_id>/` 目录下执行 `build_command`，捕获 stdout + stderr。

**返回格式（成功）**：

```
[run_build] Build succeeded.
--- stdout ---
...
```

**返回格式（失败）**：

```
[run_build] Build failed (exit code 1).
--- stderr ---
src/com/example/OrderService.java:42: error: ';' expected
    if (name == null) return
                            ^
1 error
```

**规模上限**：输出截断至 **200 行**，超限附注「输出已截断」。

**超时**：默认 **120 秒**，超时返回错误。

**人工 gate**：否。

**M2 实现类型**：真实实现。

---

### `run_tests` — 在隔离工作区执行单测命令

**用途**：在隔离工作区目录下运行 `test_command`，返回单测结果。

**工厂函数**：`make_run_tests_tool(workspace_dir: str, test_command: str) -> Tool`

**输入参数**：

| 参数 | 类型 | 说明 |
| ---- | ---- | ---- |
| `fix_id` | `str` | 隔离工作区 ID |

**行为**：在 `workspace/fix/<fix_id>/` 目录下执行 `test_command`，捕获 stdout + stderr。

**返回格式（成功）**：

```
[run_tests] Tests passed.
--- stdout ---
Tests run: 12, Failures: 0, Errors: 0
```

**返回格式（失败）**：

```
[run_tests] Tests failed (exit code 1).
--- stdout ---
Tests run: 12, Failures: 1, Errors: 0
FAILED: testHandleNullName
  expected: no exception
  but was: NullPointerException at OrderService.java:42
```

**规模上限**：输出截断至 **200 行**，超限附注「输出已截断」。

**超时**：默认 **300 秒**，超时返回错误。

**人工 gate**：否。

**M2 实现类型**：真实实现。

---

## M3+ 预留工具槽

以下工具在 M3 及之后里程碑引入，届时在本文档追加契约定义：

| 工具名 | 预计里程碑 | 用途 | 是否需人工 gate |
| ------ | ---------- | ---- | --------------- |
| `start_local_server` | M3 | 启动本地服务 | 是 |
| `query_local_db` | M3 | 查询本地 DB | 否（只读） |
| `search_logs` | M5 | 搜索线上日志 | 否（只读） |
| `svn_commit` | M4 | 提交到 SVN | 是（强制人工确认） |

---

## 添加新工具的检查清单

新工具合入前，须完成以下各项：

- [ ] 在本文档追加契约定义（参数、返回格式、规模上限、实现类型）
- [ ] 确认是否属于敏感操作（写库/调接口/SVN），若是则标注人工 gate 要求
- [ ] mock 实现返回带 `[MOCK]` 标识
- [ ] 工厂函数签名遵循 `make_<tool_name>_tool(...)` 命名约定
- [ ] 单元测试覆盖：正常返回、边界输入、规模截断、错误路径
