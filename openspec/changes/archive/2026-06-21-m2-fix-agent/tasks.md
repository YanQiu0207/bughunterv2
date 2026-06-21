# 实施任务清单

> 由 proposal.md + ADR-0003 生成
> 任务总数: 9
> 核心原则: 模型先行 → 工具并行 → Agent 聚合 → CLI 收尾 → 测试兜底；每步完成后代码可编译

## 依赖关系总览

```
Task 1 (数据模型)  Task 2 (Config 扩展)  Task 6 (Fix Prompt)
     ↓                   ↓                      ↓
Task 3 (apply_fix)  Task 4 (run_build)  Task 5 (run_tests)
     ↓                   ↓                      ↓
     └──────────────── Task 7 (FixAgent) ────────┘
                              ↓
                Task 8 (fix.py CLI)   Task 9 (单元测试)
```

Task 3/4/5 相互独立，可并行。Task 6 独立，可与 1/2 并行。

## 变更影响概览

### 文件变更清单

| 文件 | 操作 | 涉及任务 | 说明 |
|------|------|---------|------|
| `src/models.py` | 修改 | Task 1 | 追加 FixEdit、FixProposal dataclass |
| `src/config.py` | 修改 | Task 2 | 追加 3 个字段 + load_config 对应行 |
| `config.yaml` | 修改 | Task 2 | 追加 3 个配置项注释示例 |
| `src/tools/apply_fix.py` | 新建 | Task 3 | 硬链接工作区 + 行级编辑应用 |
| `src/tools/run_build.py` | 新建 | Task 4 | 子进程执行 build_command |
| `src/tools/run_tests.py` | 新建 | Task 5 | 子进程执行 test_command |
| `src/agent/fix_prompts.py` | 新建 | Task 6 | FixAgent 系统 prompt |
| `src/agent/fix_agent.py` | 新建 | Task 7 | FixAgent 主类 + submit_fix_proposal 工具 |
| `fix.py` | 新建 | Task 8 | CLI 入口，参照 diagnose.py |
| `tests/test_fix_tools.py` | 新建 | Task 9 | apply_fix / run_build / run_tests 单元测试 |
| `tests/test_fix_agent.py` | 新建 | Task 9 | FixAgent 结构验证单元测试 |

### 受影响接口

| 接口 | 变更类型 | 调用方 | 涉及任务 |
|------|---------|--------|---------|
| `Config` dataclass | 新增字段 | `fix.py`、`FixAgent` | Task 2, 7, 8 |
| `src/models.py` | 新增类型 | `apply_fix`、`fix_agent`、`fix.py` | Task 1, 3, 7, 8 |

### 构建系统变更

无需修改 `pyproject.toml`（M2 不引入新依赖，`subprocess`/`shutil`/`difflib` 均为标准库）。

## 风险与假设

| # | 描述 | 影响任务 | 假设/处理 |
|---|------|---------|----------|
| 1 | 硬链接仅在同一文件系统下有效 | Task 3 | 假设 `target_project_dir` 与 `workspace/` 在同一挂载点；工具若 `os.link` 失败，返回 `[apply_fix] Error: cross-device link` 并终止 |
| 2 | `shutil.copytree` 遇到权限不足的文件会抛异常 | Task 3 | 捕获异常，返回带 `[apply_fix]` 前缀的错误字符串 |
| 3 | FixAgent 迭代修复时需要重新应用 edits | Task 7 | 每次迭代调用 `apply_fix` 前，先对已修改文件重新硬链接恢复原始内容（`os.unlink` + `os.link(原始文件, 工作区文件)`），确保从干净原始状态应用新 edits |
| 4 | FixAgent 生成的 edits 行号可能与运行时内容不一致 | Task 3 | `apply_fix` 在 `os.unlink` 后以读取工作区文件实际行数做 bounds check，超界返回错误 |
| 5 | build/test 命令可能产生超长输出 | Task 4, 5 | 截断至 200 行，追加 `[run_build] Output truncated (N lines total).` |

## 任务列表

---

### 任务 1: [ ] 数据模型：FixEdit 和 FixProposal

- 文件: `src/models.py`（修改）
- 依赖: 无
- 文档映射: proposal.md §核心方案「修复方案格式」、ADR-0003 §3
- 说明: 在 `src/models.py` 末尾追加两个 dataclass。
  - `FixEdit`：单处代码改动，字段 `file: str`、`start_line: int`、`end_line: int`、`new_content: str`、`reason: str`
  - `FixProposal`：一次修复方案，字段 `proposal_id: str`、`diagnosis_id: str`、`created_at: str`、`status: Literal["draft","applied","verified"]`、`edits: list[FixEdit]`、`summary: str`
- context:
  - `src/models.py` — 直接修改目标，跟随现有 dataclass 风格（`@dataclass`，无默认工厂以外的方法）
  - `src/tools/apply_fix.py` — 下游：接收 `list[FixEdit]` 参数
  - `src/agent/fix_agent.py` — 下游：构造并返回 `FixProposal`
  - `fix.py` — 下游：序列化 FixProposal 为 JSON
- 验收标准:
  - [ ] `python -c "from src.models import FixEdit, FixProposal; print('ok')"` 输出 `ok`
  - [ ] `FixEdit(file='A.java', start_line=1, end_line=1, new_content='x\n', reason='test')` 可构造
  - [ ] `FixProposal` 的 `status` 字段赋非法值时 mypy 报错（Literal 约束）
  - [ ] 现有 `pytest tests/` 全绿（不破坏 M1 测试）
- 子任务:
  - [ ] 1.1: 在 `src/models.py` 末尾追加 `FixEdit` dataclass
  - [ ] 1.2: 在 `src/models.py` 末尾追加 `FixProposal` dataclass

---

### 任务 2: [ ] Config 扩展：target_project_dir / build_command / test_command

- 文件: `src/config.py`（修改）、`config.yaml`（修改）
- 依赖: 无
- 文档映射: proposal.md §需求「Config 扩展」、ADR-0003 §5
- 说明:
  - 在 `Config` dataclass 中追加三个字段，默认值均为空字符串 `""`
  - 在 `load_config()` 的 `return Config(...)` 调用中追加三行对应读取
  - 在 `config.yaml` 末尾追加带注释的配置示例（值保持空字符串，提示用户填写）
- context:
  - `src/config.py:Config` (第 25 行) — 直接修改目标
  - `src/config.py:load_config()` (第 44 行) — 直接修改目标
  - `config.yaml` — 直接修改目标
  - `src/agent/fix_agent.py` — 下游：读取 `config.target_project_dir`、`config.build_command`、`config.test_command`
  - `tests/test_config.py`（如存在）— 若无则不影响
- 验收标准:
  - [ ] `python -c "from src.config import Config; c = Config(); print(c.build_command)"` 输出空字符串
  - [ ] `load_config('config.yaml')` 不抛异常，三个新字段可访问
  - [ ] 现有 `pytest tests/` 全绿
- 子任务:
  - [ ] 2.1: 在 `Config` dataclass 追加三个字段
  - [ ] 2.2: 在 `load_config()` 的 `return Config(...)` 追加三行
  - [ ] 2.3: 在 `config.yaml` 末尾追加配置注释示例

---

### 任务 3: [ ] apply_fix 工具

- 文件: `src/tools/apply_fix.py`（新建）
- 依赖: Task 1（需要 `FixEdit` 类型，但 LangChain tool 接收 dict，实际可不导入）
- 文档映射: proposal.md §需求 F3、ADR-0003 §1 和 §3、tool-contract.md §M2 工具契约 apply_fix
- 说明: 实现 `make_apply_fix_tool(workspace_root: str, target_project_dir: str)`。
  核心逻辑：
  1. 工作区路径 = `workspace_root/fix/<fix_id>/`
  2. 若工作区不存在，`shutil.copytree(target_project_dir, workspace_path, copy_function=os.link)` 创建
  3. 若工作区已存在，对本次 edits 涉及的每个文件做「恢复原始」：`os.unlink(ws_file)` → `os.link(original_file, ws_file)`（从 target_project_dir 重新硬链接）
  4. 从后往前按行号排序 edits，对每个 edit：`os.unlink(ws_file)` → 读原文件行 → 替换 start_line~end_line → 写回
  5. 编辑条目 > 50 条，返回错误不执行任何修改
  6. 返回成功/失败字符串（`[apply_fix]` 前缀规范）
- context:
  - `src/tools/read_source.py` — 参照工厂函数 + `@tool` 模式
  - `src/agent/fix_agent.py` — 上游调用方：`make_apply_fix_tool(workspace_root, target_project_dir)`
  - `tests/test_fix_tools.py` — 下游测试
- 验收标准:
  - [ ] `python -c "from src.tools.apply_fix import make_apply_fix_tool; print('ok')"` 输出 `ok`
  - [ ] 调用工具后原 `target_project_dir` 中文件 inode 不变（`os.stat().st_ino` 验证）
  - [ ] 工作区中修改文件 inode 与原文件不同（断开硬链接验证）
  - [ ] edits > 50 条时返回含 `[apply_fix] Error` 的字符串，工作区不产生任何修改
  - [ ] 跨设备 `os.link` 失败时返回含 `[apply_fix] Error` 的字符串
- 子任务:
  - [ ] 3.1: 实现 `_create_or_reset_workspace(workspace_path, target_project_dir, files_to_modify)`（创建/恢复硬链接）
  - [ ] 3.2: 实现 `_apply_edits(workspace_path, edits)`（从后往前替换行内容）
  - [ ] 3.3: 实现 `make_apply_fix_tool` 工厂函数 + `@tool apply_fix`

---

### 任务 4: [ ] run_build 工具

- 文件: `src/tools/run_build.py`（新建）
- 依赖: 无
- 文档映射: proposal.md §需求 F4、tool-contract.md §M2 工具契约 run_build
- 说明: 实现 `make_run_build_tool(workspace_root: str, build_command: str)`。
  核心逻辑：
  - 工具接收 `fix_id: str`，计算工作区目录
  - `subprocess.run(build_command, cwd=workspace_path, shell=True, capture_output=True, text=True, timeout=120)`
  - 合并 stdout + stderr，截断至 200 行，returncode 非 0 视为失败
  - 返回格式见 tool-contract.md
- context:
  - `src/tools/find_callers.py` — 参照工厂函数 + `@tool` 模式
  - `src/agent/fix_agent.py` — 上游调用方
  - `tests/test_fix_tools.py` — 下游测试
- 验收标准:
  - [ ] `python -c "from src.tools.run_build import make_run_build_tool; print('ok')"` 输出 `ok`
  - [ ] 命令成功（exit 0）时返回含 `[run_build] Build succeeded.` 的字符串
  - [ ] 命令失败（exit 非 0）时返回含 `[run_build] Build failed` 的字符串
  - [ ] 输出超 200 行时返回含 `Output truncated` 的字符串
  - [ ] 超时 120s 时返回含 `[run_build] Error: timed out` 的字符串
- 子任务:
  - [ ] 4.1: 实现 `make_run_build_tool` 工厂函数 + `@tool run_build`

---

### 任务 5: [ ] run_tests 工具

- 文件: `src/tools/run_tests.py`（新建）
- 依赖: 无
- 文档映射: proposal.md §需求 F4、tool-contract.md §M2 工具契约 run_tests
- 说明: 同 Task 4，差异：超时 300s，前缀 `[run_tests]`，成功提示 `Tests passed.`。
- context:
  - `src/tools/run_build.py`（Task 4）— 同一模式，直接参照
  - `src/agent/fix_agent.py` — 上游调用方
  - `tests/test_fix_tools.py` — 下游测试
- 验收标准:
  - [ ] `python -c "from src.tools.run_tests import make_run_tests_tool; print('ok')"` 输出 `ok`
  - [ ] 超时 300s（不是 120s）
  - [ ] 成功/失败/截断/超时返回格式与 run_build 对称（前缀替换为 `[run_tests]`）
- 子任务:
  - [ ] 5.1: 实现 `make_run_tests_tool` 工厂函数 + `@tool run_tests`

---

### 任务 6: [ ] FixAgent 系统 Prompt

- 文件: `src/agent/fix_prompts.py`（新建）
- 依赖: 无
- 文档映射: proposal.md §核心方案、ADR-0002（回溯循环方法论可参考）
- 说明: 实现 `build_fix_system_prompt(max_steps: int) -> str`，返回指导 FixAgent 的系统提示。
  内容要点：
  1. 角色：你是一个 Java 代码修复 agent，目标是根据诊断报告生成可编译、单测通过的最小化修复
  2. 工具使用顺序：apply_fix → run_build（失败则修改 edits 重试）→ run_tests（失败则修改 edits 重试）→ submit_fix_proposal（成功才能调用）
  3. 约束：只修改诊断报告中涉及的文件；edits 最小化；不引入与修复无关的改动
  4. `max_steps` 上限提示
  5. 失败处理：若 max_steps 耗尽仍未通过，调用 submit_fix_proposal 并标注 status="draft"（已尽力但未验证通过）
- context:
  - `src/agent/prompts.py` — 参照 `build_system_prompt()` 函数结构
  - `src/agent/fix_agent.py`（Task 7）— 上游调用方
- 验收标准:
  - [ ] `python -c "from src.agent.fix_prompts import build_fix_system_prompt; print(len(build_fix_system_prompt(10)) > 0)"` 输出 `True`
  - [ ] 返回字符串包含 `apply_fix`、`run_build`、`run_tests`、`submit_fix_proposal` 关键词
- 子任务:
  - [ ] 6.1: 实现 `build_fix_system_prompt(max_steps: int) -> str`

---

### 任务 7: [ ] FixAgent

- 文件: `src/agent/fix_agent.py`（新建）
- 依赖: Task 1（FixProposal）、Task 2（Config）、Task 3（apply_fix）、Task 4（run_build）、Task 5（run_tests）、Task 6（fix_prompts）
- 文档映射: proposal.md §需求 F2/F3/F4、ADR-0003 §4
- 说明: 参照 `DiagnosisAgent` 骨架，实现 `FixAgent`。
  - `__init__(self, config: Config, workspace_root: str)`
  - `run(self, report: DiagnosisReport) -> FixProposal`：
    1. 生成 `proposal_id = uuid4()`
    2. 注册工具：`apply_fix`、`run_build`、`run_tests`、`submit_fix_proposal`
    3. `submit_fix_proposal` 工具：接收 `edits: list[dict]`、`summary: str`、`status: str`，写入 `result_holder`，返回终止信号
    4. 构造 `ChatOpenAI`（同 DiagnosisAgent 方式）
    5. 构造用户消息（包含 DiagnosisReport 的 conclusion 信息）
    6. `agent.invoke(...)` 运行
    7. 从 `result_holder` 构造 `FixProposal`
    8. 调用 `_checkpoint()` 原子写盘到 `workspace_root/fix/<proposal_id>.json`
    9. 返回 `FixProposal`
- context:
  - `src/agent/diagnosis_agent.py` — 参照骨架（`result_holder`、`ChatOpenAI`、`create_react_agent`、`_checkpoint`）
  - `src/agent/fix_prompts.py`（Task 6）— 调用 `build_fix_system_prompt`
  - `src/tools/apply_fix.py`（Task 3）— 工具注册
  - `src/tools/run_build.py`（Task 4）— 工具注册
  - `src/tools/run_tests.py`（Task 5）— 工具注册
  - `fix.py`（Task 8）— 下游调用方
  - `tests/test_fix_agent.py`（Task 9）— 下游测试
- 验收标准:
  - [ ] `python -c "from src.agent.fix_agent import FixAgent; print('ok')"` 输出 `ok`
  - [ ] `FixAgent.__init__` 接受 `(config: Config, workspace_root: str)`
  - [ ] `FixAgent.run` 接受 `DiagnosisReport`，返回 `FixProposal`
  - [ ] `result_holder` 为空时（agent 未调用 submit_fix_proposal），返回 status="draft" 的 FixProposal
  - [ ] 现有 `pytest tests/ -m 'not integration'` 全绿
- 子任务:
  - [ ] 7.1: 实现 `make_submit_fix_proposal_tool(result_holder)`
  - [ ] 7.2: 实现 `FixAgent.__init__` 和 `_checkpoint()`
  - [ ] 7.3: 实现 `FixAgent.run()`（工具注册 + agent 构造 + invoke + 结果解析）
  - [ ] 7.4: 实现 `_build_fix_proposal(result_holder, proposal_id, diagnosis_id) -> FixProposal` 辅助函数

---

### 任务 8: [ ] CLI 入口 fix.py

- 文件: `fix.py`（新建）
- 依赖: Task 7（FixAgent）
- 文档映射: proposal.md §需求「CLI 入口」、ADR-0003 §6（G2 gate）
- 说明: 参照 `diagnose.py` 实现 `fix.py`。
  参数：`--report`（诊断 JSON 路径，必填）、`--config`（默认 `config.yaml`）
  流程：
  1. `load_config(args.config)` → 检查 `config.target_project_dir`、`build_command`、`test_command` 非空，否则报错退出
  2. 读取 `--report` JSON → 反序列化为 `DiagnosisReport`（最小化：只取需要的字段）
  3. 确定 `workspace_root = "workspace"`
  4. 实例化 `FixAgent(config, workspace_root)` → `proposal = agent.run(report)`
  5. 打印修复摘要：proposal_id、status、受影响文件列表
  6. 若 status == "verified"，打印：`Fix verified. Diff saved to workspace/fix/<id>/. Review and commit manually.`
  7. 若 status == "draft"，打印：`Fix proposal generated but not verified. Check workspace/fix/<id>.json.`
- context:
  - `diagnose.py` — 直接参照整体结构
  - `src/agent/fix_agent.py`（Task 7）— 调用
  - `src/config.py`（Task 2）— 读取新字段
- 验收标准:
  - [ ] `python fix.py --help` 打印帮助，包含 `--report` 和 `--config`
  - [ ] `config.target_project_dir` 为空时，`python fix.py --report x.json` 退出并提示配置缺失
  - [ ] `--report` 路径不存在时，报错退出（非 traceback）
- 子任务:
  - [ ] 8.1: 实现 argparse 参数和 config 校验
  - [ ] 8.2: 实现 DiagnosisReport JSON 反序列化（只取 diagnosis_id + conclusion 字段）
  - [ ] 8.3: 实现 FixAgent 调用 + 结果打印

---

### 任务 9: [ ] 单元测试

- 文件: `tests/test_fix_tools.py`（新建）、`tests/test_fix_agent.py`（新建）
- 依赖: Task 3、Task 4、Task 5、Task 7
- 文档映射: proposal.md §验收标准
- 说明:
  **test_fix_tools.py**（参照 `tests/test_tools.py`）：
  - `apply_fix`：创建临时目录模拟 target_project_dir，验证原文件 inode 不变、工作区文件内容正确、edits > 50 返回错误
  - `run_build`：用 `echo "Build OK"` 作为 build_command，验证成功返回；用 `exit 1` 验证失败返回；用超长输出验证截断
  - `run_tests`：同上，超时值为 300s（用 `timeout` 参数 mock 验证不同于 run_build 的 120s）

  **test_fix_agent.py**：
  - 验证 `FixAgent` 注册了 apply_fix、run_build、run_tests、submit_fix_proposal 四个工具
  - 验证 `result_holder` 为空时返回 status="draft" 的 FixProposal
  - 不调用真实 LLM（mock `agent.invoke`）
- context:
  - `tests/test_tools.py` — 参照测试模式（`tool.invoke({...})`）
  - `tests/test_integration.py` — 参照 `scope="module"` fixture 模式
- 验收标准:
  - [ ] `pytest tests/test_fix_tools.py -v` 全绿
  - [ ] `pytest tests/test_fix_agent.py -v` 全绿
  - [ ] `pytest tests/ -m 'not integration'` 全绿（含 M1 原有测试）
- 子任务:
  - [ ] 9.1: 实现 `test_fix_tools.py`（apply_fix / run_build / run_tests 各测 3 个用例）
  - [ ] 9.2: 实现 `test_fix_agent.py`（工具注册验证 + result_holder 空值路径）

---

## 文档覆盖映射

| 文档条目 | 任务 | 说明 |
|---------|------|------|
| proposal.md §数据模型 FixEdit/FixProposal | Task 1 | 完整覆盖 |
| proposal.md §Config 扩展 3 个字段 | Task 2 | 完整覆盖 |
| proposal.md §需求 F2（生成修复方案） | Task 6, 7 | prompt + agent 主逻辑 |
| proposal.md §需求 F3（apply_fix 工具） | Task 3 | 完整覆盖 |
| proposal.md §需求 F4（编译+单测回灌） | Task 4, 5, 7 | 工具 + agent 循环逻辑 |
| proposal.md §需求「CLI 入口」 | Task 8 | 完整覆盖 |
| proposal.md §验收标准 1（pytest 全绿） | Task 9 | 完整覆盖 |
| proposal.md §验收标准 2（fix.py 可运行） | Task 8 | 完整覆盖 |
| proposal.md §验收标准 3（原目录不变） | Task 3, 9 | apply_fix inode 验证 |
| proposal.md §验收标准 4（报错回灌迭代） | Task 7 | agent 循环逻辑 |
| ADR-0003 §1（硬链接隔离） | Task 3 | 完整覆盖 |
| ADR-0003 §2（编译+单测验证标准） | Task 4, 5 | 完整覆盖 |
| ADR-0003 §3（行级编辑指令格式） | Task 1, 3 | 模型 + 工具 |
| ADR-0003 §4（FixAgent 独立架构） | Task 7 | 完整覆盖 |
| ADR-0003 §5（Config 新字段） | Task 2 | 完整覆盖 |
| ADR-0003 §6（G1/G2 人工 gate） | Task 7, 8 | G1 在 agent 首次 apply 前展示 diff；G2 在 fix.py 输出提示 |
