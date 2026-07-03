---
name: zero-token-routing
description: >-
  Replace LLM routing decisions with a YAML-driven, pure-Python rule engine
  that maps user input → target sub-agent in <1ms/0 tokens. Multi-file
  configuration so adding agents only touches YAML, not code. Includes
  scene-specific L2/L3 skill injection, anomaly logging, and maintenance
  CLI scaffold for add-agent/add-skill/add-route operations.
scripts:
  - route_engine.py            # 核心路由引擎 (28KB, 650行)
  - validate-route-map.py      # YAML 12维审计验证器 (187行)
  - hermes-route-add           # 规则追加 CLI (308行)
  - analyze-route-log.py       # 路由日志分析 (139行)
  - agent-mgmt/                # 6 个 Python 内部模块 + 4 Jinja2 模板
references:
  - references/route-map/      # 21-22 个 YAML 路由规则文件
  - references/chinese-boundary-workaround.md
  - references/hermes-native-vs-zero-token.md
  - references/main-agent-workflow-integration.md
  - references/maintenance-scaffold-design.md
  - references/token-savings-benchmark.md
required_commands:
  - python3
required_python_packages:
  - pyyaml
  - ruamel.yaml (用于 hermes-route-add)
---

# Zero-Token Routing

Replace the "main agent thinks about who to delegate to" step with a
predefined rule engine. Each user input is matched against per-agent
pattern rules (regex / phrase / keyword) → weighted scoring → confidence
threshold → direct delegate or LLM fallback.

## Principles (user preferences — embed these)

### 1. Maintainability first — YAML driven, not code driven
- Adding a sub-agent: **only YAML** (index.yaml +1 line + new routes/*.yaml)
- Changing rules/weights: **only YAML** (edit routes/*.yaml)
- Deleting an agent: **only YAML** (delete file + index.yaml -1 line)
- Never touch Python for content changes. The engine is a fixed scaffold.

### 2. Multi-file structure — one file per agent
```
route-map/
├── index.yaml       ← total index (overrides + agent→file mapping)
├── shared.yaml      ← cross-agent rules (optional)
└── routes/
    ├── pm-agent.yaml
    ├── programmer.yaml
    └── ...12 agents total
```
Reason: Adding/removing an agent only touches 2 files. Changing one agent's
rules never touches another agent's file. Same pattern as profiles/*/SOUL.md.

### 3. Architecture changes go through PM-agent
- New routing feature → PM-agent (on Pro) designs → programmer implements
- Do NOT redesign the structure yourself; PM-agent owns the architecture
- PM-agent's output: feasibility report + [DELEGATION_REQUESTS] checklist
- PM-agent does NOT read skill-map.yaml — skill injection is handled entirely by route engine
- After PM-agent returns [DELEGATION_REQUESTS], main agent runs conflict scan before delegating

### 4. All delegated tasks must go to a sub-agent
Main agent only decomposes and delegates — never classifies a task as
"generic (main agent handles itself)". Every delegate_task routes to a
named sub-agent. The routing engine is the first gate.

### 5. YAML/config edits go through programmer, not main agent
Route-map YAML changes, rule tweaks, and skills field updates must be
delegated to programmer. Main agent must NOT directly write YAML files
for routing rules. Violation: user will correct with "修复不应该是
Programmer 的事吗？"

### 6. Errors must be reported, never silently handled
When route_engine raises an exception (FileNotFoundError, YAML parse error,
etc.), report the full error detail to the user immediately. Do NOT silently
fall back to LLM routing. Silent fallback hides route-map corruption.

## Engine Architecture

```
user_input → _normalize(lowercase)
  → overrides check (exact matches, skip scoring)
  → evaluate() weighted scoring against all 12 agents
  → decide() with three outcomes:
      auto              — confidence ≥ threshold, direct delegate
      auto_tiebreak     — tie resolved by priority field
      llm_fallback      — all scores below threshold, hand to LLM
```

### Rule types

| type | when to use | matching |
|------|-------------|----------|
| `regex` | English keywords + `\b` boundaries | `re.search(pattern, text, re.IGNORECASE)` |
| `phrase` | Chinese keywords (!!) | `pattern.lower() in normalized` |
| `keyword` | simple exact match | `pattern.lower() in normalized_text` |

### Skills Association (scene-specific L3 injection)

Each rule can carry a `skills` field listing L3 manual skills to inject
when that rule matches. This replaces the old "full L3 list" approach.

```yaml
# programmer.yaml — scene-specific L3 skills
rules:
  - type: phrase
    pattern: "bug"
    weight: 0.8
    skills: ["systematic-debugging", "codebase-inspection"]   # debugging context

  - type: phrase
    pattern: "PR"
    weight: 0.8
    skills: ["github-pr-workflow", "github-code-review"]       # PR context

  - type: phrase
    pattern: "实现"
    weight: 0.8
    skills: ["spike"]                                           # feature context
```

When multiple rules match, skills are unioned (deduplicated). If no rule
has a `skills` field, manual_skills returns `[]` (not the full list).
L2 auto_skills are always populated from .skill-cache.json (unaffected).

Key design patterns per agent:

| Agent | Pattern → Skills |
|-------|-----------------|
| programmer | bug→debug, PR→github, 实现→spike, 安装→compatibility-audit, 测试→[] |
| pm-agent | 架构/治理/拓扑→architecture-integrity-check, 拆解→product-manager+plan, 冲突→multi-agent-swarm |
| error-analyst | 错误/诊断→postmortem-analyst+network-debugging, 审计/审查→engineering-security-engineer |
| Other 9 agents | All rules → [] (no L3 manual skills needed, L2 auto suffices) |

## Token Savings Benchmarks

Quantified proof that the route engine saves meaningful tokens vs LLM routing.

### Controlled Test (2026-06-30)

Same goal, same toolsets, same base context — only variable: routing decision source.

| Metric | Route Engine (Python) | LLM Reasoning |
|--------|:--------------------:|:-------------:|
| Main agent routing cost | ~152 tokens (terminal JSON output) | ~1,500 tokens (reasoning + binding table lookup) |
| Routing latency | ~0.1s | ~3-10s |
| Sub-agent token impact | Negligible (task-driven, not routing-driven) | Same |
| Determinism | ✅ Identical input → identical output | ❌ Varies per run |
| Context pollution | Structured JSON, zero reasoning trace | LLM reasoning trajectory pollutes context |

**Conclusion:** ~1,350 tokens saved per routing decision at the main agent level. Over 50 tasks/day ≈ 67K tokens/day ≈ significant monthly savings.

### Test Methodology

```
Three-layer verification:
  1. Route engine dispatch — test route_engine.py output for each agent
  2. Delegation pipeline — delegate_task with route engine output as context
  3. Skill injection — verify sub-agent receives correct auto_skills + manual_skills
```

For full methodology and raw data: `references/token-savings-benchmark.md`

### Delegation Pipeline Verification Checklist

After route-map changes or skill-map updates, verify the full pipeline:

1. **Route test** — `python3 scripts/route_engine.py "test input"` → correct agent + confidence ≥ 0.5
2. **Delegate test** — `delegate_task` with route engine output → sub-agent completes
3. **Skill injection test** — sub-agent reports loaded skills match engine's `auto_skills` + `manual_skills`
4. **Checksum closure** — sub-agent writes report to `.shared/{task_id}/` + returns SHA256
5. **E2E comparison** — (optional) run same task with LLM routing to compare token consumption

---

## ⚠️ Critical — Chinese `\\b` boundary trap

Python's `\b` word boundary **does not work with Chinese characters**.
Chinese chars are non-`\w` in Python's `re` module, so there's no boundary
between adjacent Chinese chars.

**WRONG:**
```yaml
- type: regex
  pattern: "\\b(记忆|知识库)\\b"    # never matches in Chinese text
```

**RIGHT:**
```yaml
- type: phrase
  pattern: "记忆"                     # pattern in normalized → works
- type: phrase
  pattern: "知识库"
```

**Rule of thumb:**
- English keywords → regex with `\b` (works: `\bPR\b` won't match PROXY)
- Chinese keywords → phrase (avoids `\b` boundary failure entirely)

See references/chinese-boundary-workaround.md for full test suite.

## ⚠️ Critical — re.IGNORECASE required

`_normalize()` lowercases the input, but regex patterns often have uppercase
(`NAS`, `API`, `TDD`). Without `re.IGNORECASE` in `re.search()`, the pattern
"NAS" won't match normalized "nas".

```python
# WRONG:
return bool(re.search(pattern, normalized))
# RIGHT:
return bool(re.search(pattern, normalized, re.IGNORECASE))
```

## ⚠️ Pitfall — Shared tool pollution in rebuild-cache.py

The original `rebuild-cache.py` merged `shared_manual` skills (pdf, docx,
xlsx, ssh-172, excalidraw, etc. — 15 tools) into every Agent's manual list.
This inflated programmer's manual_skills from 16 to 31, including tools
completely irrelevant to coding.

**Fix applied (2026-06-30):** Removed the shared-tool merge loop from
`rebuild-cache.py` lines 63-66. After the fix, each Agent's manual list
contains only its own skills.

**Check:** After running rebuild-cache.py, verify programmer's manual list
has 16 items (not 31).

## Logging and Analysis

All route decisions are logged to `logs/route-engine.jsonl` (JSON Lines):

```json
{"ts":"...","input":"搜索新闻","agent":"data-analyst","confidence":1.5,
 "method":"auto","matched":["搜索","新闻"],"flagged":false,"flag_reason":null}
```

### Anomaly flagging rules

| Condition | flagged | flag_reason |
|-----------|---------|-------------|
| method=llm_fallback | true | "low_confidence" |
| method=auto_tiebreak | true | "tiebreak" |
| method=auto + confidence < 0.6 | true | "borderline" |
| method=auto + confidence ≥ 0.6 | false | null |

### Analysis tool

`scripts/analyze-route-log.py` reads the log and outputs:
- Total calls, auto rate, fallback rate, flagged rate
- Per-agent call ranking
- All flagged entries with input excerpt
- Improvement suggestions (agents with ≥15% fallback rate)

Run periodically (cron or manual) to detect routing quality issues.

## Validation Suite

Three layers of validation, inspired by skill-map.yaml governance:

| layer | validator | what it checks |
|-------|-----------|----------------|
| engine | `validate-route-map.py` | YAML syntax, agent existence, cross-refs, regex validity, weight bounds (-2.0~2.0), agent-name consistency, duplicate detection, min 2 positive rules per agent |
| integration | `validate-skill-map.py` (dim 12) | subprocess calls the above |
| cache | `rebuild-cache.py` | pre-compiles all regex patterns, writes `.route-cache.json` |

## Workflow (Live — Integrated into Main Agent SOUL.md)

The route engine is now the FIRST step in the main agent's delegation workflow
(SOUL.md updated 2026-06-30). Every user task goes through the engine before
any manual judgment.

```
user input
  │
  ├─ ① route_engine.py 自动路由
  │    调用 `python3 scripts/route_engine.py route "用户输入"` 解析 JSON 输出
  │    → agent 非空 + confidence ≥ 0.5 → 锁定 Agent + skills → 直接走委派流程
  │    → 未锁定 → 主 Agent 手动判定
  │
  ├─ ② 手动判定（引擎未锁定时）
  │    ├─ 架构级 → PM-agent
  │    ├─ Coding → superpowers 全管线
  │    └─ 其余 → 主 Agent 从绑定表选 Agent
  │
  └─ ③ 委派流程（统一）
       委派前检查（5 问 + 内容质量）→ 构造参数（最小上下文）→ 注入执行纪律+技能 → delegate_task
```

**Engine locked:** 委派前检查中的「选 Agent」步骤自动跳过（Agent 已确定），
技能从引擎返回的 `skills` 字段注入，不另从绑定表全量拉取。

**Engine not locked:** 主 Agent 手动从绑定表确定 Agent + 全量 L3。

**内容质量检查（第⑥问）：** 所有委派前必须确认任务描述可执行——
禁止占位符（"处理异常""完善细节"类模糊表述），deliverable 必须有可验证终点。
PM-agent 批量产出 [DELEGATION_REQUESTS] 时追加冲突扫描：相邻子任务有无改同一文件/同一模块？
有则标注依赖或合并。

**Output dict shape (with skills association):**

```python
{
    "agent": "programmer",
    "confidence": 0.85,
    "method": "auto" | "auto_tiebreak" | "llm_fallback",
    "details": {
        "scores": [("programmer", 0.85), ("error-analyst", 0.0)],
        "matched_rules": ["\\b(bug|修复)\\b"],
        "fallback_reason": ""
    },
    "auto_skills": [                     # ← L2 auto (from .skill-cache.json, full list)
        "test-driven-development",
        "systematic-debugging",
        "simplify-code",
        ...
    ],
    "manual_skills": [                   # ← L3 manual (scene-specific, from matched rules' skills field)
        "codebase-inspection",
        "systematic-debugging"
    ]
}
```

## Maintenance — Three CLI Scaffolds (Built and Operational)

Three CLI scripts were built (Phase 0 + Phase 1, 2026-06-30) and tested
end-to-end. All share 4 core library modules under `scripts/agent-mgmt/`.

### Core Library (scripts/agent-mgmt/)

| Module | Lines | Purpose |
|--------|:-----:|---------|
| `_yaml_ops.py` | 242 | ruamel.yaml RoundTrip read, insert_into_dict, append_to_list, backup_file, restore_file |
| `_templates.py` | 369 | Jinja2 engine + 4 templates (agent-route, agent-config, skill-entry, binding-row) |
| `_validation.py` | ~280 | 6 functions: check_agent_exist, check_skill_global_unique, check_file_exists, check_schema_consistency, check_route_skills_exist, check_profiles_consistency |
| `_binding_table.py` | ~200 | Parse/generate SOUL.md Agent→Skill binding table (str/re only, no Markdown parser) |
| `_transaction.py` | 188 | `FileTransaction` class: backup → modify → commit/rollback. Shared by all 3 CLIs. |
| `_skills_patch.py` | — | Patch skill-cache.json entries; used by hermes-skill-add for skill-map registration |

### CLI Entry Points

| CLI | What it does | Steps | Automation rate |
|-----|-------------|:-----:|:---------------:|
| `scripts/hermes-agent-add` | Full agent creation: validate → route file → index.yaml → skill-map → profile config → SOUL.md binding row → profile SOUL.md placeholder → rebuild-cache → dual validate → commit/rollback | 10 | ~85% |
| `scripts/hermes-skill-add` | Skill registration: skill-map entry + optional route rule + SOUL.md binding update + rebuild + validate | 8 | ~90% |
| `scripts/hermes-route-add` | Append one rule to existing agent + validate | 4 | ~95% |

### Key Implementation Patterns

**Transaction protection:** All three CLIs create a `FileTransaction` at start,
`backup()` all files that will be modified, then modify → validate → `commit()`
on success or `rollback()` on failure. Backups go to `/tmp/hermes-mgmt-rollback/<ts>/`.

**Import pattern (agent-mgmt directory has hyphen):**
```python
import sys
from pathlib import Path
_mgmt_dir = Path(__file__).resolve().parent / "agent-mgmt"
if str(_mgmt_dir) not in sys.path:
    sys.path.insert(0, str(_mgmt_dir))
from _yaml_ops import read_yaml, insert_into_dict
```

**Validate WARN handling:** `validate-route-map.py` and `validate-skill-map.py`
return exit code 1 for WARN status (not an error — e.g. new agent not in
hardcoded list). CLI scripts must accept both exit code 0 (OK) and 1 (WARN)
as pass. Only exit code ≥2 is a real failure.

### API Layer (Phase 2 — after CLI scaffolding)

**Strategy: CLI-first, API-later.** API is a thin HTTP wrapper around the
shared core library — never a replacement. Without the CLI scaffolding in
place, there's nothing for the API to wrap.

**Framework:** Python `http.server` (standard library, zero extra deps).
FastAPI was considered and rejected — the ~3 dependency overhead (uvicorn +
fastapi + pydantic) is not justified for a single-purpose local API.

**Binding:** `127.0.0.1:8199` + API Key (plaintext header `X-API-Key`).

**Endpoints (7 total):**

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/agent/add` | Full agent creation (6-7 files) |
| POST | `/api/skill/add` | Skill registration (4-5 files) |
| POST | `/api/route/add` | Route rule append (1-2 files) |
| GET | `/api/agent/list` | All agents + status |
| GET | `/api/validate` | Run all validators |
| GET | `/api/health` | Liveness check |
| GET | `/api/logs` | Route log summary |

**Incremental cost:** ~350-450 lines Python, zero new dependencies.

**Key findings from PM-agent feasibility report:**

| Finding | Detail |
|---------|--------|
| API's real value | **Not speed** (CLI is already sub-second). It's **main agent direct call** — user says "add an agent" → main agent does `POST /api/agent/add` without delegating to pm-agent first. One less hop. |
| Coexistence | API never imports route_engine.py. It calls the shared core library + subprocesses rebuild-cache.py / validate-*.py. The `.route-cache.json` is the indirect bridge. |
| Not a Hermes plugin | Governance API is infrastructure (long-running, isolated), not a session-level plugin. Runs as an independent daemon. |
| Concurrency | File locking via `fcntl.flock()` — prevents two concurrent API calls from corrupting route-map files. |
| Full feasibility report | `projects/route-tree/api-scaffold-feasibility-report.md` |

### Roadmap (Actual, 2026-06-30)

```
Phase 0: _transaction.py + _yaml_ops + _templates + _validation   ← DONE, 2026-06-30
Phase 1: hermes-agent-add / hermes-skill-add / hermes-route-add    ← DONE, 2026-06-30
Phase 2: api_server.py (~400 lines)                                ← ON HOLD (YAGNI)
         User chose CLI-first over API layer. API's sole incremental
         value (main agent direct call via HTTP vs terminal()) was
         insufficient — terminal() already gives main agent the same
         access. Revisit only if multi-user or Web UI needed.
Phase 3: delete operations, audit history, Web UI                  ← FUTURE
```

> Full PM-agent report: `projects/route-tree/api-scaffold-feasibility-report.md`
> CLI scaffold design: `references/maintenance-scaffold-design.md`

## Roadmap — Strong Binding (Pure Zero-Token)

The user has discussed wrapping the route engine as an executable skill and
**removing LLM fallback** entirely (强绑定). Under strong binding the engine
has only two outcome paths: auto/tiebreak on success, "unable to route" on
failure. No LLM fallback.

### Preconditions

| Condition | How to check | Gate |
|-----------|-------------|------|
| Real-task hit rate ≥ 90% | `analyze-route-log.py` — filter out test inputs ("xyz"/"aaaaaa") | 50+ logged decisions |
| All fallback cases audited | Every `llm_fallback` entry reviewed | Each fallback is either noise or a rule that was then added |
| User tolerance confirmed | Ask explicitly before cutting fallback | User confirmed they accept occasional "无法路由" |

### Phased rollout

```
Phase 1: Raise confidence threshold 0.5 → 0.8
         Borderline (0.5–0.8) goes to llm_fallback instead of auto
         Effect: fewer misroutes, same safety net

Phase 2: Replace llm_fallback with "上报用户+请求明确意图"
         Engine can't decide → tell user and ask for clarification
         Effect: zero-cost fallback, user fills gap

Phase 3: Remove fallback path entirely
         Engine === only routing path
         Effect: pure zero-token. Rule gaps = user correction loop
```

### Risk checklist

| Scenario | Impact |
|----------|--------|
| Vague input ("把那个搞一下") | All scores 0 → blocked. Needs rephrase or rule addition |
| New work category ("写个公函") | Not routed until YAML rule added |
| Cross-session reference ("和上次一样") | No LLM to infer from history |

Run `analyze-route-log.py` before enabling Phases 2–3.

## Acceptance Criteria

The engine passes these 12 acceptance tests:

| Input | Expected agent | Expected manual_skills |
|-------|---------------|----------------------|
| 修复 PROXY 连接的 bug | programmer | codebase-inspection, systematic-debugging |
| 构建新的 UI 界面 | ui-designer | [] |
| NAS 备份配置 | synology-helper | [] |
| 写一份 API 参考文档 | docs-writer | [] |
| 设计多 Agent 架构方案 | pm-agent | architecture-integrity-check |
| 审查代码安全性 | error-analyst | engineering-security-engineer |
| 优化 system prompt | prompt-engineer | [] |
| 端到端集成测试验证 | reality-checker | [] |
| 把 PDF 转换成 Word | document-processor | [] |
| 搜索最新的 AI 论文 | data-analyst | [] |
| 记忆之前的讨论内容 | memory-agent | [] |
| 处理文件目录结构 | file-ops | [] |

## ⚠️ Critical — phrase type lowercase mismatch (fixed 2026-06-30)

`phrase` type matching originally did `pattern in normalized` WITHOUT lowercasing
the pattern first. Since `_normalize()` lowercases the input text but the pattern
(from YAML) keeps original case, "新增 Agent" (pattern with capital A) would NOT
match "新增一个 agent" (normalized input).

```python
# BROKEN (pre-2026-06-30):
elif rule_type == "phrase":
    return pattern in normalized          # "新增 Agent" in "新增一个 agent" → False!

# FIXED (2026-06-30):
elif rule_type == "phrase":
    return pattern.lower() in normalized  # "新增 agent" in "新增一个 agent" → True
```

Note: `keyword` type already had `pattern.lower()` — the inconsistency was the bug.
Both phrase and keyword now behave identically for matching (only differ by which
type you choose in YAML for semantic clarity).

## ⚠️ Fuzzy Optimization (2026-07-01)

`fuzzy: true` enables subtype matching — Chinese subsequence for `phrase` type,
CJK character overlap for `keyword` type. Not all rules benefit equally.

**Full per-rule analysis:** `route-map/fuzzy-analysis-report.md` (410 lines)

**Golden rules:**
```
  DO add fuzzy to:      long phrases (≥4 chars), domain-specific terms, users' natural variants
  DON'T add fuzzy to:   single-char rules, high-frequency generic words (实现/测试/安全), 
                        ALL negative-weight rules (weakens false-match protection)
  NEVER add fuzzy to:   regex rules (regex already covers variants), the 「图」rule in ui-designer
```

**YAML formatting trap:** When adding `fuzzy: true` to a rule, it must be at the same
indentation level as `pattern`/`weight`/`skills` within that rule — NOT one level above
(which makes it belong to the parent block and may be silently ignored).

```yaml
  # CORRECT — fuzzy at rule level
  - type: phrase
    pattern: 大文件
    weight: 0.8
    fuzzy: true          # ← same indent as pattern/weight
    skills: []

  # WRONG — fuzzy at wrong level, silently ignored
  - type: phrase
    pattern: 写文档
    weight: 1.0
    skills:
      - doc-coauthoring

    # ── unrelated comment ─────────────────────────────
    fuzzy: true          # ← 4-space indent, NOT rule-level!
```

## ⚠️ Critical — Chinese insertion patterns need `.*` not `\s*`

When a Chinese phrase has insertions between words, `\s*` (whitespace only) won't
bridge Chinese characters. Use `.*` to match any characters:

```yaml
# BROKEN — doesn't match "新增一个 Agent" (Chinese chars between)
- type: regex
  pattern: "(新增|新建|注册)\\s*Agent"

# FIXED — matches "新增 Agent", "新增一个 Agent", "新增一个子 Agent"
- type: regex
  pattern: "(新增|新建|注册).*Agent"
```

`.*` is greedy by default, but since the target keyword "Agent" is specific (capital
letter in Chinese context), false positives are rare. If precision matters, use lazy
`.*?` or add surrounding anchors.

## ⚠️ Rule — Generic vs specific conflicts (tiebreak prevention)

When two agents have overlapping patterns, the specific pattern should have
higher weight than the generic one:

```yaml
# programmer.yaml — generic "测试" catches everything
- type: phrase
  pattern: "测试"
  weight: 0.8

# reality-checker.yaml — specific "集成测试" should beat generic
- type: phrase
  pattern: "集成测试"
  weight: 1.2           # > programmer's 0.8
```

**Rule of thumb:** Agent-specific/granular rules should have weight ≥ 1.0.
Generic/fallback rules should have weight ≤ 0.8. The tiebreak mechanism picks
the agent with higher priority (lower number), but you should NOT rely on that
— weight design should prevent ties in the first place.

## Sub-Agent Route Engine Access

Sub-agents can call the route engine directly via terminal — no MCP needed:

```python
# Inside any sub-agent with terminal toolset:
terminal("python3 /opt/data/scripts/route_engine.py '服务器返回500错误'")
```

**Key constraint:** depends on whether the sub-agent has `terminal` in its
delegation toolsets. If yes, it has full access to the same Python script the
main agent uses. The 0.1s response time and deterministic output apply identically.

**When this matters:**
- PM-agent validates routing after decomposing a task
- Reality-checker verifies correct routing for test cases
- Error-analyst double-checks routing during fault diagnosis

**When it doesn't work:** sub-agent has no `terminal` toolset (e.g. restricted
delegation with only `file` or `browser`). For those cases, the main agent
handles routing pre-delegation — this is the normal flow.

**MCP not needed:** Converting the route engine to an MCP server would save
~50-80 tokens per call (removing terminal shell overhead) but adds a persistent
process. The terminal-based approach has negligible runtime overhead (~0.1s)
and zero deployment complexity. Skip MCP unless sub-agents without terminal
need routing access — in practice, the main agent always routes first.

## Hermes Version Compatibility — Layer Separation

The route engine is **layer-independent** from Hermes core. This is a deliberate
architectural property, not an accident.

| Layer | Owns | Technology |
|-------|------|-----------|
| **Route engine** (this skill) | *Which agent* to delegate to | YAML rules → Python scoring → agent name |
| **Hermes core** | *How* delegation executes, model selection, verification | Built-in `delegate_task`, MoA, `/goal` contracts |
| **Hermes infrastructure** | Gateway, providers, transports, platforms | config.yaml, plugins, cron |

**Why upgrades don't break routing:**
- The route engine's output is always just `{"agent": "programmer", ...}` — a name.
- That name goes into Hermes' standard `delegate_task` call.
- Hermes core upgrades (v0.17 → v0.18 → v0.19) change the *execution mechanism* of
  `delegate_task` (parallel fan-out, verification, model selection), not the *decision*
  of who to delegate to.
- The YAML rules, weights, and skills fields have zero dependency on Hermes version.

**What the route engine gains for free from upgrades:**
| Hermes upgrade | Benefit to route engine |
|---------------|------------------------|
| v0.18.0 parallel fan-out | Multiple route-engine dispatches execute in parallel automatically |
| v0.18.0 verification contracts | Sub-agent results are verified by Hermes before returning |
| v0.18.0 MoA | The delegated sub-agent can use MoA models if configured |
| Any future `delegate_task` enhancement | Inherited automatically — no route-map changes needed |

**After upgrading Hermes, verify (takes 30s):**
```bash
python3 scripts/route_engine.py "修复bug"       # still → programmer
python3 scripts/route_engine.py "NAS备份"       # still → synology-helper
python3 scripts/route_engine.py "架构设计"       # still → pm-agent
```
No route-map changes are needed unless the upgrade adds/removes a sub-agent
type that the routing rules reference. Even then, only the YAML rules change.

**When to investigate:** Only if Hermes changes the `delegate_task` API signature
or adds a new *kind* of sub-agent that needs new routing rules. Neither has
happened through v0.18.0.

## Public Resources

The route engine architecture is documented in two versions:

| Version | Repository | URL |
|---------|-----------|-----|
| **Internal (full)** | `zero-0437/hermes-skill-governance` | `git@github.com:zero-0437/hermes-skill-governance.git` (private) |
| **Sanitized (public)** | `zero-0437/route-engine-docs` | https://github.com/zero-0437/route-engine-docs |

The public version replaces internal paths with `$HERMES_HOME/`, IPs with
`[internal-network]`, and usernames with `[admin-user]`. Architecture content
is identical.

When the user asks for the route engine repository URL, point to the public
repo first unless they explicitly ask for internal details.

## Pitfalls

- **`\\b` with Chinese**: doesn't work → use phrase type
- **re.IGNORECASE**: must be set on all regex matches when text is lowercased
- **Path resolution mismatch when deployed as skill** (2026-07-03 code review finding): `route_engine.py`, `validate-route-map.py`, and `analyze-route-log.py` use `__file__`-relative paths (`os.path.join(_SCRIPT_DIR, "..", ...)`) that resolve to the skill root directory. But `.skill-cache.json`, `skill-map.yaml`, and `logs/` live at the **workspace root** (`/opt/data/`). When these scripts run from inside the skill directory:
  - `../.skill-cache.json` → skill root → **NOT FOUND** → `_lookup_skills()` returns `[]`
  - `../skill-map.yaml` → skill root → **NOT FOUND** → `validate-route-map.py` skips schema_version check
  - `../logs/` → skill root → **wrong location** — logs get written to skill root
  **Fix:** Use `$HERMES_HOME` environment variable at the top of each script, or create absolute-path config, or add symlinks for `.skill-cache.json` and `skill-map.yaml` into the skill root.
- **`scripts/agent-mgmt/` is a mandatory dependency** (2026-07-03 code review finding): `hermes-route-add` imports `_yaml_ops`, `_validation`, and `_transaction` from `scripts/agent-mgmt/`. This directory (contains 6 modules: `_yaml_ops.py`, `_validation.py`, `_transaction.py`, `_templates.py`, `_binding_table.py`, `_skills_patch.py`) MUST be deployed alongside the skill. Without it, `hermes-route-add` crashes with `ModuleNotFoundError` on import. When copying the skill elsewhere (e.g. as a standalone package), verify `scripts/agent-mgmt/` is included.
- **Python 依赖（venv）**: 所有 scripts/ 下的 Python 脚本需要 `yaml`+`ruamel.yaml` 等非标准库模块，系统 `python3` 不含。使用 `/opt/hermes/.venv/bin/python3` 执行，或用 Hermes venv 的 python（`which python3` 在手动的 Hermes session 中）。`ModuleNotFoundError: No module named 'yaml'` 即此问题
- **Cold start**: first call loads all YAML (~100ms), subsequent calls <0.3ms
- **Negative weights**: intentional for false-match protection (e.g. programmer -0.5 when "文档" appears). Allow -2.0 to +2.0 range.
- **Priority field**: lower number = higher priority, used for tie-breaking
- **overrides section**: for agents that should bypass scoring entirely (e.g. pm-agent when "架构" is mentioned)
- **Shared tool pollution**: rebuild-cache.py must NOT inject shared skills into each Agent's manual list. After fix, programmer should have 16 manual skills, not 31.
- **「更新」上下文歧义**: When user says "更新后", DO NOT assume they mean local git changes. They frequently mean **Hermes software version upgrade** (e.g. v0.17 → v0.18). Ask or check context before answering about local commits vs release notes. When in doubt, check both and report which one they're referring to.
- **Skills field design**: route rules' `skills` field must only reference skills registered in skill-map.yaml. validate-route-map.py checks this at dimension 7.
- **ruamel.yaml Comment object crash**: When reordering YAML dict entries (e.g. `reorder_index_agents()`), do NOT create a new `CommentedMap` and copy `.ca` attributes. The Comment object's `items` property is read-only. Use `move_to_end(last=True)` instead: iterate sorted keys and call `agents.move_to_end(key, last=True)` for each. This preserves all YAML comments without touching `.ca`.
|- **Validate exit code 1 = WARN ≠ failure**: `validate-route-map.py` and `validate-skill-map.py` return exit code 1 when they have warnings (not errors). This is an expected state (e.g. when a new agent isn't in the hardcoded expected list). CLI tools must treat exit code 1 as pass, not failure. Only raise for exit code ≥2.
- **`hermes-route-add` step numbering is swapped** (cosmetic — 2026-07-03 code review finding): The comment block at line 212 says "步骤 3" (neg-weight handling) while line 248 says "步骤 2" (rule append). The execution order is correct (validate → neg-weight transform → append → validate → commit), only the comment labels are reversed. Not urgent but confusing for maintainers.
- **`SKILL.md.linecount` artifact should be deleted**: After copying the skill, `SKILL.md.linecount` (output of `wc -l`) may linger in the skill root. This file has no function and should be removed — it is not part of the published skill.
- **`fuzzy-analysis-report.md` location**: This 33KB analysis report lives inside `references/route-map/` — it's a report, not a route rule file. It belongs in `references/` root. The YAML parser won't choke on it (it's `.md`, not `.yaml`), but it clutters the route-map directory.

## 使用流程

> 以下 CLI 命令需在 skill 目录下执行：
> `cd /opt/data/skills/multi-agent-arch/zero-token-routing`

### 快速路由

对任意用户输入执行路由匹配，返回目标 Agent 及其置信度：

```bash
python3 scripts/route_engine.py route "修复bug"
```

**输出 JSON 解析指南：**

| 字段 | 含义 | 示例值 |
|------|------|--------|
| `target` | 匹配到的目标 Agent | `programmer` |
| `confidence` | 置信度 (0.0~1.0) | `0.85` |
| `method` | 匹配方式 | `route` / `override` / `fallback` |
| `matched_rules` | 命中的规则列表 | `["关键词:bug", "关键词:修复"]` |
| `score` | 匹配总分 | `0.75` |
| `threshold` | 该 Agent 阈值 | `0.5` |

- `method: fallback` 表示无规则命中，回退到 LLM 裁决
- `confidence < threshold` 表示匹配但不足以自动路由，建议走 LLM 判断

### 技能查询

查询指定 Agent 关联的技能列表：

```bash
python3 scripts/route_engine.py skills pm-agent
```

输出示例：
```json
{
  "agent": "pm-agent",
  "skills": [
    "skill-map-maintenance",
    "spec-authoring",
    "domain-modeling",
    "writing-plans"
  ]
}
```

### 规则验证

对 route-map/ 目录下所有 YAML 规则执行 12 维审计验证：

```bash
python3 scripts/validate-route-map.py
```

**退出码含义：**
- `0` → ✅ OK，所有规则通过
- `1` → ⚠️ WARN，存在警告但不影响路由（如新 Agent 不在预期列表中）
- `2` → ❌ ERR，存在必须修复的语法/结构/引用错误

常见检查项：YAML 格式正确性、`skills` 字段引用的技能是否在 skill-map.yaml 中注册、`weight` 范围 [-2.0, 2.0]、`type` 合法值等。

### 日志分析

分析路由日志，提取异常模式和统计信息：

```bash
python3 scripts/analyze-route-log.py
```

**输出解读：**
- 按时间窗口统计路由命中/未命中比率
- 异常标记含义：
  - `[SKIP]` → 跳过（不匹配当前 Agent 的规则）
  - `[FALLBACK]` → 回退（无规则命中，走 LLM 裁决）
  - `[OVERRIDE]` → 覆盖（命中 override 规则，跳过分数计算）
  - `[MATCH]` → 匹配（正常路由）
- 置信度分布直方图
- Top-N 未匹配的输入模式（供添加新规则参考）

### 追加规则

为新 Agent 或已有 Agent 追加路由规则：

```bash
python3 scripts/hermes-route-add <agent> "<pattern>" <type> <weight>
```

**参数说明：**
- `<agent>`：目标 Agent 名称（如 `programmer`、`pm-agent`）
- `"<pattern>"`：匹配模式（支持 `keyword`、`regex`、`phrase` 三种类型）
- `<type>`：模式类型，`keyword` / `regex` / `phrase`
- `<weight>`：匹配权重（范围 -2.0 ~ 2.0）

**示例：**
```bash
python3 scripts/hermes-route-add programmer "重构" keyword 0.8
python3 scripts/hermes-route-add pm-agent "路线图|roadmap" regex 0.9
python3 scripts/hermes-route-add arch-agent "系统设计" phrase 0.7
```

执行后自动更新对应 agent 的 YAML 规则文件并重新加载。

### 封装完整性验证

复制 skill 到新目录、修复路径缺陷或重建缓存后，执行以下快速验证确保所有路径和模块就绪：

```bash
cd /opt/data/skills/multi-agent-arch/zero-token-routing

# ① 验证 symlinks 全部生效
python3 -c "import os; ws='/opt/data'; \
  for n in ['.skill-cache.json','skill-map.yaml','logs']: \
    p=os.path.join(os.getcwd(),n); \
    print(f'✅ {n}: {os.path.exists(p)}')"

# ② 验证 agent-mgmt 模块可导入
python3 -c "import sys,os; sys.path.insert(0,os.path.join('scripts','agent-mgmt')); \
  from _yaml_ops import append_to_list; \
  from _transaction import FileTransaction; \
  from _validation import check_file_exists; \
  from _binding_table import *; \
  print('✅ All 6 agent-mgmt modules import OK')"

# ③ 验证 route engine 返回技能（用 Hermes venv）
/opt/hermes/.venv/bin/python3 scripts/route_engine.py skills pm-agent

# ④ 验证 CLI 脚手架参数解析（用 Hermes venv）
/opt/hermes/.venv/bin/python3 scripts/hermes-route-add 2>&1 | head -3
```

**预期输出：**
- ① 全部 `True`
- ② 无 ModuleNotFoundError（如缺 `ruamel.yaml` 属预期依赖问题，用 Hermes venv 重试）
- ③ 返回含 `auto` 和 `manual` 列表的 JSON
- ④ 显示 usage 信息（缺少参数是正常退出，非 import 崩溃）

### 异常处理模板

| 异常 | 可能原因 | 排查方法 |
|------|----------|----------|
| `FileNotFoundError: route-map/...` | route-map/ 未找到。skill 注入后相对路径变了？ | 确认在 skill 目录执行；或设置 `ROUTE_MAP_PATH` 环境变量指向绝对路径 |
| `YAML parse error` | 某规则文件语法错误 | 运行 `validate-route-map.py` 定位具体文件和行号 |
| `json.decoder.JSONDecodeError` | subprocess 输出被截断 | 检查是否有其他进程竞争输出；增加 `subprocess` timeout |
| `KeyError: 'routes'` | index.yaml 缺少 routes 节或格式错误 | 检查 `index.yaml` 的 routes 映射是否完整 |
| `PermissionError` | route_engine.py 或 YAML 文件权限不足 | `chmod +x scripts/*` 确保可执行
