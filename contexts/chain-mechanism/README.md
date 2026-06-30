# 路由引擎链（Route Chain）机制

## 概述

路由引擎链（chain）是一种工作流编排机制：当用户输入路由到某个 Agent 时，路由引擎一并提出「这个任务后续还有谁」。主 Agent 先委派目标 Agent，完成后自动按链条继续执行。

```
路由前                   路由结果                   执行
用户输入 ──→ route_engine ──→ {agent, chain} ──→ 主 Agent
                                                      │
                                                      ├── delegate(agent) ← 第一步
                                                      ├── delegate(chain[0]) ← 第二步
                                                      └── delegate(chain[1]) ← 第三步
```

## 历史

最初设计为子 Agent 回报中附加 `[CHAIN_NEXT]` 段（2026-06-30，见 v1 存档）。后改为路由引擎主导：链条作为 index.yaml 中 Agent 的路由属性，路由时一并返回。子 Agent 无需感知链条存在。

## 定义位置

chain 定义在 `route-map/index.yaml` 的 Agent 条目中：

```yaml
spec-agent:
  priority: 1
  condition: 新项目/新功能强制入口
  file: routes/spec-agent.yaml
  chain:                                      # ← 可选
    - agent: pm-agent
      goal: 根据 PRD 拆解实现任务为垂直切片
    - agent: programmer
      goal: 按拆解后的任务逐个实现
      batch: true
```

## Schema

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| chain | array | 否 | 可选。定义目标 Agent 执行完成后，自动执行的后续步骤 |
| chain[].agent | string | 是 | 后续 Agent 名称（必须存在于 index.yaml） |
| chain[].goal | string | 是 | 步骤目标描述（作为 delegate_task 的 goal） |
| chain[].batch | bool | 否 | 如果上一步产出多个子任务，是否每个独立委派（默认 false） |

## 执行规则

1. 路由引擎返回 `{agent, confidence, chain?, ...}`
2. `agent` 是第一步要委派的 Agent
3. 如果 `chain` 存在，主 Agent 在第一步完成后按顺序执行后续步骤
4. 每步的 context 自动注入上一步的产出路径
5. batch=true 时：如上一步拆出 N 个子任务，对每个子任务单独委派一次
6. 任一步返回 BLOCKED → 挂起整条链，不继续
7. 所有步骤完成 → 汇总全部产出回报用户

## 无链路的普通路由

Agent 在 index.yaml 中不设 chain 字段 → 路由引擎返回 `{agent}`，无 chain → 主 Agent 走旧逻辑（委派单一 Agent，收回报，完事）。

## 维护

- 新增链条：只在 index.yaml 改对应 Agent 的 chain 字段
- 移除链条：删除 chain 字段
- 修改链条步骤：改 index.yaml 中的 chain 数组
- 路由引擎和子 Agent 均不需要改动

## 链路的两种触发方式

| 方式 | 主导方 | 数据来源 | 优先级 |
|------|--------|---------|--------|
| 路由引擎链（v2） | route_engine | index.yaml 中 Agent 的 `chain` 字段 | **高**（主 Agent 优先使用） |
| CHAIN_NEXT（v1 存档） | 子 Agent 回报 | 回报文本中的 `[CHAIN_NEXT]` 段 | 低（仅兜底） |

## v1: CHAIN_NEXT（子 Agent 回报驱动）— 已存档

v1 设计由子 Agent 在回报中附加 `[CHAIN_NEXT]` 段，由主 Agent 解析执行。v2 由路由引擎主导后，v1 降级为兜底方案：当 index.yaml 中无 chain 字段时，仍可解析子 Agent 回报中的 CHAIN_NEXT 段。

v1 相关文件：
- `contexts/agent-environment.md` §§CHAIN_NEXT Schema 段
- `contexts/chain-next-handler.md`（解析/串行/兜底逻辑）
- `skills/spec/spec-authoring/SKILL.md`（产出后链条定义）
