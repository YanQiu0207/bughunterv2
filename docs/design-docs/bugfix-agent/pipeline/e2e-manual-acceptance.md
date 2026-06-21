# M1–M3 端到端手工验收清单

> 目标：在进入 M3B「本地复现能力」前，先证明现有诊断、修复、验证、SVN 写回链路能在最小 Java + SVN 项目上稳定跑通。

## 1. 验收范围

本清单覆盖：

- M1：`diagnose.py` 生成诊断报告。
- M2：`fix.py` 生成修复方案，并在从干净 SVN 缓存副本复制出的隔离工作区中完成编译 + 单测。
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
svn_cache_dir: "workspace/cache/svn-clean"
build_command: "<编译命令>"
test_command: "<单测命令>"
```

`LLM_API_KEY` 只放在环境变量中，不写入 `config.yaml`。Git Bash 下执行：

```bash
export LLM_API_KEY="<your-key>"
```

> 路径约定：Git Bash 中可以直接使用 Windows 路径（如 `E:/tmp/java-svn-target`），也可以使用类 Unix 路径（如 `/e/tmp/java-svn-target`）。建议在 `config.yaml` 中统一使用 `E:/...` 这种正斜杠 Windows 路径，便于 Python、SVN 与 Maven 一起解析。

### 2.2 最小目标项目

准备一个最小 Java + SVN 工作副本，至少包含：

- 一个可复现 NPE 的 Java 文件。
- 一个能失败后修复通过的单测。
- 可从命令行执行的 `build_command` 和 `test_command`。

### 2.3 安全检查

执行前确认：

- `target_project_dir` 是测试用 SVN 工作副本，不是生产主工作副本。
- `workspace/cache/svn-clean` 是工具维护的干净 SVN 缓存副本。
- `workspace/cache/svn-clean` 与 `target_project_dir` 都没有未提交改动。
- `commit_fix.py` 第一次只跑 `--dry-run`。

Git Bash 下可用以下命令检查：

```bash
svn status workspace/cache/svn-clean
svn status "E:/tmp/java-svn-target"
```

两条命令都应该没有输出。

## 3. M1：诊断验收

### 3.1 执行命令

Git Bash 下执行：

```bash
python ./diagnose.py \
  --stack ./tests/fixtures/stack_trace.txt \
  --src ./tests/fixtures/src \
  --config ./config.yaml
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

```bash
python ./fix.py \
  --report "./workspace/diagnosis/<diagnosis_id>.json" \
  --config ./config.yaml
```

### 4.2 验收标准

- `workspace/fix/<proposal_id>.json` 存在。
- `workspace/fix/<proposal_id>/` 隔离工作区存在。
- `proposal.status == "verified"`。
- 隔离工作区由 `workspace/cache/svn-clean` 复制而来，原 `target_project_dir` 文件未被修改。
- `build_command` 和 `test_command` 均在隔离工作区通过。

### 4.3 人工 gate

`fix.py` 产出 verified proposal 后，人工检查：

- 修改文件是否只覆盖诊断相关位置。
- 是否存在无关格式化、重构、命名调整。
- 修复方案是否符合最小改动原则。

未通过 review 时，不进入 M3A。

## 5. M3A：SVN 写回与提交验收

### 5.1 先跑 dry-run

```bash
python ./commit_fix.py "<proposal_id>" --config ./config.yaml --dry-run
```

验收标准：

- 终端打印 unified diff。
- `target_project_dir` 不产生任何文件修改。
- 未执行 `svn commit`。

### 5.2 人工确认后提交

确认 diff 无误后，才执行：

```bash
python ./commit_fix.py "<proposal_id>" --config ./config.yaml --yes
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

### 6.1 Git Bash 建议执行顺序

#### `proposal_id` 不存在

```bash
python ./commit_fix.py "00000000-0000-4000-8000-000000000000" \
  --config ./config.yaml \
  --dry-run
```

预期：拒绝执行，不写任何文件。

#### 目标工作副本有 dirty 文件

先故意制造一个本地改动：

```bash
printf '\n// dirty probe\n' >> "E:/tmp/java-svn-target/src/main/java/path/to/File.java"
python ./commit_fix.py "<proposal_id>" --config ./config.yaml --dry-run
svn revert "E:/tmp/java-svn-target/src/main/java/path/to/File.java"
```

预期：`commit_fix.py` 拒绝执行，并提示目标文件有未提交改动。

#### 干净缓存副本有 dirty 文件

```bash
printf 'dirty\n' > ./workspace/cache/svn-clean/__dirty_probe.txt
python ./fix.py \
  --report "./workspace/diagnosis/<diagnosis_id>.json" \
  --config ./config.yaml
rm ./workspace/cache/svn-clean/__dirty_probe.txt
```

预期：`fix.py` 在 `apply_fix` 阶段拒绝，提示 SVN cache 有 local changes。

#### build 或 test 失败

临时把 `config.yaml` 中的 `build_command` 或 `test_command` 改成必失败命令，例如：

```yaml
build_command: "bash -lc 'exit 1'"
```

再执行：

```bash
python ./commit_fix.py "<proposal_id>" --config ./config.yaml --yes
```

预期：写回后验证失败，自动 `svn revert`，拒绝提交。测完后恢复原来的 `build_command` / `test_command`。

## 7. 验收完成定义

同时满足以下条件，才进入 M3B：

- M1 诊断报告稳定生成。
- M2 verified `FixProposal` 稳定生成。
- M2 应用修改前会检查 `workspace/cache/svn-clean` 干净。
- M3A `--dry-run` 不污染目标项目。
- M3A `--yes` 能在测试 SVN 工作副本完成提交。
- 必测失败路径至少覆盖 `proposal_id` 不存在、dirty 文件、build 失败、test 失败。

## 8. Git Bash 快速命令清单

如果前置配置都已经填好，可以按下面顺序跑：

```bash
export LLM_API_KEY="<your-key>"

svn status workspace/cache/svn-clean
svn status "E:/tmp/java-svn-target"

python ./diagnose.py \
  --stack ./tests/fixtures/stack_trace.txt \
  --src ./tests/fixtures/src \
  --config ./config.yaml

python ./fix.py \
  --report "./workspace/diagnosis/<diagnosis_id>.json" \
  --config ./config.yaml

python ./commit_fix.py "<proposal_id>" --config ./config.yaml --dry-run

python ./commit_fix.py "<proposal_id>" --config ./config.yaml --yes
```

其中 `<diagnosis_id>` 从 `workspace/diagnosis/*.json` 文件名获取，`<proposal_id>` 从 `fix.py` 终端输出或 `workspace/fix/*.json` 文件名获取。
