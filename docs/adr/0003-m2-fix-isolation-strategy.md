# ADR-0003：M2 修复隔离与验证策略

**状态**: 已被 ADR-0004 取代
**日期**: 2026-06-21

## 背景

ADR-0001 §7 将隔离工作区的细节设计推迟到 M2 启动前完成。M2 目标是跑通「生成修复方案 → review → 应用 → 编译 + 单测 → 提交」的人在环循环。

在设计过程中明确了以下前提条件：

- bughunterv2 与目标 Java 项目运行在**同一台 Linux 机器**上
- 目标项目通过 SVN 管理，代码仓库较大
- 验证标准：**编译通过 + 单测全绿**即可提交；运行时效果由 QA / 开发验收
- 核心约束：修复过程中原 SVN 工作副本**不能有任何改动**（即使是临时的）

## 决策

### 1. 隔离策略：硬链接工作区

使用 Linux 硬链接创建隔离工作区，而非复制目录：

```
workspace/fix/<fix_id>/    ← 硬链接自 target_project_dir（近零磁盘开销）
```

**创建方式**（Python 实现）：

```python
shutil.copytree(src, dst, copy_function=os.link)
```

**修改文件时**（apply_fix 内部）：

```python
os.unlink(workspace_file)          # 断开硬链接
with open(workspace_file, 'w') as f:
    f.write(new_content)           # 创建新 inode，原文件不受影响
```

**选择理由**：
- 硬链接 = 零额外磁盘占用、创建速度远快于复制
- 修改文件时断开硬链接，原目录文件从未被写入
- 编译和单测不连接真实数据库、不写共享日志，隔离区完全自包含

**放弃的方案**：
- 直接改原目录 + svn revert 回滚：修复期间原目录处于脏状态，老板无法继续在原目录工作，且崩溃后留下脏文件
- 完整目录复制（`cp -r`）：仓库较大，磁盘 IO 开销不可接受

### 2. 验证策略：编译 + 单测，不做运行时验证

M2 的通过标准：

1. `build_command` 执行成功（编译通过）
2. `test_command` 执行成功（单测全绿）

运行时效果（程序启动、数据库行为、业务逻辑）**不在 M2 范围**，交由 QA 和开发人员验收。

**理由**：运行时隔离需要独立数据库实例、独立日志目录、独立端口，属于完整测试环境搭建问题，复杂度与 M2 目标不匹配。运行时验证能力在 M3 引入（`start_local_server`、`query_local_db`）。

### 3. 修复方案格式：行级编辑指令

FixAgent 输出结构化 JSON，每条指令描述一处修改：

```json
[
  {
    "file": "src/com/example/OrderService.java",
    "start_line": 42,
    "end_line": 42,
    "new_content": "    if (name == null) return;\n"
  }
]
```

`apply_fix` 工具按指令顺序应用，**从后往前处理**（避免行号因先前修改而偏移）。

**选择理由**：比 unified diff 更容易让 LLM 生成、更容易被工具精确应用，不依赖外部 patch 工具。

### 4. FixAgent 架构

独立的 `FixAgent`（`src/agent/fix_agent.py`），接收 `DiagnosisReport` 作为输入，输出 `FixProposal`。

不复用 DiagnosisAgent，职责单一：DiagnosisAgent 负责「找原因」，FixAgent 负责「写代码」。

### 5. 新增配置项

`config.yaml` 新增：

```yaml
# M2：修复与验证
target_project_dir: ""        # 目标 Java 项目根目录（必填）
build_command: ""             # 编译命令，在隔离工作区目录下执行（必填）
test_command: ""              # 单测命令，在隔离工作区目录下执行（必填）
```

### 6. 人工 gate

M2 有两处强制人工确认：

| Gate | 时机 | 内容 |
|------|------|------|
| **G1 修复 review** | apply_fix 执行前 | 展示 diff，老板决定是否应用 |
| **G2 提交确认** | 编译+单测通过后 | 展示最终 diff，老板决定是否 svn commit |

两处 gate 均不可跳过（svn commit 永远不由 agent 自动执行）。

## M2 工具清单

以下工具在 `docs/standards/tool-contract.md` 追加契约定义：

| 工具 | 职责 | 人工 gate |
|------|------|-----------|
| `apply_fix` | 将行级编辑指令写入隔离工作区 | 否（写隔离区，不碰原目录） |
| `run_build` | 在隔离工作区执行 `build_command` | 否 |
| `run_tests` | 在隔离工作区执行 `test_command` | 否 |

`show_diff`（对比隔离区与原目录）作为辅助能力内置在 G1/G2 gate 逻辑中，不单独作为 agent 工具暴露。

## M2 完整流程

```
DiagnosisReport（M1 输出）
  ↓
FixAgent 分析报告，生成行级修复指令 + 可读 diff
  ↓
[G1] 老板 review diff → 同意继续 / 拒绝退出
  ↓
apply_fix：cp -rl 创建隔离工作区 → unlink + 写入修改文件
  ↓
run_build → 编译失败 → FixAgent 迭代修复 → 重新 run_build
  ↓ 编译通过
run_tests → 测试失败 → FixAgent 迭代修复 → 重新 run_build + run_tests
  ↓ 单测全绿
[G2] 老板确认最终 diff → svn commit（老板手动执行）
```

## 影响

- `docs/standards/tool-contract.md` 需追加 M2 三个工具的契约定义
- `config.yaml` 新增 `target_project_dir`、`build_command`、`test_command` 三个字段
- `src/models.py` 新增 `FixProposal`、`FixEdit` 数据模型
- `src/agent/fix_agent.py` 新建 FixAgent
- `src/tools/` 新增 `apply_fix.py`、`run_build.py`、`run_tests.py`
- 隔离工作区目录：`workspace/fix/<fix_id>/`
