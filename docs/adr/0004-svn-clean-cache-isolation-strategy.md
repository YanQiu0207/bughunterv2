# ADR-0004：使用干净 SVN 缓存副本创建修复隔离工作区

**状态**: 已接受
**日期**: 2026-06-21
**取代**: ADR-0003

## 背景

ADR-0003 选择用 Linux 硬链接创建 `workspace/fix/<fix_id>/` 隔离工作区，目标是避免复制大型 SVN 工作副本，同时保证原 SVN 工作副本不被 agent 修改。

后续讨论中，我们重新评估了该方案的安全边界：

- 硬链接方案速度快、磁盘占用低，但安全性依赖「写入前必须断开硬链接」这一实现细节。
- 如果复制范围包含 `.svn` 元数据，隔离工作区中可能存在额外 SVN 状态风险。
- Git worktree 方案隔离更强，但项目当前没有 Git 镜像；引入 `git-svn` 或 Git 镜像会增加同步和提交链路复杂度。
- 用户认可维护一个本地「干净 SVN 缓存副本」，再从缓存复制出每次修复工作区，以换取更清晰的安全边界。

## 决策

将 M2 修复隔离策略从「硬链接工作区」调整为：

```text
target_project_dir                 # 日常 / 最终提交用 SVN 工作副本，agent 不直接修改
workspace/cache/svn-clean           # 工具维护的干净 SVN 缓存副本
workspace/fix/<fix_id>/             # 每次修复从缓存复制出的隔离工作区
```

核心流程：

1. 使用已存在的 `workspace/cache/svn-clean`。
2. 创建 `workspace/fix/<fix_id>/` 前，强制校验缓存副本干净。
3. 从 `workspace/cache/svn-clean` 复制出 `workspace/fix/<fix_id>/`。
4. Agent 只修改 `workspace/fix/<fix_id>/`。
5. `run_build` / `run_tests` 只在 `workspace/fix/<fix_id>/` 中执行。
6. 人工 review 通过后，才将 diff / edits 应用到 `target_project_dir`。
7. 写回 `target_project_dir` 前，必须检查其 SVN 状态干净。

## 安全约束

### 1. 缓存副本只读给 agent

本轮实现中，`workspace/cache/svn-clean` 只允许工具执行：

```text
svn status
```

Agent 不得在缓存副本中执行代码修改、构建或测试。`svn checkout` / `svn update` 初始化或刷新缓存副本属于后续能力，不在本轮 `apply_fix` 中执行。

### 2. 创建隔离工作区前必须检查缓存干净

复制前必须执行：

```text
svn status workspace/cache/svn-clean
```

若有任何输出，拒绝创建 `workspace/fix/<fix_id>/`。

### 3. 写回提交口前必须检查提交口干净

写回 `target_project_dir` 前必须执行：

```text
svn status <target_project_dir>
```

若有任何输出，拒绝写回，提示用户先处理本地改动。

### 4. 隔离工作区可删除重建

`workspace/fix/<fix_id>/` 是一次性工作区。失败、取消或验收完成后，可以删除，不影响缓存副本和最终提交口。

## 放弃的方案

### 硬链接工作区

放弃原因：

- 保护原文件依赖每次写入前正确断开硬链接。
- 若复制 `.svn` 元数据，隔离目录可能带来 SVN 状态混淆。
- 异常恢复依赖自研 registry / restore 逻辑，长期安全边界不够直观。

### Git worktree / Git 镜像

暂不采用原因：

- 当前没有目标项目 Git 镜像。
- 从 SVN 维护 Git 镜像或 `git-svn` 会引入额外同步链路。
- 最终提交仍以 SVN 为准，短期目标是安全隔离，而不是切换版本管理模型。

保留可能性：如果后续需要更强的多轮修复历史、分支级 review 和回滚能力，可重新评估 Git worktree。

## 影响

- `apply_fix` 的工作区创建逻辑应从「硬链接复制 `target_project_dir`」改为「校验已存在的 `workspace/cache/svn-clean` 后复制缓存副本」。
- `run_build` / `run_tests` 继续在 `workspace/fix/<fix_id>/` 执行，接口可保持不变。
- `commit_fix.py` 写回前应继续检查 `target_project_dir` 干净，并在失败时 revert 已写文件。
- `config.yaml` 后续需要补充缓存相关配置，例如：

```yaml
svn_url: ""
svn_cache_dir: "workspace/cache/svn-clean"
```

## 后果

优点：

- 原 SVN 工作副本和 agent 修复工作区完全分离。
- 不再依赖硬链接断开语义保护原文件。
- 相比每次 `svn checkout`，本地复制缓存副本更快。
- 相比 Git 镜像方案，仍保持 SVN 原生工作流。

代价：

- 需要多维护一个干净 SVN 缓存副本。
- 本地磁盘占用高于硬链接方案。
- 复制大型工作副本仍有 I/O 成本。
- 本轮只实现已存在缓存副本的干净性检查；缓存初始化、刷新和清理规则是后续能力。
