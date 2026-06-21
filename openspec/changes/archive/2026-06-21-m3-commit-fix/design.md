# Design: M3 — Commit Fix（自动写回 + 版本提交）

**作者**：YanQiu0207
**日期**：2026-06-21
**变更**：m3-commit-fix

---

## 1. 设计方案 (Design)

### 1.1 方案概览

**整体思路**：`commit_fix.py` 读取已验证的 FixProposal，生成 unified diff，`svn update` 后尝试 `patch` apply；apply 失败则重新跑 fix agent 生成新 edits，最多重试 N 次。

**数据流**：

```
workspace/fix/<id>.json (FixProposal, status=verified)
  │
  ├─ 对每个 modified file：diff(target_project_dir/<f>, workspace/fix/<id>/<f>)
  │
  ├─ svn update target_project_dir
  │
  ├─ patch --dry-run → 无冲突 → patch apply → svn commit ✓
  │
  └─ 有冲突 → FixAgent.run(diagnosis_report) → 新 proposal → 重试
             （超过 max_retry 次 → 报错退出，working copy 保持干净）
```

**模块划分**：

| 模块 | 职责 |
|------|------|
| `commit_fix.py` | CLI 入口，重试循环编排 |
| `src/commit/svn.py` | 封装 `svn update` / `svn commit` / `svn revert` |
| `src/commit/patcher.py` | 生成 unified diff、`patch --dry-run`、apply |
| `FixAgent`（复用 M2） | 冲突时重新生成 edits |

**依赖方向**：`commit_fix.py` → `src/commit/svn.py` + `src/commit/patcher.py` + `FixAgent`（无反向依赖）。

### 1.2 组件设计 (Component Design)

#### 1.2.1 核心类/模块设计

| 模块 | 职责 |
|------|------|
| `commit_fix.py` | CLI 入口；读 FixProposal → 快照 → svn update → 冲突检测 → apply/commit 或触发重试 |
| `src/commit/svn.py` | 薄封装 svn 命令：update / commit / revert；不含业务逻辑 |
| `src/commit/patcher.py` | 纯 Python（difflib）；冲突检测、edits apply、diff 生成；不调用外部 patch 命令 |
| `FixAgent`（M2 复用） | 冲突重试时重新生成 edits；无改动 |

**设计取舍**：冲突检测采用「目标文件 hash 变动即触发重试」而非三路合并。保守（可能误报），但实现简单且安全。

#### 1.2.2 接口设计

**CLI**

```
python commit_fix.py <proposal_id> [--config config.yaml] [--max-retry N] [--dry-run]
```

- `--dry-run`：生成 diff 打印，不写文件，不 commit
- `--max-retry`：默认取 config 中 `max_retry`（默认 3），CLI 参数可覆盖

**src/commit/svn.py**

```python
def svn_update(path: str) -> None: ...
def svn_commit(path: str, message: str) -> str: ...   # 返回 revision 号
def svn_revert(path: str, files: list[str]) -> None: ...
```

**src/commit/patcher.py**

```python
def snapshot_hashes(source_dir: str, files: list[str]) -> dict[str, str]: ...
def detect_conflicts(old_hashes: dict[str, str], source_dir: str) -> list[str]: ...
def apply_edits(source_dir: str, edits: list[FixEdit]) -> None: ...
def generate_diff(source_dir: str, workspace_dir: str, files: list[str]) -> str: ...
```

#### 1.2.3 数据模型

N/A - 本需求不适用

#### 1.2.4 并发模型

N/A - 本需求不适用

#### 1.2.5 错误处理

| 场景 | 分类 | 处理 |
|------|------|------|
| proposal 不存在 / status != verified | 不可重试 | 打印错误退出，working copy 未动 |
| svn update 失败 | 不可重试 | 打印错误退出，working copy 未动 |
| 冲突（目标文件 hash 变动） | 可重试 | 触发 FixAgent 重新生成，新 fix_id，重走全流程；超过 max_retry 退出 |
| apply_edits 写文件失败 | 不可重试 | `svn_revert` 清理已写文件，打印错误退出 |
| svn commit 失败 | 不可重试 | `svn_revert` 清理，打印错误退出 |
| FixAgent 重试时返回 draft | 不可重试 | 立即退出，不消耗重试次数 |

### 1.3 核心逻辑实现

**主循环（commit_fix.py）**

```python
def main(proposal_id, config, max_retry, dry_run):
    proposal = load_proposal(proposal_id)           # 读 JSON，校验 status=verified
    diagnosis = load_diagnosis(proposal.diagnosis_id)
    edited_files = [e.file for e in proposal.edits]
    workspace_dir = workspace_path(proposal_id)

    for attempt in range(max_retry + 1):
        old_hashes = snapshot_hashes(source_dir, edited_files)
        svn_update(source_dir)

        conflicts = detect_conflicts(old_hashes, source_dir)
        if conflicts and attempt < max_retry:
            proposal = FixAgent(config, new_workspace_root).run(diagnosis)
            if proposal.status != "verified":
                sys.exit("Fix agent returned draft, aborting.")
            edited_files = [e.file for e in proposal.edits]
            workspace_dir = workspace_path(proposal.proposal_id)
            continue
        elif conflicts:
            sys.exit(f"Conflict after {max_retry} retries.")

        diff = generate_diff(source_dir, workspace_dir, edited_files)
        print(diff)
        if dry_run:
            return

        apply_edits(source_dir, proposal.edits)
        revision = svn_commit(source_dir, f"[bughunter] {proposal.summary[:200]}")
        print(f"Committed: r{revision}")
        return
```

**`apply_edits` 写文件顺序**：与 `apply_fix` 相同，按 start_line 倒序 apply，保持行号语义。写失败时立即调 `svn_revert` 清理所有已写文件后退出。

### 1.4 方案优劣分析

**优点**
- 纯 Python，无额外外部依赖（不依赖 `diff`/`patch` 命令）
- `svn_revert` 在任何失败路径兜底，working copy 始终干净
- 复用 FixAgent，冲突重试无需新代码

**局限**
- 冲突检测保守：文件 hash 变动即重试，即便修改行不重叠（误报率高于三路合并）
- 重试代价高：每次重跑完整 fix agent + build/test
- commit message 截取 summary 前 200 字，不含 edits 详情

---

## 2. 测试计划 (Test Plan)

### 2.1 单元测试

**`tests/test_patcher.py`**（`tmp_path`，无外部依赖）

1. `snapshot_hashes` 正常返回 dict
2. `snapshot_hashes` 空文件列表返回 `{}`
3. `snapshot_hashes` 文件不存在时抛 OSError
4. `detect_conflicts` hash 未变 → 返回空列表
5. `detect_conflicts` 部分 hash 变动 → 返回变动文件
6. `apply_edits` 单文件单 edit
7. `apply_edits` 多文件多 edit
8. `apply_edits` 空 edits 列表（无操作）
9. `apply_edits` 写文件失败时已写文件被回滚
10. `generate_diff` 返回合法 unified diff 文本
11. `generate_diff` source 与 workspace 相同时 diff 为空

**`tests/test_svn.py`**（mock subprocess）

12. `svn_update` 命令构造正确
13. `svn_update` subprocess 失败时抛异常
14. `svn_commit` 从 stdout 解析 revision 号
15. `svn_commit` 失败时抛异常
16. `svn_revert` 命令携带正确的文件列表

### 2.2 集成测试

**`tests/test_commit_fix.py`**（mock svn 命令 + FixAgent）

17. 无冲突 happy path：apply + commit，打印 revision
18. 冲突 → 重试 → 第二次无冲突：commit 成功
19. 超过 max_retry：退出，svn_revert 已调用
20. `proposal.status = "draft"`：拒绝执行，不调 svn
21. `--dry-run`：打印 diff，不写文件，不 commit
22. `apply_edits` 失败：`svn_revert` 被调用
23. FixAgent 重试返回 draft：立即退出，不消耗重试次数
24. `max_retry=0`：首次冲突即退出

### 2.3 性能测试（如适用）

N/A - 本需求不适用

---

## 3. 可观测性 & 运维 (Observability & Operations)

### 3.1 可观测性

- **日志**：新增的日志输出点、日志级别、关键日志格式
- **监控指标**：N/A
- **告警**：N/A

### 3.2 配置参数 (Configuration)

| 参数名 | 类型 | 默认值 | 说明 | 是否支持动态修改 |
|--------|------|--------|------|------------------|
| `max_retry` | int | 3 | fix agent 冲突重试上限 | 否 |

### 3.3 运维注意事项

- **升级兼容性**：`commit_fix.py` 是独立脚本，无状态，可随时替换，无需特殊升级步骤
- **回滚方案**：commit 后如需回滚，手动执行 `svn revert -r <prev_revision>`；工具本身不提供自动回滚
- **资源影响**：每次冲突重试会重跑 fix agent（消耗 LLM token + build/test 时间），`max_retry` 建议不超过 3

---

## 4. Changelog

| 日期 | 变更内容 | 作者 |
|------|----------|------|
| 2026-06-21 | 初始化 | YanQiu0207 |
