# 实施任务清单

> 由 proposal.md / design.md 生成
> 任务总数: 7
> 核心原则: 先建底层工具模块（svn.py / patcher.py），再组装 CLI，最后补测试

## 依赖关系总览

```
Task 1 (Config: max_retry)
       ↓
Task 4 (commit_fix.py) ← Task 2 (svn.py) ← Task 6 (test_svn.py)
                      ← Task 3 (patcher.py) ← Task 5 (test_patcher.py)
                               ↓
                        Task 7 (test_commit_fix.py)

Task 2 ‖ Task 3（无依赖，可并行）
```

## 变更影响概览

### 文件变更清单

| 文件 | 操作 | 涉及任务 | 说明 |
|------|------|---------|------|
| `src/config.py` | 修改 | Task 1 | 新增 `max_retry` 字段及默认值 |
| `src/commit/__init__.py` | 新建 | Task 2 | commit 包标识文件（空） |
| `src/commit/svn.py` | 新建 | Task 2 | svn_update / svn_commit / svn_revert |
| `src/commit/patcher.py` | 新建 | Task 3 | snapshot_hashes / detect_conflicts / apply_edits / generate_diff |
| `commit_fix.py` | 新建 | Task 4 | CLI 入口 + 重试主循环 |
| `tests/test_patcher.py` | 新建 | Task 5 | patcher.py 单元测试（11 个用例） |
| `tests/test_svn.py` | 新建 | Task 6 | svn.py 单元测试（5 个用例） |
| `tests/test_commit_fix.py` | 新建 | Task 7 | 集成测试（8 个用例） |

### 受影响接口

| 接口 | 变更类型 | 调用方 | 涉及任务 |
|------|---------|--------|---------|
| `Config.max_retry` | 新增字段 | `commit_fix.py` | Task 1, 4 |
| `load_config()` | 新增 max_retry 解析 | `commit_fix.py` | Task 1, 4 |

### 构建系统变更

无（纯 Python，无需修改 pyproject.toml / setup.py）

## 风险与假设

| # | 描述 | 影响任务 | 假设/处理 |
|---|------|---------|----------|
| 1 | `apply_edits` 在 `patcher.py` 中重复了 `apply_fix.py` 的行级写入逻辑 | Task 3 | 接受重复：两者写入目标不同（source_dir vs workspace），且 M3 不引入 hardlink 机制，共享会增加耦合 |
| 2 | `commit_fix.py` 在重试时需要加载 DiagnosisReport，依赖 `workspace/diagnosis/<diagnosis_id>.json` 存在 | Task 4 | 假设 `diagnose.py` 已写出该文件；若不存在则报错退出 |
| 3 | `svn_commit` 需要解析 revision 号，但 SVN CLI 输出格式可能因版本而异 | Task 2 | 假设标准 `svn commit` 输出包含 `Committed revision N.` 格式；用正则解析，解析失败时返回 `"?"` 而非报错 |

## 任务列表

---

### 任务 1: [x] Config 新增 max_retry 字段

- 文件: `src/config.py`（修改）
- 依赖: 无
- 文档映射: proposal.md §关键约束 / design.md §3.2 配置参数
- 说明: 在 `Config` dataclass 新增 `max_retry: int = 3`，并在 `load_config()` 中解析 YAML 里的 `max_retry` 键
- context:
  - `src/config.py` — 直接修改目标
  - `commit_fix.py`（Task 4）— 下游消费方，读取 `config.max_retry`
- 验收标准:
  - [ ] 编译通过，现有测试全部通过（`pytest tests/` 无新失败）
  - [ ] `Config()` 默认 `max_retry == 3`
  - [ ] YAML 写 `max_retry: 5` 时，`load_config()` 返回 `config.max_retry == 5`
- 子任务:
  - [ ] 1.1 在 `_DEFAULT_MAX_RETRY = 3` 常量后添加
  - [ ] 1.2 `Config` 中加 `max_retry: int = _DEFAULT_MAX_RETRY`
  - [ ] 1.3 `load_config()` 中加 `max_retry=int(raw.get("max_retry", _DEFAULT_MAX_RETRY))`

---

### 任务 2: [x] 新建 src/commit/svn.py

- 文件: `src/commit/__init__.py`（新建，空文件）、`src/commit/svn.py`（新建）
- 依赖: 无（可与 Task 3 并行）
- 文档映射: design.md §1.2.1 / §1.2.2
- 说明: 封装三个 SVN 命令，通过 `subprocess.run` 执行，失败时抛 `RuntimeError`
- context:
  - `src/commit/svn.py` — 直接修改目标
  - `commit_fix.py`（Task 4）— 下游消费方
  - `tests/test_svn.py`（Task 6）— 测试方
- 验收标准:
  - [ ] 编译通过
  - [ ] `svn_update` / `svn_commit` / `svn_revert` 三个函数存在且签名与 design.md §1.2.2 一致
  - [ ] subprocess 返回非零时 `svn_update` 抛 `RuntimeError`
- 子任务:
  - [ ] 2.1 新建 `src/commit/__init__.py`（空）
  - [ ] 2.2 实现 `svn_update(path: str) -> None`
  - [ ] 2.3 实现 `svn_commit(path: str, message: str) -> str`（解析 revision，失败返回 `"?"`）
  - [ ] 2.4 实现 `svn_revert(path: str, files: list[str]) -> None`

---

### 任务 3: [x] 新建 src/commit/patcher.py

- 文件: `src/commit/patcher.py`（新建）
- 依赖: 无（可与 Task 2 并行）
- 文档映射: design.md §1.2.1 / §1.2.2 / §1.3
- 说明: 纯 Python，使用 `difflib` 和 `hashlib`；`apply_edits` 复用 apply_fix 的行级写入逻辑（back-to-front，atomic write）但写到 source_dir
- context:
  - `src/commit/patcher.py` — 直接修改目标
  - `src/models.py:FixEdit` — 上游数据结构
  - `commit_fix.py`（Task 4）— 下游消费方
  - `tests/test_patcher.py`（Task 5）— 测试方
- 验收标准:
  - [ ] 编译通过
  - [ ] 四个函数存在且签名与 design.md §1.2.2 一致
  - [ ] `snapshot_hashes(dir, [])` 返回 `{}`
  - [ ] `detect_conflicts({"f": "abc"}, dir_where_f_unchanged)` 返回 `[]`
- 子任务:
  - [ ] 3.1 实现 `snapshot_hashes(source_dir, files) -> dict[str, str]`（SHA-256）
  - [ ] 3.2 实现 `detect_conflicts(old_hashes, source_dir) -> list[str]`
  - [ ] 3.3 实现 `apply_edits(source_dir, edits) -> None`（back-to-front，atomic write，失败时 revert 已写文件）
  - [ ] 3.4 实现 `generate_diff(source_dir, workspace_dir, files) -> str`（`difflib.unified_diff`）

---

### 任务 4: [x] 新建 commit_fix.py

- 文件: `commit_fix.py`（新建）
- 依赖: Task 1、Task 2、Task 3
- 文档映射: design.md §1.1 / §1.2.2 / §1.3 / §1.2.5
- 说明: CLI 入口，实现 design.md §1.3 主循环；包含 `_load_proposal` 和 `_load_diagnosis` 两个 JSON 反序列化辅助函数（参考 `fix.py::_load_report` 写法）
- context:
  - `commit_fix.py` — 直接修改目标
  - `src/config.py:load_config` — 上游配置加载
  - `src/commit/svn.py` — 上游 SVN 操作
  - `src/commit/patcher.py` — 上游 patch 操作
  - `src/agent/fix_agent.py:FixAgent` — 上游 fix agent（重试时调用）
  - `fix.py` — 参考已有 CLI 结构
- 验收标准:
  - [ ] 编译通过
  - [ ] `python commit_fix.py --help` 打印 usage（含 `proposal_id`、`--config`、`--max-retry`、`--dry-run`）
  - [ ] `proposal.status != "verified"` 时打印错误并以非零退出
  - [ ] `--dry-run` 时不写文件（用 mock 验证）
- 子任务:
  - [ ] 4.1 实现 CLI 参数解析（argparse）
  - [ ] 4.2 实现 `_load_proposal(path) -> FixProposal`
  - [ ] 4.3 实现 `_load_diagnosis(workspace_root, diagnosis_id) -> DiagnosisReport`
  - [ ] 4.4 实现主循环（snapshot → svn update → 冲突检测 → apply/commit 或 retry）
  - [ ] 4.5 status 校验：非 `verified` 时拒绝执行

---

### 任务 5: [x] tests/test_patcher.py（11 个用例）

- 文件: `tests/test_patcher.py`（新建）
- 依赖: Task 3
- 文档映射: design.md §2.1（测试 1–11）
- 说明: 全部使用 `tmp_path`，无外部依赖
- context:
  - `tests/test_patcher.py` — 直接修改目标
  - `src/commit/patcher.py` — 被测模块
- 验收标准:
  - [ ] `pytest tests/test_patcher.py` 全部通过（11 passed）
- 子任务:
  - [ ] 5.1 `snapshot_hashes` 正常、空列表、文件不存在
  - [ ] 5.2 `detect_conflicts` hash 未变、部分变动
  - [ ] 5.3 `apply_edits` 单文件、多文件、空 edits、写失败时回滚
  - [ ] 5.4 `generate_diff` 有差异、无差异

---

### 任务 6: [x] tests/test_svn.py（5 个用例）

- 文件: `tests/test_svn.py`（新建）
- 依赖: Task 2
- 文档映射: design.md §2.1（测试 12–16）
- 说明: mock `subprocess.run`
- context:
  - `tests/test_svn.py` — 直接修改目标
  - `src/commit/svn.py` — 被测模块
- 验收标准:
  - [ ] `pytest tests/test_svn.py` 全部通过（5 passed）
- 子任务:
  - [ ] 6.1 `svn_update` 命令构造正确 / subprocess 失败时抛异常
  - [ ] 6.2 `svn_commit` 解析 revision / 失败时抛异常
  - [ ] 6.3 `svn_revert` 命令携带文件列表

---

### 任务 7: [x] tests/test_commit_fix.py（8 个用例）

- 文件: `tests/test_commit_fix.py`（新建）
- 依赖: Task 4、Task 5、Task 6
- 文档映射: design.md §2.2（测试 17–24）
- 说明: mock svn 命令 + FixAgent，使用 `tmp_path` 构造 workspace 结构
- context:
  - `tests/test_commit_fix.py` — 直接修改目标
  - `commit_fix.py` — 被测模块
  - `src/commit/svn.py` / `src/commit/patcher.py` / `src/agent/fix_agent.py` — mock 目标
- 验收标准:
  - [ ] `pytest tests/test_commit_fix.py` 全部通过（8 passed）
- 子任务:
  - [ ] 7.1 无冲突 happy path（apply + commit，打印 revision）
  - [ ] 7.2 冲突 → 重试 → 成功
  - [ ] 7.3 超过 max_retry → svn_revert 已调
  - [ ] 7.4 `status = "draft"` 拒绝执行
  - [ ] 7.5 `--dry-run` 不写文件不 commit
  - [ ] 7.6 `apply_edits` 失败 → svn_revert 已调
  - [ ] 7.7 FixAgent 重试返回 draft → 立即退出
  - [ ] 7.8 `max_retry=0` 首次冲突即退出

---

## 文档覆盖映射

| 文档条目 | 任务 | 说明 |
|---------|------|------|
| proposal.md §核心方案（svn update + diff + apply + commit） | Task 2, 3, 4 | 完整覆盖 |
| proposal.md §关键约束（working copy 干净） | Task 3, 4 | apply_edits 回滚 + svn_revert |
| proposal.md §关键约束（max_retry 可配置） | Task 1, 4 | Config 字段 + CLI 参数 |
| proposal.md §验收标准（无冲突场景） | Task 4, 7 | |
| proposal.md §验收标准（冲突场景重试） | Task 4, 7 | |
| proposal.md §验收标准（超限报错，working copy 干净） | Task 4, 7 | |
| proposal.md §验收标准（非 verified 拒绝） | Task 4, 7 | |
| design.md §1.2.1 核心模块 | Task 2, 3, 4 | |
| design.md §1.2.2 接口设计（CLI + 函数签名） | Task 1, 2, 3, 4 | |
| design.md §1.2.5 错误处理（各失败场景） | Task 4, 7 | |
| design.md §1.3 主循环伪代码 | Task 4 | |
| design.md §2.1 单元测试（test_patcher, test_svn） | Task 5, 6 | |
| design.md §2.2 集成测试（test_commit_fix） | Task 7 | |
| design.md §3.2 配置参数（max_retry） | Task 1 | |
