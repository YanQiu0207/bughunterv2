# M2：修复 Agent 与编译反馈环

**状态**: Archived
**日期**: 2026-06-21
**归档日期**: 2026-06-21
**设计文档**: `docs/adr/0003-m2-fix-isolation-strategy.md`

---

## 背景

M1 已实现诊断 MVP：输入堆栈 + 源码目录 → 输出根因结论（`DiagnosisReport`）。

M2 目标：在 M1 产出的基础上，跑通「生成修复方案 → review → 应用 → 编译 + 单测 → 提交」的人在环循环。

## 问题

1. M1 诊断结论（`fix_direction`）只有方向，没有具体代码
2. 没有机制把修复安全地写入目标项目（原 SVN 工作副本不能被污染）
3. 没有验证修复是否可行的闭环（编译、单测）

## 目标

- F2：FixAgent 读取 DiagnosisReport，生成行级代码修复方案
- F3：将修复应用到 Linux 硬链接隔离工作区（原目录全程不动）
- F4：在隔离工作区执行编译 + 单测，报错回灌 FixAgent 迭代，直到通过

## 核心方案

### 隔离策略（ADR-0003 §1）

Linux 硬链接工作区：

```
workspace/fix/<fix_id>/    ← shutil.copytree(src, dst, copy_function=os.link)
```

修改文件时先 `os.unlink` 再写入，断开硬链接，原文件不受影响。

### 修复方案格式（ADR-0003 §3）

行级编辑指令（结构化 JSON），从后往前应用避免行号偏移：

```json
[{"file": "src/Foo.java", "start_line": 42, "end_line": 42, "new_content": "    ...\n"}]
```

### 验证标准（ADR-0003 §2）

编译通过 + 单测全绿 → 人工确认 → svn commit（老板手动）。
运行时验证由 QA 负责，不在 M2 范围。

### 人工 Gate（ADR-0003 §6）

- G1：apply_fix 执行前，老板 review diff
- G2：编译+单测通过后，老板确认 svn commit

## 需求

### 功能性需求

1. **FixAgent**：`src/agent/fix_agent.py`，接收 `DiagnosisReport`，调用 `apply_fix` / `run_build` / `run_tests` 工具，循环迭代直到通过或放弃
2. **apply_fix 工具**：`src/tools/apply_fix.py`，创建硬链接工作区并应用行级编辑
3. **run_build 工具**：`src/tools/run_build.py`，在隔离工作区执行可配置 build_command
4. **run_tests 工具**：`src/tools/run_tests.py`，在隔离工作区执行可配置 test_command
5. **数据模型**：`FixEdit`、`FixProposal` 加入 `src/models.py`
6. **Config 扩展**：`target_project_dir`、`build_command`、`test_command` 加入 `src/config.py`
7. **CLI 入口**：`fix.py`（参照 `diagnose.py`），输入 DiagnosisReport JSON 路径

### 非功能性需求

- 工具输出上限：stdout/stderr 截断至 200 行（防 context 爆炸）
- 命令超时：build_command 120s，test_command 300s
- 原目录零接触：apply_fix 只写 `workspace/fix/<fix_id>/`，禁止写 `target_project_dir`

## 验收标准

1. `pytest tests/` 全绿（含新增单元测试）
2. `python fix.py --report workspace/diagnosis/xxx.json --config config.yaml` 可运行，在隔离工作区产出修复
3. apply_fix 后原目录文件内容与修改前完全一致（inode 验证）
4. 编译/单测报错能回灌 FixAgent 并产出迭代修复

## 不在范围

- 运行时验证（启动程序、连数据库）→ M3
- svn commit 自动化 → M4
- Windows 支持 → 不在计划中（部署在 Linux）
