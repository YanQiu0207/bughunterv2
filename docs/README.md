# bughunterv2 项目文档

> 一个依托 agent、长期渐进式开发的项目：用工具增强的 agent 做线上 bug 的根因诊断与人在环修复。

## 项目定位：两大块

本项目由两个同等重要的部分组成，二者缺一不可：

- **块 A — 核心流程**：诊断 → 修复 → 验证 → 纳入版本 的工程实现（agent + 工具 + 人在环协作）。
- **块 B — 方法论沉淀**：规范、标准、文档、agent 协作机制的整理与沉淀。
  对「靠 agent 长期开发」的项目而言，清晰、结构化、可被 agent 当上下文检索的文档，是成败的关键基建，而非附属品。

## 设计原则

- **文档双读者**：所有文档同时服务于「人」与「agent」，要求结构化、概念统一、可检索。
- **设计先行**：前期重在把需求与设计做扎实，不过早编码，不过度设计。
- **渐进式**：以里程碑推进（见 `roadmap.md`），每步可用、可验证。
- **工具契约化**：外部能力统一抽象为接口契约，mock 与真实实现可热替换。

## 文档体系

```
docs/
├── README.md                          # 本文件：项目定位 + 文档导航
├── roadmap.md                         # 里程碑与渐进规划
├── glossary.md                        # 术语表（统一概念）
├── design-docs/                       # 设计文档（按 模块/功能 组织）
│   └── bugfix-agent/pipeline/
│       ├── spec.md                    #   核心流程需求与设计
│       ├── tasks.md                   #   M1 诊断 MVP 任务拆分
│       └── e2e-manual-acceptance.md   #   M1–M3 端到端手工验收清单
├── standards/                         # 规范与标准
│   ├── collaboration.md               #   协作准则（人 + agent 协作规则）
│   ├── doc-convention.md              #   文档写作规范
│   ├── coding.md                      #   编码规范                   [待建]
│   ├── tool-contract.md               #   工具接口契约规范
│   └── agent-collaboration.md         #   agent 协作 / 提示词规范    [待建]
└── adr/                               # 架构决策记录（ADR）
    ├── 0001-project-foundation-decisions.md  # 项目地基决策
    ├── 0002-diagnosis-backtrace-loop.md      # 诊断回溯循环骨架
    └── 0003-m2-fix-isolation-strategy.md     # M2 修复隔离与验证策略
```

> 标注 `[待建]` 的文件，在对应里程碑启动前创建或补齐。`tool-contract.md` 已补齐 M1/M2 工具契约。

## 当前阶段

M1–M3 原型已实现，进入真实目标项目验收阶段。

- M1：`diagnose.py` 已实现「堆栈 + 源码 → 诊断报告」。
- M2：`fix.py`、`FixAgent` 与硬链接隔离工作区已实现。
- M3A：`commit_fix.py` 已实现「已验证修复方案 → SVN 工作副本写回 / 提交」的半自动链路。
- 下一步：按 [e2e-manual-acceptance.md](design-docs/bugfix-agent/pipeline/e2e-manual-acceptance.md) 在最小 Java + SVN 项目上验收。

核心流程的需求与设计见 [design-docs/bugfix-agent/pipeline/spec.md](design-docs/bugfix-agent/pipeline/spec.md)。
