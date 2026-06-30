# Hermes 路由引擎链（Route Chain）机制

## 概述

2026-06-30 新增的路由引擎链机制，使路由引擎在返回目标 Agent 时一并返回后续工作流链条，实现**先需求对齐 → 后拆解 → 再实现**的自动编排。

## 改动文件清单

### 路由引擎（核心）

| 文件 | 改动 |
|------|------|
| `scripts/route_engine.py` | +4 处改动（见下文） |
| `scripts/route_engine.py.bak.20260630-223240` | 改动前备份 |

### route-map 配置

| 文件 | 改动 |
|------|------|
| `route-map/index.yaml` | 新增 spec-agent 条目（priority=1），含 chain 定义；pm-agent priority 1→3 |
| `route-map/routes/spec-agent.yaml` | **新建**——做/实现/创建/开发/构建等新项目关键词匹配规则 |

### 配置与治理文件

| 文件 | 改动 |
|------|------|
| `contexts/agent-environment.md` | 新增「路由引擎链」和「NEEDS_CONTEXT 转发」章节 |
| `contexts/chain-mechanism/README.md` | **新建**——链机制的设计文档 |
| `skill-map.yaml` | 新增 spec-agent 分类（6 技能：4 L2 auto + 2 L3 manual） |
| `SOUL.md` | 绑定表新增 spec-agent 行 |
| `profiles/spec-agent/config.yaml` | **新建**——spec-agent profile 配置 |
| `profiles/spec-agent/SOUL.md` | **新建**——spec-agent 行为约束 |
| `skills/spec/spec-authoring/SKILL.md` | **新建**——PRD 编写技能 |
| `.skill-cache.json` | 重建（13 Agent） |
| `.route-cache.json` | 自动刷新 |

## 路由引擎改动详解

### diff （4 处，共 +15 行）

```diff
--- route_engine.py.bak
+++ route_engine.py
@@ -73,6 +73,7 @@ def load_route_map() -> dict:
         route_map["agents"][name] = {
             "rules": agent_data.get("rules", []),
             "priority": info.get("priority", 99),
+            "chain": info.get("chain", []),      # ← ①将 index.yaml 的 chain 传递进路由 map
         }
     ...

@@ -396,6 +397,7 @@ def route(user_input: str) -> dict:
                 ...
                 auto_skills, _manual_skills = _lookup_skills(agent_name)
+                chain = route_map.get("agents", {}).get(agent_name, {}).get("chain", [])
                 return {
                     "agent": agent_name,
                     ...
+                    "chain": chain or None,        # ← ② override 路径也返回 chain
                 }

@@ -432,6 +436,10 @@ def route(user_input: str) -> dict:
         result["auto_skills"] = auto_skills
         result["manual_skills"] = sorted(matched_skills) if matched_skills else []

+        # ── 链条提取：从 index.yaml 的 Agent chain 字段 ──
+        chain = route_map.get("agents", {}).get(target, {}).get("chain", [])
+        if chain:
+            result["chain"] = chain              # ← ③ 普通 auto/tiebreak/fallback 路径均返回 chain

     return result
```

### ① load_route_map() — chain 字段传递

```python
# 改动前：构建 agent dict 时忽略 chain
route_map["agents"][name] = {
    "rules": agent_data.get("rules", []),
    "priority": info.get("priority", 99),
}

# 改动后
route_map["agents"][name] = {
    "rules": agent_data.get("rules", []),
    "priority": info.get("priority", 99),
    "chain": info.get("chain", []),   # ← 新增
}
```

从 `index.yaml` 中每个 Agent 条目的 `chain` 字段传递到运行时 `route_map`。

### ② route() override 路径

当命中 override 规则时，同时提取目标 Agent 的 chain 并返回。

### ③ route() 正常路径

在 `evaluate() → decide()` 确定目标 Agent 后，提取其 chain 字段。仅当 chain 非空时注入 `result["chain"]`，不破坏现有调用契约。

## chain 的 YAML 定义格式

在 `route-map/index.yaml` 的 Agent 条目中：

```yaml
spec-agent:
  priority: 1
  condition: 新项目/新功能强制入口
  file: routes/spec-agent.yaml
  chain:                                      # ← 可选字段
    - agent: pm-agent                         # 第一步后续 Agent
      goal: 根据 PRD 拆解实现任务为垂直切片    # delegate_task 的 goal
    - agent: programmer                       # 第二步后续 Agent
      goal: 按拆解后的任务逐个实现
      batch: true                             # 上一步产出 N 子任务时，每个独立委派
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| chain | array | 否 | 目标 Agent 完成后的后续工作流步骤 |
| chain[].agent | string | 是 | 后续 Agent 名称（须在 index.yaml 注册） |
| chain[].goal | string | 是 | 步骤目标描述 |
| chain[].batch | bool | 否 | 上一步产出多子任务时是否批量委派 |

## 路由示例

| 用户输入 | 路由结果 | chain |
|---------|---------|-------|
|「**做**一个论坛」 | spec-agent (1.0) | pm-agent → programmer |
|「**实现**聊天功能」 | spec-agent (1.0) | pm-agent → programmer |
|「**修** bug」 | programmer (0.8) | 无 |
|「**改**样式」 | ui-designer (0.8) | 无 |

## 完整工作流

```
用户：「做一个订单管理系统」
   │
   ▼
route_engine → {agent: spec-agent, chain: [pm-agent, programmer]}
   │
   ▼
main → delegate(spec-agent)
   spec-agent → NEEDS_CONTEXT（一次性抛出所有问题）
   main → 转发用户 → 用户回答
   main → delegate(spec-agent, 带回答)
   spec-agent → DONE + PRD.md
   │
   ▼
main → 走 chain
   ├── delegate(pm-agent, context=PRD) → tasks.md（垂直切片）
   └── delegate(programmer, batch) → 逐切片实现
```

## 设计原则

1. **物理隔离**：chain 机制完全在路由引擎侧实现，子 Agent 不感知链条存在
2. **零框架改动**：不修改 Hermes delegate_task 或 subagent 机制
3. **向前兼容**：无 chain 字段的 Agent 完全不受影响；`result["chain"]` 仅在非空时出现
4. **单 Agent 无链**：'改/修/修复/优化' 类修改请求直接走 programmer，无链条
