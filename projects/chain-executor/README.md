# Chain 编排引擎 + 双评审机制

## 概述

为 Hermes 多 Agent 系统引入 `chain` 机制——由路由引擎驱动的工作流编排。当一个 Agent 的任务完成后，自动按预定义链条执行后续步骤。配合 `chain_executor.py` 状态机，实现实现→评审→修复循环。

## 改动清单

### 2026-06-30

| 文件 | 动作 | 说明 |
|------|------|------|
| `scripts/chain_executor.py` | 🆕 新建 | Chain 状态机引擎——`advance`模式，只产出决策 JSON，不调 delegate_task |
| `route-map/index.yaml` | 🔧 修改 | programmer 新增 3 步 chain（实现→spec评审→质量评审） |
| `route-map/routes/error-analyst.yaml` | 🔧 修改 | 新增「评审」模糊匹配规则（weight=0.8） |
| `SOUL.md` | 🔧 修改 | 旧 superpowers 管线替换为 chain_executor 调用 + chain_step_skills 映射表；新增「双评审」手动编排段；自判规则改为「仅当引擎未锁定」 |
| `contexts/agent-environment.md` | 🔧 修改 | chain 执行规则改为 chain_executor 编排 + 工具重试独立说明 |
| `contexts/chain-mechanism/README.md` | 🔧 修改 | 新增 chain_step_skills 映射规则说明 |
| `skills/spec/domain-modeling/SKILL.md` | 🆕 新建 | Matt Pocock domain-modeling 流程移植（CONTEXT.md + ADRs） |
| `skills/superpowers/references/tdd.md` | 🔧 修改 | 追加反水平切片（Anti-Pattern: Horizontal Slices）段 |
| `contexts/agent-sections/programmer.md` | 🔧 修改 | 追加「垂直切片 TDD」约束行 |

## 架构

### Chain 定义

chain 定义在 `route-map/index.yaml` 的 Agent 条目中：

```yaml
programmer:
  chain:
    - agent: programmer        # step 0: 实现
      goal: TDD 实现 + self-review
    - agent: error-analyst      # step 1: spec 合规评审
      goal: spec 合规评审
    - agent: programmer         # step 2: 代码质量评审
      goal: 代码质量评审
```

chain step **不支持 `skills` 字段**。per-step skills 映射走 SOUL.md 的 `chain_step_skills` 表，以 `{链所属Agent}@{step索引}` 为 key。

### 执行流程

```
用户输入 → route_engine → {agent, chain}
  ↓
主 Agent 循环：
  ① python3 scripts/chain_executor.py advance ...
     ← {CONTINUE: {agent, goal, skills}, ...}
  ② delegate_task(agent, goal, skills)
     ← {agent, status, output_path, findings}
  ③ 回到 ①（传入回报作为 last_result）
  ─── 直至 DONE / BLOCKED / NEEDS_CONTEXT / ERROR
```

### 状态机

| 状态 | 含义 | 主 Agent 动作 |
|------|------|-------------|
| CONTINUE | 推进到下一步 | delegate_task(next.agent, next.goal, next.skills) |
| RETRY | fix 循环 | delegate(programmer, fix) → 回到评审步 |
| BLOCKED | 阻塞 | 挂起整条链，上报诊断 |
| NEEDS_CONTEXT | 缺信息 | 转发用户，补充后重试本步 |
| DONE | 完成 | 汇总回报（含 concerns + summary） |
| ERROR | 非法状态 | 上报诊断 |

### 双评审

当用户显式说「双评审」时，路由引擎返回 `agent=error-analyst`（无 chain）。主 Agent 手动编排：

```
① delegate(error-analyst, spec 合规评审)
② 如通过 → delegate(programmer, 代码质量评审)
③ 如不通过 → 按循环逻辑处理
```

「审核」「审查」「审计」等单审路由直接委派 error-analyst，不触发双评审。

### chain_step_skills 映射

```yaml
chain_step_skills:
  programmer@0: [test-driven-development]     # programmer 链 step 0
  programmer@1: [requesting-code-review]      # programmer 链 step 1（error-analyst）
  programmer@2: [requesting-code-review]      # programmer 链 step 2（programmer）
```

key 缺失时 chain_executor 阻断执行并输出诊断。

## 验证

```bash
# 路由：审核代码 → error-analyst（无链）
uv run python3 scripts/route_engine.py route "审核一下代码"

# 路由：修复bug → programmer 3步链
uv run python3 scripts/route_engine.py route "修复这个bug"

# chain_executor 完整流程（模拟 3 步）
uv run python3 scripts/chain_executor.py advance --task_id T-TEST --chain_owner programmer \
  --chain_def '[{"agent":"programmer","goal":"TDD 实现 + self-review"},{"agent":"error-analyst","goal":"spec 合规评审"},{"agent":"programmer","goal":"代码质量评审"}]' \
  --chain_step_skills '{"programmer@0":["tdd"],"programmer@1":["review"],"programmer@2":["review"]}' \
  --last_result '{"status":"init"}'
# 然后依次传入 DONE → DONE → APPROVE
```
