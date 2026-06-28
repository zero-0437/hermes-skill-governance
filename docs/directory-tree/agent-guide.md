# Agent 体系指南

> **阅读难度**: ⭐⭐☆☆☆ (查阅型)  
> **目标读者**: 需要了解各 Agent 分工的委派者、需要新增 Agent 的架构师

## 目录

1. [Agent 体系概览](#agent-体系概览)
2. [调度层 Agent](#调度层-agent)
3. [执行层 Agent](#执行层-agent)
4. [L2 vs L3 加载策略](#l2-vs-l3-加载策略)
5. [技能所有权规则](#技能所有权规则)

---

## Agent 体系概览

目录树管理 **12 个 Agent**，分为 **调度层**（1 个）和 **执行层**（11 个）：

```
                    ┌──────────────────┐
                    │    pm-agent      │ ← 调度层：技术架构师 + 执行调度者
                    │   (只委派不干活)   │
                    └───────┬──────────┘
                            │ 委派
          ┌─────────────────┼────────────────────┐
          │                 │                    │
    ┌─────▼─────┐   ┌──────▼──────┐   ┌────────▼────────┐
    │programmer │   │error-analyst│   │  data-analyst    │
    │ 代码编写   │   │ 错误诊断    │   │   数据搜索        │
    └───────────┘   └─────────────┘   └─────────────────┘
    ┌───────────┐   ┌─────────────┐   ┌─────────────────┐
    │ui-designer│   │document-    │   │   file-ops       │
    │  前端设计  │   │processor    │   │   文件操作        │
    └───────────┘   │  文档处理    │   └─────────────────┘
                    └─────────────┘
    ┌───────────┐   ┌─────────────┐   ┌─────────────────┐
    │synology-  │   │memory-agent │   │prompt-engineer   │
    │helper     │   │ 记忆管理    │   │  Prompt 工程      │
    │ NAS 运维  │   └─────────────┘   └─────────────────┘
    └───────────┘
    ┌───────────┐   ┌─────────────┐
    │reality-   │   │docs-writer  │
    │checker    │   │ 技术文档     │
    │ 集成测试   │   └─────────────┘
    └───────────┘
```

---

## 调度层 Agent

### pm-agent — 技术架构师 + 执行调度者

| 属性 | 值 |
|------|----|
| **角色** | 方案设计 → 任务拆解 → 委派 → 闭环汇报 |
| **工具集** | delegate_task, terminal, session_search |
| **最大轮次** | 60 |
| **L2 auto (7)** | `multi-agent-arch`, `delegation-multi-agent`, `skill-map-maintenance`, `skill-creator`, `plan`, `engineering-software-architect`, `engineering-multi-agent-systems-architect` |
| **L3 manual (12+)** | `architecture-integrity-check`, `multi-agent-swarm`, `product-manager`, `teacher`, `superpowers`, `hermes-agent`, `hermes-multi-agent-profiles`, `hermes-multi-agent-setup`, `hermes-subagent-profile`, `multi-agent-profile-setup`, `agent-delegation-setup`, `hermes-agent-skill-authoring` |

**核心规则**（摘自 SOUL.md）：
- 只委派不干活，绝不亲自执行具体任务
- 委派必须从白名单选取，白名单外一律禁用
- 架构级任务自动转 pm-agent 自身处理

---

## 执行层 Agent

### programmer — 代码编写与调试

| 属性 | 值 |
|------|----|
| **角色** | 按 TDD 纪律交付可工作代码 |
| **L2 auto (5)** | `test-driven-development`, `systematic-debugging`, `simplify-code`, `engineering-minimal-change-engineer`, `requesting-code-review` |
| **L3 manual (16)** | `spike`, `compatibility-audit`, `codebase-inspection`, `github-code-review`, `github-auth`, `github-issues`, `github-pr-workflow`, `github-repo-management`, `github-search`, `engineering-git-workflow-master`, `node-inspect-debugger`, `python-debugpy`, `claude-code`, `codex`, `opencode`, `hermes-agent-skill-authoring` |

**特点**：L3 manual 包含丰富的委派工具（claude-code, codex, opencode），可进一步下放子任务。技能 `codebase-inspection` 在此 Agent 为审查工具（`layer: 3 / manual`），在 error-analyst 则为诊断必备（`layer: 2 / auto`），两者均标注 `intentional: true`。

---

### error-analyst — 错误诊断 + 代码审查

| 属性 | 值 |
|------|----|
| **角色** | 只读分析，不执行修改 |
| **L2 auto (5)** | `systematic-debugging`, `codebase-inspection`, `requesting-code-review`, `engineering-sre`, `postmortem-analyst` |
| **L3 manual (4)** | `network-debugging`, `github-code-review`, `engineering-security-engineer`, `engineering-incident-response-commander` |

**特点**：专精诊断和复盘，`codebase-inspection` 在此 Agent 是 L2 auto（核心能力）。强调"只读分析"——发现错误后交由 programmer 修复。

---

### data-analyst — 数据搜索与分析

| 属性 | 值 |
|------|----|
| **角色** | 多渠道信息检索，先判再搜 |
| **L2 auto (1)** | `search-backend-evaluation` |
| **L3 manual (9)** | `github-search`, `maps`, `xurl`, `arxiv`, `blogwatcher`, `polymarket`, `llm-wiki`, `youtube-content`, `jupyter-live-kernel` |

**特点**：核心技能是通过 `search-backend-evaluation` 判定该用哪个搜索通道，再按需激活对应的 L3 工具。`llm-wiki` 在此 Agent 是按需工具（`layer: 1 / manual`），在 memory-agent 是角色技能（`layer: 2 / auto`）。

---

### ui-designer — 前端与视觉设计

| 属性 | 值 |
|------|----|
| **角色** | 设计实现 + 创意生成 |
| **L2 auto (1)** | `frontend-design` |
| **L3 manual (11)** | `taste-skill`, `popular-web-designs`, `claude-design`, `sketch`, `pretext`, `architecture-diagram`, `baoyu-infographic`, `excalidraw`, `p5js`, `design-md`, `touchdesigner-mcp` |

**特点**：L3 manual 包含丰富的可视化工具（excalidraw, architecture-diagram, p5js）和创意编码工具（touchdesigner-mcp, design-md）。

---

### document-processor — 文档处理与转换

| 属性 | 值 |
|------|----|
| **角色** | 格式转换 + 公文排版 |
| **L2 auto (5)** | `pdf`, `docx`, `xlsx`, `pptx`, `markitdown` |
| **L3 manual (6)** | `ocr-and-documents`, `doc-coauthoring`, `civil-servant`, `engineering-technical-writer`, `humanizer-zh` |

**特点**：L2 auto 全是文档格式处理工具（从 shared.文档 继承，但 load 覆盖为 auto）。`engineering-technical-writer` 标注 `intentional: true`——本 Agent 用于技术文档生成，但也可能交由 docs-writer 专门处理（两个 Agent 对该技能有不同 layer/load）。

---

### file-ops — 文件操作专员

| 属性 | 值 |
|------|----|
| **角色** | 读写/备份/SSH，不执行代码 |
| **L2 auto (1)** | `token-efficient-file-ops` |
| **L3 manual (3)** | `ssh-172`, `ssh-remote-access`, `github-push` |

**特点**：`ssh-172` 标注 `intentional: true`——在此 Agent 是按需工具（`layer: 1 / manual`），在 synology-helper 是角色技能（`layer: 2 / auto`）。两个 Agent 对该技能的 layer/load 差异是有意设计的。

---

### synology-helper — 群晖 NAS 运维

| 属性 | 值 |
|------|----|
| **角色** | SSH 命令 + 架构备份 |
| **L2 auto (2)** | `ssh-172`, `hermes-full-backup` |
| **L3 manual (2)** | `ssh-remote-access`, `hermes-maintenance` |

**特点**：`ssh-172` 在此 Agent 是 L2 auto（角色核心技能），区别于 file-ops 的 L1 manual。`ssh-remote-access` 通过 `ref: shared.远程.ssh-remote-access` 引用共享定义。

---

### memory-agent — 记忆与知识管理

| 属性 | 值 |
|------|----|
| **角色** | 会话检索 + 知识库维护 |
| **L2 auto (2)** | `llm-wiki`, `obsidian` |
| **L3 manual (0)** | — |

**特点**：12 个 Agent 中唯一没有 L3 manual 技能的 Agent。所有能力均为 L2 auto，启动即加载。`llm-wiki` 在此 Agent 是角色技能（`layer: 2 / auto`），在 data-analyst 是按需工具（`layer: 1 / manual`）。

---

### prompt-engineer — Prompt 工程

| 属性 | 值 |
|------|----|
| **角色** | SOUL.md 审计 + Prompt 优化 |
| **L2 auto (1)** | `engineering-prompt-engineer` |
| **L3 manual (0)** | — |

**特点**：最精简的 Agent，仅 1 个 L2 auto 技能，无 L3 manual。专精单一领域，无需额外工具。

---

### reality-checker — 集成测试与现实检验

| 属性 | 值 |
|------|----|
| **角色** | 阻止幻想式审批，要求压倒性证据 |
| **L2 auto (1)** | `dogfood` |
| **L3 manual (0)** | — |

**特点**：默认判定 `NEEDS WORK`，无压倒性证据不得认证为 `PASS`。工具集限定为 terminal, file, browser, vision, web。专属约束禁止主观判断（"看起来不错"、"应该能工作"）。

---

### docs-writer — 技术文档工程师

| 属性 | 值 |
|------|----|
| **角色** | README/API 参考/教程/概念指南写作，docs-as-code 基础设施 |
| **L2 auto (1)** | `engineering-technical-writer` |
| **L3 manual (2)** | `doc-coauthoring`, `humanizer-zh` |

**特点**：`engineering-technical-writer` 在此 Agent 是 L2 auto（角色核心技能），在 document-processor 是 L3 manual。工具集限定为 terminal, file, web。写作纪律要求每个代码块必须在 terminal 运行通过。

---

## L2 vs L3 加载策略

### L2 auto（自动加载）

- Agent 启动时自动注入上下文的技能
- 通常是该 Agent 角色的核心竞争力
- 委派时无需在 `skill_required` 中显式声明
- **策略**：够用但不过载，避免上下文膨胀

### L3 manual（按需加载）

- 必须在委派的 `skill_required` 参数中显式指定后才激活
- 通常是辅助/扩展能力或低频使用的工具
- **策略**：按需激活，节省上下文 token

### 委派示例

```json
{
  "task_id": "T-03",
  "task_description": "将项目 README 翻译为中文并润色",
  "skill_required": "doc-coauthoring, humanizer-zh",
  "input_context": "文件: /opt/data/README.md",
  "output_format": "只交翻译后的文件路径",
  "dependencies": null
}
```

此委派给 `docs-writer` 时，`engineering-technical-writer`（L2 auto）自动可用，`doc-coauthoring` 和 `humanizer-zh`（L3 manual）通过 `skill_required` 显式激活。

---

## 技能所有权规则

### 独占技能

大多数技能仅属于单一 Agent，不存在跨 Agent 共享问题。

### 共享技能（含 intentional 标注）

| 技能 | 使用 Agent | layer/load | intentional |
|------|-----------|------------|:-----------:|
| `codebase-inspection` | programmer | 3 / manual | ✅ |
| | error-analyst | 2 / auto | ✅ |
| `ssh-172` | file-ops | 1 / manual | ✅ |
| | synology-helper | 2 / auto | ✅ |
| `llm-wiki` | data-analyst | 1 / manual | ✅ |
| | memory-agent | 2 / auto | ✅ |
| `engineering-technical-writer` | document-processor | 3 / manual | ✅ |
| | docs-writer | 2 / auto | ✅ |
| `humanizer-zh` | document-processor | 1 / manual | ✅ |
| | docs-writer | 3 / manual | ✅ |

所有共享技能均通过 `intentional: true` 告知校验器：「此处的层级/加载策略差异是故意的，非配置错误」。若无此标注，校验器会报告 WARN。

### 全局 shared 工具

`shared` 区定义的所有 L1 工具（pdf, docx, xlsx, github-search, ssh-172 等）由 `rebuild-cache.py` 自动合并到每个 Agent 的 manual 列表中。Agent 无需在 skill-map.yaml 中显式声明即可使用它们，前提是委派时指定了 `skill_required`。
