# M1–M3 端到端手工验收清单

> 目标：在进入 M3B「本地复现能力」前，先证明现有诊断、修复、验证、SVN 写回链路能在最小 Java + SVN 项目上稳定跑通。

## 1. 验收范围

本清单覆盖：

- M1：`diagnose.py` 生成诊断报告。
- M2：`fix.py` 生成修复方案，并在硬链接隔离工作区中完成编译 + 单测。
- M3A：`commit_fix.py` 将 verified 修复方案写回 SVN 工作副本，并在人工确认后提交。

不覆盖：

- 本地服务启动。
- 本地 DB 查询。
- 线上日志搜索。
- 线上 DB 查询（永久不纳入工具范围）。

## 2. 前置条件

### 2.1 项目配置

在 `config.yaml` 中确认：

```yaml
llm_base_url: "<OpenAI-compatible API base URL>"
llm_model: "<可用模型名>"
target_project_dir: "<最小 Java + SVN 项目根目录>"
build_command: "<编译命令>"
test_command: "<单测命令>"
```

`LLM_API_KEY` 只放在环境变量中，不写入 `config.yaml`：

```powershell
$env:LLM_API_KEY = "<your-key>"
```

### 2.2 最小目标项目

准备一个最小 Java + SVN 工作副本，至少包含：

- 一个可复现 NPE 的 Java 文件。
- 一个能失败后修复通过的单测。
- 可从命令行执行的 `build_command` 和 `test_command`。

### 2.3 安全检查

执行前确认：

- `target_project_dir` 是测试用 SVN 工作副本，不是生产主工作副本。
- SVN 工作副本没有未提交改动。
- `commit_fix.py` 第一次只跑 `--dry-run`。

## 3. M1：诊断验收

### 3.1 执行命令

```powershell
python .\diagnose.py --stack .\tests\fixtures\stack_trace.txt --src .\tests\fixtures\src --config .\config.yaml
```

### 3.2 验收标准

- 终端输出包含：
  - 根因结论
  - 置信度
  - 修复方向
- `workspace/diagnosis/<diagnosis_id>.json` 存在。
- JSON 至少包含：
  - `diagnosis_id`
  - `status`
  - `input`
  - `backtrace_steps`
  - `conclusion`
- canonical NPE 场景下，结论应指向 `handle()` 传入 `null` 或等价描述。

### 3.3 失败处理

| 现象 | 处理 |
|------|------|
| 提示缺少 API key | 确认 `LLM_API_KEY` 环境变量已设置 |
| 模型调用失败 | 检查 `llm_base_url`、`llm_model` 与网关路径是否正确 |
| 找不到源码 | 检查 `--src` 是否指向 Java 源码目录 |

## 4. M2：修复与验证验收

### 4.1 执行命令

将上一步生成的诊断报告路径填入：

```powershell
python .\fix.py --report .\workspace\diagnosis\<diagnosis_id>.json --config .\config.yaml
```

### 4.2 验收标准

- `workspace/fix/<proposal_id>.json` 存在。
- `workspace/fix/<proposal_id>/` 隔离工作区存在。
- `proposal.status == "verified"`。
- 隔离工作区中的修改文件已断开硬链接，原 `target_project_dir` 文件未被修改。
- `build_command` 和 `test_command` 均在隔离工作区通过。

### 4.3 人工 gate

`fix.py` 产出 verified proposal 后，人工检查：

- 修改文件是否只覆盖诊断相关位置。
- 是否存在无关格式化、重构、命名调整。
- 修复方案是否符合最小改动原则。

未通过 review 时，不进入 M3A。

## 5. M3A：SVN 写回与提交验收

### 5.1 先跑 dry-run

```powershell
python .\commit_fix.py <proposal_id> --config .\config.yaml --dry-run
```

验收标准：

- 终端打印 unified diff。
- `target_project_dir` 不产生任何文件修改。
- 未执行 `svn commit`。

### 5.2 人工确认后提交

确认 diff 无误后，才执行：

```powershell
python .\commit_fix.py <proposal_id> --config .\config.yaml --yes
```

验收标准：

- 写回前自动执行 `svn update`。
- 本地编译和单测再次通过。
- 成功后打印 SVN revision。
- 若提交失败，已修改文件被 `svn revert` 清理。

## 6. 必测失败路径

| 场景 | 预期 |
|------|------|
| `proposal_id` 不存在 | 拒绝执行，不写文件 |
| `proposal.status != "verified"` | 拒绝执行，不写文件 |
| `--dry-run` | 只展示 diff，不写文件 |
| 目标文件已有本地未提交改动 | 拒绝执行，提示先处理 dirty 文件 |
| `build_command` 失败 | 自动 revert，拒绝提交 |
| `test_command` 失败 | 自动 revert，拒绝提交 |

## 7. 验收完成定义

同时满足以下条件，才进入 M3B：

- M1 诊断报告稳定生成。
- M2 verified `FixProposal` 稳定生成。
- M3A `--dry-run` 不污染目标项目。
- M3A `--yes` 能在测试 SVN 工作副本完成提交。
- 必测失败路径至少覆盖 `proposal_id` 不存在、dirty 文件、build 失败、test 失败。
