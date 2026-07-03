# Main Agent Workflow Integration

How the route engine integrates into the main Agent's delegation workflow
(SOUL.md reorganisation, 2026-06-30).

## Before

The main agent's SOUL.md had a three-branch manual judgment flow:

```
判定
  ├─ 架构级 → PM-agent
  ├─ Coding → superpowers
  └─ 其余 → 非 coding → 路由(route_engine.py) → 委派
```

**Problems:**
- Route engine was mentioned but never actually called (LLM routing always)
- Route engine was only for "non-coding" tasks — architecture and coding
  tasks never went through it
- Hardcoded agent mapping ("数据分析→data-analyst") duplicated route-map rules
- Duplicate binding table section from incomplete test cleanup

## After

Route engine is the FIRST step for ALL tasks:

```
用户任务
  │
  ├─ ① route_engine.py 自动路由
  │    调用 `python3 scripts/route_engine.py route "用户输入"` 解析 JSON 输出
  │    → agent + confidence ≥ 0.5 → 锁定 Agent + skills → 直接委派
  │    → 未锁定 → 手动判定
  │
  ├─ ② 手动判定（引擎未锁定时）
  │    ├─ 架构级 → PM-agent
  │    ├─ Coding → superpowers
  │    └─ 其余 → 从绑定表选 Agent
  │
  └─ ③ 委派流程（统一）
       委派前检查（5 问 + 内容质量）→ 构造参数 → 注入执行纪律 → delegate_task → 监控 → 汇总
```

## Key Changes

| Change | Old | New |
|--------|-----|-----|
| Engine scope | Non-coding only | ALL tasks |
| Engine activation | Mentioned, not used | Called via `python3 scripts/route_engine.py route` |
| Agent selection | Hardcoded mapping | Route-map rules |
| 委派前检查 | Always 5 questions | Q3 skipped when engine locked, + Q6 content quality |
| Skills injection | Full L3 list from binding table | Engine's `skills` field (scene-specific) |

## Calling the Engine

The main agent calls the engine via terminal (NOT via execute_code, since
route_engine needs subprocess isolation):

```python
# In main agent's workflow
result = terminal("python3 scripts/route_engine.py route \"用户输入\"")
# Parse JSON from result
import json
r = json.loads(result_output)
agent = r["agent"]
method = r["method"]  # "auto" | "llm_fallback"
skills = r.get("manual_skills", [])
```

## Backup

Backup created before modification:
`/opt/data/SOUL.md.bak-20260630_105623`
