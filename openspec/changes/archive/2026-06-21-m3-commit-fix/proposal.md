# M3 — Commit Fix（自动写回 + 版本提交）

状态: Quick Draft

## 问题

M2 生成的 FixProposal 停留在本地 workspace，需要人工把修改 copy 回源码目录并手动提交 SVN。这不符合「人在环修复」的目标——人只应做决策，不应做机械操作。

## 目标

提供一条命令，人工 approve 之后，系统自动把修复写回源码目录并提交 SVN。

## 核心方案

新增 `commit_fix.py` 脚本，流程：

1. 读取 `workspace/fix/<proposal_id>.json`（FixProposal）
2. `svn update` 拉取最新源码
3. 对每个被修改文件：生成 unified diff（workspace 原始快照 vs workspace 修改版）
4. 把 diff apply 到最新源码
   - 无冲突 → `svn commit`（commit message 从 FixProposal.summary 自动生成）
   - 有冲突 → 重新跑 fix agent（基于最新源码）→ build + test → 重试 apply；超过 N 次则报错退出
5. 成功后打印 SVN revision 号

## 关键约束

- 原始 SVN 工作副本在冲突重试前不能被污染（不能先写再失败）
- fix agent 重试需要新的 fix_id（UUID），不复用旧 workspace
- 最大重试次数 N 可配置（默认 3）
- 支持任意语言项目（build/test command 已在 config 中）

## 验收标准

- [ ] 无冲突场景：一条命令完成 apply + svn commit
- [ ] 冲突场景：自动重新生成 fix 并重试，成功后 commit
- [ ] 超过最大重试次数：明确报错，SVN 工作副本保持干净
- [ ] proposal_id 不存在或 status != verified：拒绝执行
