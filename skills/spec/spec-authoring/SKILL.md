---
name: spec-authoring
description: 将讨论/对话/需求转化为结构化 PRD 文档
---

# Spec Authoring

## 产出物

根据已有对话内容编写 PRD（产品需求文档），包含：

### Problem Statement
用户视角的问题描述

### Solution
用户视角的解决方案

### User Stories
编号列表。格式：「作为<角色>，我想要<功能>，以便<收益>」

### Implementation Decisions
实施决策列表（模块边界、接口约定、架构选择）
不含具体文件路径或代码片段

### Testing Decisions
测试策略：测试边界层级选择、要覆盖的场景

### Open Questions
未确认的问题列表，用 [TODO: clarify] 标记

## 原则

- **不面试用户**：只综合现有对话内容，已讨论过的内容不重复问
- **模糊点用 [TODO: clarify] 占位**：不假装清晰
- **术语使用 CONTEXT.md 中的定义**：与新技能 domain-modeling 产出的共享语言保持一致

## 完成标准

PRD 产出完整且无 [TODO: clarify] 占位符 → 向主 Agent 回报 DONE。
如有占位符，在 SUMMARY 中标注未澄清项，状态为 DONE_WITH_CONCERNS。
