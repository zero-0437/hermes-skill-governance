# 技能反向索引 — Skill→Agent 隐式路由

> 路由引擎 `route_engine.py` 新增功能  
> 实现从「技能名 → 拥有该技能的 Agent」的隐式路由路径  
> 与现有显式路由规则（关键词/正则/短语）并存互补

---

## 设计思路

### 问题

现有路由引擎仅依赖 route-map 中的关键词、正则和短语规则进行显式路由。用户可能直接提及技能名（如
"test-driven-development"、"systematic-debugging"），但显式规则未必覆盖这些技能名，导致技能持有者
Agent 无法被路由命中。

### 解决方案

从 `.skill-cache.json` 自动构建 **skill_name → [agent_list]** 反向索引。当用户输入中出现技能名时，
自动为该技能的所有者 Agent 加分，无需在 route-map 中额外声明规则。

```
┌─────────────┐     ┌─────────────────────┐     ┌─────────────────┐
│ 用户输入     │ ──→ │ skill 反向索引匹配    │ ──→ │ 匹配命中？       │
│ "请用TDD..." │     │ → test-driven-dev    │     │ → programmer +0.2│
└─────────────┘     └─────────────────────┘     └─────────────────┘
                                    │                      ↓
                                    │               ┌─────────────────┐
                                    │               │ 合并到 evaluate  │
                                    │               │ 评分结果再 decide │
                                    │               └─────────────────┘
                                    ↓
                          ┌─────────────────────┐
                          │ 未命中 → 不影响评分    │
                          └─────────────────────┘
```

### 与显式路由的关系

| 维度 | 显式路由（route-map） | 隐式路由（技能反向索引） |
|:----:|----------------------|------------------------|
| 数据源 | route-map/*.yaml | .skill-cache.json |
| 匹配对象 | 关键词/正则/短语 | 技能名 |
| 触发方式 | 规则命中 → 加分 | 技能名出现 → 加 0.2 |
| 维护成本 | 需手动添加规则 | 自动构建，零维护 |
| 优先级 | evaluate 阶段主评分 | evaluate 后合并加分 |

两种路由路径独立运行、互不冲突，最终评分合并后进入 `decide()` 决策。

---

## 使用方式

### 自动生效

无需任何配置。路由引擎启动时自动：

1. 调用 `_build_skill_owners()` 从 `.skill-cache.json` 构建反向索引
2. 在 `route()` 的 evaluate/decide 之间调用 `_score_skill_matches()`
3. 将技能加分合并到 Agent 评分列表后，进入正常决策流程

### 加分策略

| 条件 | 加分 |
|:----:|:----:|
| 用户输入中出现一个技能名，且该技能有 N 个 owner | 每个 owner Agent 各 +0.2 |
| 同时命中多个技能名 | 每个 skill+owner 组合叠加加分 |
| 同一个 Agent 有多项技能被命中 | 叠加：如 3 个技能命中 → +0.6 |
| 无人拥有该技能 | 无影响，评分不变 |

> **参考**：显式路由规则权重通常为 0.3~1.0，技能加分的 0.2 是**轻量辅助加分**，不会压倒显式规则，
> 但足以为技能相关 Agent 提供路由倾向。

### 效果示例

用户输入 `"运行 test-driven-development 流程修复这个 bug"`：
- 技能 `test-driven-development` 被命中（管理员 → programmer）
- programmer 获得 +0.2 加分
- 若 programmer 原有显式评分 0.3，最终评分 0.5，可能达到阈值并被选中

---

## 核心函数

### `_build_skill_owners()`

```python
def _build_skill_owners() -> dict[str, list[str]]
```

从 `.skill-cache.json` 的 `agents` 字段遍历每个 Agent 的 L2 auto 和 L3 manual 技能，
构建 `{skill_name: [agent1, agent2, ...]}` 反向索引。

- 自动去重：同一 Agent 的 auto+manual 中相同技能只计一次
- 支持共享技能：同一技能名被多个 Agent 持有（如 `codebase-inspection` 同时在 programmer 和 error-analyst）
- 缓存友好：依赖 `_load_skill_cache()` 的模块级缓存，不重复读磁盘

### `_score_skill_matches()`

```python
def _score_skill_matches(text: str, owners: dict[str, list[str]]) -> tuple[dict[str, float], set[str]]
```

根据用户输入中提及的技能名，计算每个 Agent 的加分。

**返回值**：
- `scores: dict[str, float]` — `{agent_name: bonus}`，每个命中技能为 owner 加 0.2
- `matched_skills: set[str]` — 实际命中的技能名集合

**加分逻辑**：遍历反向索引的所有技能名，判断是否出现在用户输入（归一化后文本）中。
每个命中技能为每个 owner 累加 0.2。多技能叠加。

---

## 边界保护逻辑

### 短纯英文技能名（< 5 字符）使用 `\b` 单词边界匹配

短技能名（如 `plan`、`pdf`、`git`）如果使用简单的 `in` 子串匹配，容易误触发：

| 输入文本 | 包含 "plan" 子串 | 实际含义 | 应匹配？ |
|---------|:----------:|----------|:------:|
| "explanation" | ✅ | 说明文档 | ❌ |
| "please plan the task" | ✅ | 请规划任务 | ✅ |
| "transplant" | ✅ | 移植操作 | ❌ |

解决方案：对 `len(skill_name) < 5 and skill_name.isascii() and skill_name.isalpha()` 的技能名，
使用正则 `\b{skill}\b` 进行单词边界匹配。

```python
if len(skill_name) < 5 and skill_name.isascii() and skill_name.isalpha():
    if not re.search(rf'\b{re.escape(skill_name.lower())}\b', normalized):
        continue
```

### 其他情况使用 `in` 子串匹配

- **含连字符的技能名**（如 `test-driven-development`）：连字符将 skill 绑定为整体，`in` 子串匹配即可准确匹配全名
- **CJK 技能名**：中文无单词边界概念，使用 `in` 子串
- **长度 >= 5 的技能名**：较长名称自然降低误匹配概率，`in` 子串匹配足够

### 边界情况汇总

| 技能名 | 长度 | 匹配策略 | 输入 | 结果 |
|--------|:---:|:--------:|------|:----:|
| `pdf` | 3 | `\b` 边界 | "cpdf viewer" | ❌ 不匹配 |
| `pdf` | 3 | `\b` 边界 | "use pdf tools" | ✅ 匹配 |
| `plan` | 4 | `\b` 边界 | "explanation" | ❌ 不匹配 |
| `git` | 3 | `\b` 边界 | "digit-al" | ❌ 不匹配 |
| `test-driven-development` | 25 | `in` 子串 | "need tdd approach" | ❌ 不匹配 |
| `test-driven-development` | 25 | `in` 子串 | "run test-driven-development" | ✅ 匹配 |
| `chinese` | 7 | `in` 子串 | "chinese-restaurant" | ⚠️ 可能误匹配 |

> `chinese` 这类长单词嵌入复合词的情况是已知局限。`in` 子串为长技能名提供更宽松匹配，
> 若需更严格匹配，可以在 route-map 中补充显式 regex 规则覆盖。

---

## 集成位置

在 `route()` 主流程中的位置：

```
route(user_input)
  ├─ load_route_map()
  ├─ normalize()
  ├─ 检查 overrides（直接委派，跳过后续）
  ├─ evaluate()                         ← 显式路由评分
  ├─ _build_skill_owners()              ← 构建反向索引
  ├─ _score_skill_matches()             ← 技能加分
  ├─ 合并评分（evaluate 结果 + skill 加分）
  ├─ decide()                           ← 最终决策
  └─ 提取 matched_rules / 技能分配
```

代码位置：`route_engine.py` 第 111–155 行（函数定义），第 464–476 行（调用集成）。

---

## 修改清单

| 条目 | 说明 |
|:----:|------|
| **新增函数** | `_build_skill_owners()` — 构建技能→Agent 反向索引 |
| **新增函数** | `_score_skill_matches()` — 计算技能匹配加分 |
| **修改函数** | `route()` — 在 evaluate/decide 之间插入技能反向匹配流程 |
| **新增常量** | 无（复用现有 `SKILL_CACHE_FILE`） |
| **新增依赖** | 无（仅使用 `json`、`re`，均已导入） |
| **影响范围** | 仅 `route_engine.py`，零侵入 route-map 和 skill-cache 结构 |

---

## 测试要点

1. **基础功能**：用户输入 `"use test-driven-development"` → programmer 应获 +0.2
2. **多技能叠加**：`"use tdd and systematic-debugging"` → programmer +0.4（若双技能均绑定）
3. **共享技能**：技能被多个 Agent 持有，所有 owner 都应加分
4. **短名边界保护**：`"transplant"` 不应匹配 `plan`，`"cpdf"` 不应匹配 `pdf`
5. **无技能命中**：输入 `"hello world"` → 无加分，评分不变
6. **与显式规则叠加**：显式 +0.3 的技能命中 +0.2 → 最终 0.5
7. **空技能缓存**：`.skill-cache.json` 不存在或为空 → 静默跳过，不抛异常
