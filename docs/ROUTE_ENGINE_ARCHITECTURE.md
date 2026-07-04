# 路由引擎（Route Engine）体系架构文档

> **最后更新**: 2026-07-03 | **Schema 版本**: v2.5 | **引擎文件**: `/opt/data/scripts/route_engine.py`（650 行）

---

## 📑 目录

- [1. 概述](#1-概述)
- [2. 系统架构](#2-系统架构)
- [3. 核心引擎](#3-核心引擎)
- [4. Route Map 体系](#4-route-map-体系)
- [5. 任务链（Chains）](#5-任务链chains)
- [6. 支持工具](#6-支持工具)
- [7. 更新历史](#7-更新历史)
- [8. 配置与调优](#8-配置与调优)
- [9. GitHub 仓库与 SSH 配置](#9-github-仓库与-ssh-配置)

---

## 1. 概述

路由引擎（Route Engine）是 Hermes Agent 系统的**无 LLM 路由决策层**——所有用户输入在进入 LLM 之前，先经过路由引擎匹配规则，自动分配到最合适的 Agent。

### 1.1 设计原则

| 原则 | 说明 |
|------|------|
| **零 LLM 路由** | 全部路由决策基于纯 Python 规则匹配，不调用任何 LLM API。路由过程零延迟、零成本 |
| **可审计** | 每一条路由决策记录在 `/opt/data/logs/route-engine.jsonl`，含匹配规则、评分、置信度、决策方法 |
| **可调试** | 12 维验证器（`validate-route-map.py`）确保 route-map 结构完整；`analyze-route-log.py` 分析路由日志输出改进建议 |
| **分层匹配** | override → chain_keyword → evaluate+decide 三层，精度与效率兼备 |
| **fuzzy 扩展** | 对 phrase 和 keyword 类型支持中文子序列匹配和汉字重叠率匹配，提升用户变体覆盖 |

### 1.2 核心数据流

```
用户输入
    │
    ▼
route(user_input)  ── 主入口
    │
    ├─ 1. override 检查 ── 命中 → 直接委派，跳过评分
    │
    ├─ 2. chain_keyword 检查 ── 命中 → 直接匹配链，跳过 evaluate
    │
    ├─ 3. evaluate → 对所有 Agent 评分
    │       ├─ 精确匹配（regex / phrase / keyword）
    │       ├─ fuzzy 扩展匹配（phrase 子序列 / keyword 重叠率）
    │       └─ 技能反向索引加分（0.2/技能）
    │
    ├─ 4. decide → 权重决策
    │       ├─ 最高分 < min_confidence(0.5) → fallback
    │       ├─ 平局 → priority 裁决
    │       └─ 正常 → top Agent
    │
    └─ 5. log_route → 写入 JSONL 日志（自动轮转 10MB）
```

---

## 2. 系统架构

### 2.1 整体组件关系

```
┌─────────────────────────────────────────────────────────────┐
│                     Hermes Agent 系统                         │
│                                                             │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────────┐  │
│  │ route_engine │──▶│ route-map/   │──▶│ .route-cache   │  │
│  │     .py      │   │ index.yaml   │   │   .json        │  │
│  │   (650行)    │   │ routes/*.yaml│   │ (编译缓存)     │  │
│  │              │   │ chains/*.yaml│   └────────────────┘  │
│  │              │   │ shared.yaml  │                        │
│  │              │   └──────┬───────┘                        │
│  │              │          │                                │
│  │              │   ┌──────▼───────┐   ┌────────────────┐  │
│  │              │   │ .skill-cache│   │ agent-env      │  │
│  │              │   │   .json     │   │ (技能定义)     │  │
│  │              │   └─────────────┘   └────────────────┘  │
│  └──────┬───────┘                                         │
│         │                                                  │
│         ▼                                                  │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────────┐  │
│  │ validate-    │   │ hermes-route │   │ analyze-route  │  │
│  │route-map.py  │   │    -add      │   │   -log.py      │  │
│  │ (12维审计)   │   │ (事务追加)   │   │ (日志分析)     │  │
│  └──────────────┘   └──────────────┘   └────────────────┘  │
│                                                             │
│  ┌──────────────┐                                           │
│  │ chain_executor (外部编排器)                               │
│  └──────────────┘                                           │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 目录结构

```
/opt/data/
├── scripts/
│   ├── route_engine.py              # 核心引擎（650 行）
│   ├── validate-route-map.py        # 12 维 route-map 验证器（187 行）
│   ├── hermes-route-add             # CLI 事务追加规则（309 行）
│   ├── analyze-route-log.py         # 路由日志分析工具（139 行）
│   └── agent-mgmt/                  # 辅助模块（事务/YAML/校验）
│       ├── _yaml_ops.py
│       ├── _validation.py
│       └── _transaction.py
│
├── route-map/                       # Route Map 规则目录
│   ├── index.yaml                   # 主入口：12 个 Agent 定义 + overrides + defaults
│   ├── shared.yaml                  # 跨 Agent 公共规则（预留）
│   ├── fuzzy-analysis-report.md     # fuzzy 优化分析报告（410 行）
│   ├── routes/                      # 12 个 Agent 路由规则
│   │   ├── programmer.yaml         (211 行)
│   │   ├── error-analyst.yaml      (147 行)
│   │   ├── memory-agent.yaml       (128 行)
│   │   ├── reality-checker.yaml    (129 行)
│   │   ├── docs-writer.yaml        (117 行)
│   │   ├── spec-agent.yaml         (103 行)
│   │   ├── data-analyst.yaml       (99 行)
│   │   ├── file-ops.yaml           (99 行)
│   │   ├── document-processor.yaml (90 行)
│   │   ├── synology-helper.yaml    (73 行)
│   │   ├── prompt-engineer.yaml    (60 行)
│   │   ├── ui-designer.yaml        (148 行)
│   │   └── dual-review.yaml        (13 行)
│   └── chains/                      # 5 个任务链定义
│       ├── programmer-chain.yaml
│       ├── spec-agent-chain.yaml
│       ├── debugger-chain.yaml
│       ├── dual-review-chain.yaml
│       └── follow-process-chain.yaml
│
├── logs/
│   └── route-engine.jsonl           # 路由日志（JSONL，自动轮转 10MB，保留 5 份）
│
├── .route-cache.json                # 编译后的路由规则缓存（359 行，schema v2.5）
├── .skill-cache.json                # 技能缓存
│
├── home/
│   └── .ssh/                        # SSH 配置
│       ├── config
│       ├── id_ed25519
│       ├── id_ed25519.pub
│       └── known_hosts
│
└── backups/                         # 路由引擎备份（见第7章）
    ├── route-engine-20260702-083738/
    ├── route-engine-20260702-083745/
    └── route-engine-fix-20260702-102015/
```

---

## 3. 核心引擎

### 3.1 route_engine.py 工作流程

引擎主入口为 `route(user_input)` 函数（第 435 行），返回一个包含 `agent`、`confidence`、`method`、`chain`、`skills` 的字典。

```
route(user_input):
  │
  ├── load_route_map()
  │   ├── 读取 index.yaml
  │   ├── 遍历 agents，加载 routes/*.yaml
  │   ├── 解析 chain_ref，加载 chains/*.yaml
  │   ├── 构建 chain_keywords 反向索引
  │   └── 扫描 chains/ 目录补全未引用 chain 的 keywords
  │
  ├── _normalize(text) → 转小写
  │
  ├── [Phase 1] override 检查
  │   ├── 遍历 index.yaml 的 overrides 列表
  │   ├── 命中任意规则 → 直接返回，跳过评分
  │   └── override 规则也支持 skills 分配
  │
  ├── [Phase 2] chain_keyword 检查
  │   ├── 遍历 chain_kw_index（chain 头部定义的 keywords）
  │   ├── 精确短语匹配 → 返回 chain 对应 owner + steps
  │   └── 不命中 → 继续 Phase 3
  │
  ├── [Phase 3] evaluate
  │   ├── 遍历所有 Agent 的所有规则
  │   ├── match_rule(normalized, rule) 精确/模糊匹配
  │   └── 返回 [(agent, score, matched_rules)] 降序
  │
  ├── [Step 3.5] 技能反向索引加分
  │   ├── _build_skill_owners() → 技能→Agent 映射
  │   ├── _score_skill_matches() → 每命中技能 +0.2
  │   └── 叠加到 evaluate 结果中
  │
  ├── [Phase 4] decide
  │   ├── 空评分 → fallback (pm-agent)
  │   ├── top_score < 0.5 → fallback
  │   ├── 平局 → priority 裁决（数值小优先）
  │   └── 正常 → top Agent
  │
  └── [Phase 5] 日志记录
      ├── log_route(result, input)
      ├── JSON Lines 格式，自动轮转 10MB
      └── flagged 标记（fallback/tiebreak/borderline）
```

### 3.2 三阶段决策详解

#### Phase 1: Override（直接委派）

定义在 `index.yaml` 的 `overrides` 段。当前有 2 条 override 规则，全部委派给 `pm-agent`：

```yaml
overrides:
- agent: pm-agent
  rules:
  - pattern: 架构
    skills: [architecture-integrity-check]
    type: keyword
    fuzzy: true
  - pattern: \\b(agent.*冲突|拓扑)\\b
    skills: [architecture-integrity-check]
    type: regex
```

Override 命中时返回 `confidence: 1.0`、`method: "auto"`，**跳过后续所有评估**。

#### Phase 2: Chain Keyword（关键词匹配链）

定义在各 chain YAML 文件头部的 `chain_keywords` 列表。例如 `programmer-chain` 定义 `chain_keywords: [编码管线, p-chain, parallel-review, 双轴审查, 开发管线]`。

- 使用 `phrase` 类型精确匹配（无 fuzzy）
- 命中后按 keyword 长度降序（最精确优先），再按 owner priority 升序
- 直接返回 chain 的全部 steps，跳过 evaluate

#### Phase 3: Evaluate + Decide（评分决策）

`evaluate()` 函数遍历所有 Agent 的所有规则，累加命中规则的 `weight`。核心逻辑：

```python
def evaluate(text, route_map):
    for name, data in agents.items():
        score = 0.0
        for rule in data["rules"]:
            if match_rule(normalized, rule):
                score += rule["weight"]
        if score < 0:
            score = 0.0  # 负权重只降低自身，不扩展为负值
        results.append((name, score, matched))
    results.sort(key=lambda x: x[1], reverse=True)
    return results
```

`decide()` 根据评分做最终路由：

| 条件 | 路由结果 | method |
|------|---------|--------|
| 无评分 | fallback_agent（pm-agent） | `llm_fallback` |
| top_score < 0.5 | fallback_agent | `llm_fallback` |
| 平局 | priority 裁决（数值小胜） | `auto_tiebreak` |
| 正常 | top Agent | `auto` |

### 3.3 匹配类型与 Fuzzy 算法

#### 三种匹配类型

| 类型 | 精确匹配 | fuzzy 匹配 |
|------|---------|-----------|
| `regex` | `re.search(pattern, text, IGNORECASE)` | 静默忽略（fuzzy 对 regex 无意义） |
| `phrase` | `pattern.lower() in normalized` | **中文子序列匹配** |
| `keyword` | `pattern.lower() in normalized` | **汉字重叠率 ≥ 0.6** |

#### Fuzzy Phrase：中文子序列匹配

`match_fuzzy_phrase()`（第 266 行）：

1. **中文部分**：提取 pattern 和 input 中的 CJK 字符（`[\u4e00-\u9fff]`），检查 pattern 的 CJK 字符是否**按顺序**出现在 input 的 CJK 字符序列中
2. **英文部分**：pattern 中的英文单词（`[a-z][a-z0-9_]*`）必须在 input 中**精确出现**（集合包含）

示例：
- pattern `"写一个函数"` → CJK 字符 `[写, 一, 个, 函, 数]`
- input `"写一个函数吧"` → CJK `[写, 一, 个, 函, 数, 吧]` → 子序列匹配 ✅
- input `"写一个函授数学"` → CJK `[写, 一, 个, 函, 授, 数, 学]` → 子序列匹配 ✅（按序）
- input `"写个函数"` → CJK `[写, 个, 函, 数]` → 缺"一" → 不匹配 ❌

**中英文混合**：
- pattern `"修复这个 bug"` → CJK `[修, 复, 这, 个]` + 英文 `{bug}`
- input `"修复一下这个 bug"` → CJK `[修, 复, 一, 下, 这, 个]` → 子序列匹配 + `bug` 在英文集合中 ✅

#### Fuzzy Keyword：汉字重叠率匹配

`match_fuzzy_keyword()`（第 287 行）：

1. **纯英文 keyword**：fallback 到 `in` 精确匹配
2. **中英文混合**：计算 pattern 汉字集合在 input 汉字集合中的覆盖率

```
重叠率 = |pattern汉字 ∩ input汉字| / |pattern汉字|
阈值：≥ 0.6 为匹配
```

示例：
- pattern `"架构"` → 汉字集合 `{架, 构}`
- input `"构架"` → 汉字集合 `{构, 架}` → 重叠率 = 2/2 = 1.0 ✅
- input `"框架"` → 汉字集合 `{框, 架}` → 重叠率 = 1/2 = 0.5 ❌（< 0.6）

### 3.4 负权重与误匹配防护

负权重实现"否定路由"语义：

- 规则 `weight` 为负数时，命中该规则降低该 Agent 总分
- 总分低于 0 时**钳位到 0.0**，不会变为负数影响其他 Agent
- 典型应用：programmer 用 `设计: -0.5`、`文档: -0.5`、`备份: -0.5` 来防止误抢 ui-designer/docs-writer/synology-helper 的场景
- **原则**：负权重规则**不加 fuzzy**，避免扩大防护范围导致误屏蔽

### 3.5 技能反向索引

`_build_skill_owners()` → `_score_skill_matches()` 实现**隐式技能路由**：

1. 从 `.skill-cache.json` 构建 `{skill_name: [agent1, agent2, ...]}` 反向索引
2. 用户输入中命中技能名 → 该技能的所有 owner Agent 各加 0.2
3. 短英文技能名（< 5 字符，全 ASCII）使用 `\b` 单词边界匹配，避免 `plan` 匹配 `explanation` 等误触发
4. 含连字符、CJK 或长度 ≥ 5 的技能名使用子串包含匹配

### 3.6 模块级缓存

```python
_route_map_cache: dict | None = None
_skill_cache: dict | None = None
```

- `load_route_map()` 首次调用加载并缓存，后续直接返回缓存
- `_load_skill_cache()` 技能缓存同
- `_clear_cache()` 安全清空方法

### 3.7 自动日志轮转

```python
_LOG_FILE = "/opt/data/logs/route-engine.jsonl"
_LOG_MAX_BYTES = 10 * 1024 * 1024   # 10 MB
_LOG_BACKUP_COUNT = 5
```

每当日志文件超过 10MB，自动轮转：`.1` → `.2` → ... → `.5`（删除最旧），最后 `.1` 为最新备份。每次路由调用记录以下字段：

```json
{
  "ts": "2026-07-03T12:00:00+08:00",
  "input": "用户输入（前200字）",
  "agent": "programmer",
  "confidence": 1.0,
  "method": "auto",
  "matched": ["实现新功能", "写一个函数"],
  "flagged": false,
  "flag_reason": null
}
```

当 `method` 为 `llm_fallback`、`auto_tiebreak` 或 `auto` 且 `confidence < 0.6` 时，`flagged = true`。

---

## 4. Route Map 体系

### 4.1 index.yaml 主入口

**路径**: `/opt/data/route-map/index.yaml`（92 行）

当前配置：

```yaml
schema_version: '2.5'
maintainer: pm-agent
last_updated: '2026-07-03T00:00:00Z'
defaults:
  fallback_agent: pm-agent
  method: threshold
  min_confidence: 0.5
overrides:
  - agent: pm-agent
    rules:
      - pattern: 架构
        skills: [architecture-integrity-check]
        type: keyword
        fuzzy: true
      - pattern: \b(agent.*冲突|拓扑)\b
        skills: [architecture-integrity-check]
        type: regex
agents:
  # 12 个 Agent 定义（详见下节）
```

#### 12 个 Agent 定义

| Agent | Priority | chain_ref | 条件 |
|-------|----------|-----------|------|
| `dual-review` | 0 | `dual-review-chain` | 双评审 — 两步评审链 |
| `spec-agent` | 1 | `spec-agent-chain` | 新项目/新功能强制入口 |
| `programmer` | 2 | `programmer-chain` | 编码类任务 |
| `error-analyst` | 3 | `debugger-chain` | 故障诊断/安全审查 |
| `pm-agent` | 3 | — | 纯协调类（多Agent编排） |
| `data-analyst` | 4 | — | 数据分析/搜索查询 |
| `ui-designer` | 5 | — | UI/UX 设计/视觉图表 |
| `document-processor` | 6 | — | 文档格式转换/OCR |
| `file-ops` | 7 | — | 文件操作/SSH传输 |
| `synology-helper` | 8 | — | NAS 操作/备份 |
| `memory-agent` | 9 | — | 记忆管理/知识库 |
| `prompt-engineer` | 10 | — | Prompt 设计/优化 |
| `reality-checker` | 11 | — | 集成测试/端到端验证 |
| `docs-writer` | 12 | — | 技术文档/API 参考 |

**priority 含义**：数值越低优先级越高。平局裁决时使用。

### 4.2 routes/ 目录规则文件

共 13 个规则文件（含 `dual-review.yaml`），每个文件包含该 Agent 的匹配规则列表。

#### 规则结构

```yaml
rules:
  - type: phrase          # 匹配类型：phrase | keyword | regex
    pattern: 写一个函数     # 匹配模式
    weight: 1.0           # 权重（-2.0 ~ 2.0）
    skills: [spike]       # 关联的 L3 manual 技能
    fuzzy: true           # 是否启用模糊匹配
    chain_ref: programmer-chain  # 关联的任务链（可选）
    description: 描述       # 规则说明（可选）
```

#### 各 Agent 规则概览

| Agent | 规则数 | 正权重 | 负权重 | fuzzy 条数 |
|-------|--------|--------|--------|-----------|
| programmer | ~46 | ~38 | ~8 | 5 |
| error-analyst | ~30 | ~24 | ~6 | 10 |
| memory-agent | ~22 | ~22 | 0 | ~18 |
| reality-checker | ~25 | ~25 | 0 | ~12 |
| docs-writer | ~22 | ~18 | ~4 | ~7 |
| spec-agent | ~18 | ~10 | ~8 | 2 |
| data-analyst | ~13 | ~13 | 0 | ~12 |
| file-ops | ~16 | ~14 | ~2 | ~8 |
| document-processor | ~15 | ~15 | 0 | ~8 |
| synology-helper | ~10 | ~10 | 0 | ~6 |
| prompt-engineer | ~10 | ~10 | 0 | ~6 |
| ui-designer | ~23 | ~23 | 0 | ~5 |
| dual-review | 1 | 1 | 0 | 0 |

### 4.3 chains/ 目录

详见 [第 5 章](#5-任务链chains)。

### 4.4 shared.yaml

**路径**: `/opt/data/route-map/shared.yaml` — 当前为空（预留），未来可用于跨 Agent 公共规则。

```yaml
shared_rules: []
```

### 4.5 .route-cache.json

**路径**: `/opt/data/.route-cache.json`（359 行）

编译后的路由规则缓存，加速二次加载。包含：

- `schema_version`: '2.5'
- `agents`: {agent_name: {file, mtime, compiled_rules}}
- 每条 compiled_rule 包含 type、pattern、weight、is_valid

### 4.6 负权重设计模式

负权重规则是 Route Engine 的关键设计模式，用于防止模糊匹配导致的错误路由。典型场景：

```
programmer 负权重:
  - "设计" → -0.5  (防止误抢 ui-designer)
  - "文档" → -0.5  (防止误抢 docs-writer)
  - "备份" → -0.5  (防止误抢 synology-helper)
  - "记忆" → -0.5  (防止误抢 memory-agent)
  - "NAS|Prompt" → -0.5 (regex, 防误抢)

error-analyst 负权重:
  - "修复" → -0.3  (防止误抢 programmer)
  - "修改" → -0.3
  - "写" → -0.3
  - "实现" → -0.3

spec-agent 负权重:
  - "改" → -0.5   (防止非新建场景走 spec)
  - "修" → -0.5
  - "删" → -0.5
  - "失败|错误|出错" → -1.0 (regex, 防编译错误截胡)
```

---

## 5. 任务链（Chains）

任务链（Chain）是多 Agent 协同编排的工作流，由路由引擎命中后触发，由外部 `chain_executor` 执行。

### 5.1 链数据结构

每个 chain YAML 文件结构：

```yaml
chain_name: programmer-chain
chain_keywords: [编码管线, p-chain, ...]   # 触发关键词（Phase 2 使用）
owner: programmer                          # 所属 Agent
description: "..."                         # 描述
report_only: false                         # true=仅输出报告不修改
steps:
  - agent: programmer
    goal: 步骤目标
    keywords: [step 关键词]
    type: interactive                       # 可选：需要用户交互
    batch: true                             # 可选：批量模式
  - type: parallel                          # 并行步骤
    branches:
      - agent: error-analyst
        goal: 分支目标
      - agent: programmer
        goal: 分支目标
    join_strategy: separate                 # 策略：separate=独立输出
chain_step_skills:                         # 每步关联的 skills
  agent@step_index: [skill1, skill2]
```

### 5.2 5 个链定义

#### ① programmer-chain — 编码管线

**文件**: `/opt/data/route-map/chains/programmer-chain.yaml`
**关键词**: `编码管线`, `p-chain`, `parallel-review`, `双轴审查`, `开发管线`

| Step | Agent | Goal | Skills |
|------|-------|------|--------|
| 0 | programmer | TDD 实现 + self-review | test-driven-development |
| 1 | error-analyst | spec 合规评审 | requesting-code-review |
| 2 | programmer | 代码质量评审 | requesting-code-review, receiving-code-review |
| 3 | **parallel** | **并行审查** | — |
| 3a | error-analyst | Standards 审查：代码规范和坏味道 | — |
| 3b | programmer | Spec 审查：实现是否匹配 spec/PRD | — |
| 4 | reality-checker (interactive) | 验证门控：运行测试+curl+断言 | verification-before-completion |
| 5 | programmer | 收尾：commit→PR | finishing-a-development-branch |

#### ② spec-agent-chain — 新项目管线

**文件**: `/opt/data/route-map/chains/spec-agent-chain.yaml`
**关键词**: `新项目管线`, `spec-chain`, `prd管线`, `需求分析管线`

| Step | Agent | Goal | Skills |
|------|-------|------|--------|
| 0 | spec-agent | 需求分析，产出设计文档 | brainstorming, architecture-integrity-check |
| 1 | pm-agent | 制定 2-5 分钟粒度执行计划 | writing-plans |
| 2 | pm-agent | 拆解实现任务为垂直切片 | architecture-integrity-check |
| 3 | programmer (batch) | 按拆解任务逐个实现 | — |
| 4 | **parallel** | **并行审查** | — |
| 4a | error-analyst | Standards 审查 | — |
| 4b | programmer | Spec 审查 | — |
| 5 | reality-checker (interactive) | 验证门控 | verification-before-completion |
| 6 | programmer | 收尾 | finishing-a-development-branch |

#### ③ debugger-chain — Bug 诊断管线

**文件**: `/opt/data/route-map/chains/debugger-chain.yaml`
**关键词**: `调试管线`, `bug诊断`, `debug-chain`, `排错`, `diagnosing-bugs`, `诊断bug`

| Phase | Agent | Goal | Skills |
|-------|-------|------|--------|
| 1 | error-analyst (interactive) | 建立反馈环：可运行复现测试 | systematic-debugging |
| 2 | programmer | 最小化复现用例 | — |
| 3 | error-analyst (interactive) | 提出 3-5 个可证伪根因假设 | systematic-debugging |
| 4 | programmer | 注入 DEBUG 日志，定位根因 | — |
| 5 | programmer | 修复 + 回归测试 | test-driven-development |
| 6 | programmer | 清理 + 后验 | — |

#### ④ dual-review-chain — 双评审管线

**文件**: `/opt/data/route-map/chains/dual-review-chain.yaml`
**关键词**: `双评审`, `d-review`, `合规检查`
**`report_only: true`** — 仅输出评审报告，不执行修改

| Step | Agent | Goal | Skills |
|------|-------|------|--------|
| 0 | error-analyst | spec 合规评审 | requesting-code-review |
| 1 | programmer | 代码质量评审 | requesting-code-review |

#### ⑤ follow-process-chain — 标准流程管线

**文件**: `/opt/data/route-map/chains/follow-process-chain.yaml`
**关键词**: `按流程走`, `标准流程`, `standard-flow`, `全流程管线`

| Step | Agent | Goal | Skills |
|------|-------|------|--------|
| 0 | pm-agent | 任务拆解为垂直切片 | writing-plans |
| 1 | programmer (batch) | 按拆解结果实现代码 | test-driven-development |
| 2 | error-analyst | spec 合规评审 | requesting-code-review |
| 3 | programmer | 代码质量评审 | requesting-code-review, receiving-code-review |

---

## 6. 支持工具

### 6.1 validate-route-map.py — 12 维审计器

**路径**: `/opt/data/scripts/validate-route-map.py`（187 行）
**退出码**: 0=OK, 1=WARN, 2=ERR

审计维度：

| # | 维度 | 检查内容 |
|---|------|---------|
| 1 | YAML 合法性 | index.yaml 及所有 routes/*.yaml 是否为有效 YAML |
| 2 | routes YAML 合法性 | 每个 route 文件是否为有效 dict |
| 3 | agents 完整性 | 12 个预期 Agent 全部在 index.yaml 中定义 |
| 4 | 文件交叉验证 | index.yaml 引用的 file 路径是否实际存在 |
| 5 | 逆向覆盖检查 | routes/ 下每个 .yaml 是否在 index.yaml 有映射 |
| 6 | schema_version 一致性 | index.yaml 与 skill-map.yaml 的版本一致 |
| 7 | rules[] 结构完整性 | 每条规则必须有 type、pattern、weight |
| 8 | regex 语法 | 所有 regex 规则通过 `re.compile()` |
| 9 | 最少正权重规则 | 每个 Agent 至少 2 条正权重规则 |
| 10 | weight 范围 | 所有权重在 -2.0~2.0 之间 |
| 11 | agent 名一致性 | 文件名与内部 agent 字段一致 |
| 12 | 重复规则检测 | 同文件内 type+pattern 组合不重复 |

### 6.2 hermes-route-add — 事务保护追加规则

**路径**: `/opt/data/scripts/hermes-route-add`（309 行）
**CLI 用法**:

```bash
./scripts/hermes-route-add --agent <name> --type <keyword|phrase|regex> \
    --pattern <pattern> --weight <float> [--skills <skills>] [--neg-weight]
```

**事务保护流程**:

```
1. 校验 agent 存在性、weight 钳位、regex 语法、skill 存在性
2. backup() → 备份原文件
3. append_to_list() → 追加规则到 routes/{agent}.yaml
4. run validate-route-map.py → 验证一致性
5. 通过 → commit() | 失败 → rollback()
```

**校验项**:
- agent 名称合法（`^[a-z0-9_-]+$`）
- agent 在 index.yaml 中存在
- weight 自动钳位到 `[-2.0, 2.0]`
- regex 语法使用 `re.compile()` 预检查
- skills 引用必须在 skill-map.yaml 中存在
- `--neg-weight` 将 weight 转为负值

### 6.3 analyze-route-log.py — 路由日志分析

**路径**: `/opt/data/scripts/analyze-route-log.py`（139 行）
**数据源**: `/opt/data/logs/route-engine.jsonl`

**输出统计**:
- method 分布（auto / llm_fallback / auto_tiebreak）
- flagged 条目及原因
- Agent 调用排名
- 按 Agent 回退率（fallback ≥ 15% 且 total ≥ 3 时提供改进建议）
- 时间范围
- flagged 比例 > 20% 时建议审查阈值

---

## 7. 更新历史

### 7.1 Git 提交历史（hermes-skill-governance 仓库）

**仓库**: `git@github.com:zero-0437/hermes-skill-governance`
**本地路径**: `/tmp/hermes-skill-governance`

#### 近期关键提交

| 日期 | Commit | 内容 |
|------|--------|------|
| 2026-07-02 | `62891cb` | **route-map 关键词补齐**：12 个路由文件新增约 36 条规则 |
| 2026-07-02 | `97f6f01` | SOUL.md 三块重构：核心原则 + 委派纪律 + 兜底机制 |
| 2026-07-01 | `60c7976` | 工作流对齐委派铁律：删除手动判定分支 |
| 2026-07-01 | `015c4b8` | 委派铁律重构：6 条 → 3 条，路由引擎接管委派决策 |
| 2026-06-30 | `ec225ec` | SOUL.md 前三段精修：5 项小修复 |
| 2026-06-30 | `65d68f6` | SOUL.md 再减：路由引擎链缩为一行引用 |
| 2026-06-29 | `f2c589b` | SOUL.md 二次瘦身：199 → 116 行（-42%） |
| 2026-06-28 | `82cbf8a` | 拆离主 Agent 内容：agent-environment.md 纯子 Agent 协议 |
| 2026-06-28 | `e6c9f4f` | 双评审改为路由引擎 chain 自动触发 |
| 2026-06-27 | `316b0b2` | SOUL.md 瘦身+修复：路由调用语法修正、绑定表精简 |
| 2026-06-27 | `d7b87ab` | chain_executor.py v2.0: 安全加固 + 文档同步 |
| 2026-06-27 | `009807b` | route_engine skills CLI + SOUL.md/MEMORY 清理 |
| 2026-06-27 | `f35b575` | **feature: 技能反向索引** — 技能→Agent 隐式路由 |
| 2026-06-26 | `ec19e85` | **feat: chain_executor 编排引擎** + programmer 双评审链 |
| 2026-06-26 | `873bce4` | **feat: route chain mechanism** + spec-agent |

#### 版本里程碑

| 版本 | 日期 | 主要变更 |
|------|------|---------|
| v2.0 | 2026-06-26 | route chain mechanism 发布，spec-agent 链 | 
| v2.1 | 2026-06-27 | 技能反向索引、skills CLI | 
| v2.2 | 2026-06-27 | chain_executor v2.0 安全加固 | 
| v2.3 | 2026-06-28 | 双评审 chain 自动触发，SOUL.md 瘦身 | 
| v2.4 | 2026-06-29 | SOUL.md 二次瘦身（-42%），委派铁律重构 | 
| v2.5 | 2026-07-01 | 委派铁律 6→3 条，删除手动判定，路由引擎完全接管 |
| v2.6 | 2026-07-02 | route-map 关键词补齐（+36 条规则） |

### 7.2 备份历史

| 备份目录 | 时间 | 内容 |
|---------|------|------|
| `backups/route-engine-20260702-083738/` | 2026-07-02 08:37 | 空目录（标记性备份） |
| `backups/route-engine-20260702-083745/` | 2026-07-02 08:37 | 含 route_engine.py (21,725B)、index.yaml (3,445B)、programmer.yaml (6,243B)、spec-agent.yaml (1,792B)、chain_executor.py |
| `backups/route-engine-fix-20260702-102015/` | 2026-07-02 10:20 | 修复后备份：route_engine.py (22,133B)、index.yaml (3,701B)、programmer.yaml (6,386B)、agent-environment.md + chain_executor.py |

---

## 8. 配置与调优

### 8.1 Fuzzy 开启策略

根据 `fuzzy-analysis-report.md`（410 行）的详细分析，fuzzy 开启遵循以下原则：

#### 开启动因
- `phrase` + fuzzy：用户可能用子序列变体表达同一意图（"写一下代码" → "写代码"）
- `keyword` + fuzzy：用户可能写错字或用同音/近形字（"架构" → "构架"）
- 多字词组（≥4 字）开启 fuzzy 较安全，单/双字词风险高

#### 不开原因
- `regex` 规则：本身已覆盖变体，加 fuzzy 无意义
- **负权重规则**：加 fuzzy 会扩大防护范围，导致误屏蔽
- 高频泛用词：`实现`、`测试`、`安全`、`文件`、`设计`、`错误`、`文档` 等
- 单字/双字 keyword 加 fuzzy 风险极高

#### Fuzzy-Analysis 报告优先级建议

| 优先级 | 推荐 Agent | 推荐规则数 | 特征 |
|--------|-----------|-----------|------|
| 🔴 P0 立即 | memory-agent (8条), data-analyst (10条) | 18 | 用户变体极多，误匹配风险低 |
| 🟡 P1 批次 | programmer (3条), error-analyst (9条), pm-agent (9条) | 21 | 领域特异性强，安全 |
| 🟢 P2 观察 | ui-designer (5条), file-ops (3条) | 8 | 部分词泛用，需观察 |
| ⚪ 不开 | 所有负权重规则 + 高频泛用词 | — | 风险不可接受 |

### 8.2 权重调优指南

| 权重范围 | 含义 | 使用场景 |
|----------|------|---------|
| 1.0~2.0 | 强匹配 | 精准意图、专有名词、规格场景 |
| 0.7~0.9 | 中等匹配 | 常见关键词、一般意图 |
| 0.5~0.6 | 弱匹配 | 通用词（如"文件"、"图"） |
| -0.3~-0.5 | 轻度防误匹配 | 该 Agent 不应处理但其他 Agent 可能误抢的场景 |
| -1.0~-2.0 | 强防误匹配 | 必须排除的场景（如 spec-agent 排除"失败/错误/出错"） |

#### min_confidence 调优
- 当前值：**0.5**（`index.yaml defaults`）
- 调高（如 0.6）→ 降低自动路由率，增加 fallback → LLM 决策
- 调低（如 0.3）→ 提高自动路由率，但也增加误路由风险

---

## 9. GitHub 仓库与 SSH 配置

### 9.1 仓库信息

| 项目 | 值 |
|------|-----|
| 远程仓库 | `git@github.com:zero-0437/hermes-skill-governance` |
| 本地路径 | `/tmp/hermes-skill-governance` |
| 分支 | `main` |

### 9.2 SSH 配置

**SSH 配置文件**: `/opt/data/home/.ssh/config`

```
Host github.com
    HostName github.com
    User git
    IdentityFile /opt/data/home/.ssh/id_ed25519
    UserKnownHostsFile /opt/data/home/.ssh/known_hosts
```

**SSH 密钥**:
- 私钥: `/opt/data/home/.ssh/id_ed25519`
- 公钥: `/opt/data/home/.ssh/id_ed25519.pub`
- known_hosts: `/opt/data/home/.ssh/known_hosts`

### 9.3 引用方式

```bash
# 克隆仓库
git clone git@github.com:zero-0437/hermes-skill-governance.git

# 查看提交历史
cd hermes-skill-governance
git log --oneline -10
```
