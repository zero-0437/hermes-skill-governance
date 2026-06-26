# Skill 目录树 — Hermes 多 Agent 技能治理系统

> 四层分层模型 + Agent 目录树 + 持久化缓存 + 自动审计闭环  
> 纯文件变更，零框架依赖 | Hermes v0.17.0 | 2026-06-26

---

## 为什么需要？

现有 140+ Skill 以扁平列表管理，三个痛点：

| 痛点 | 影响 |
|------|------|
| **子 Agent 启动慢** | 委派后 worker 先探索 2-4 轮才能定位正确技能，延迟 8-16s |
| **主 Agent 不知情** | 委派时不了解 worker 能力边界，无法预判可行性和耗时 |
| **维护无章法** | 安装/删除 Skill 后注册分散多处，易遗漏致不一致 |

---

## 架构

### 四层分层模型

```
L4 元技能     ── 系统自身治理（主 Agent / PM-agent 专属）
L3 领域技能   ── 跨 Agent 专业知识（按需注入）
L2 角色技能   ── Agent 绑定工作方法（委派时自动注入）
L1 工具技能   ── 单能力封装（任意 Agent 按需加载）
```

| Layer | 加载方式 | 谁加载 | 生命周期 | 示例 |
|:-----:|---------|--------|----------|------|
| L1 | manual — `skill_view` 按需 | 任意 Agent | 任务级 | `pdf`, `github-search`, `maps` |
| L2 | auto — 委派时自动注入 | 绑定 Agent | 会话级 | `test-driven-development`→programmer |
| L3 | manual — context 显式指定 | 跨 Agent 共享 | 任务级 | `product-manager`, `civil-servant` |
| L4 | auto — 常驻 | 主/PM-agent | 常驻 | `multi-agent-arch`, `plan` |

### Agent 目录树 (`skill-map.yaml`)

以 Agent → 分类 → 技能 两层组织，每技能标注 layer 和 load。跨 Agent 技能以逻辑引用出现在多个节点，不复制文件。

```yaml
# 307 行 / 9.6KB / 10 Agent + shared 全局区
agents:
  programmer:
    categories:
      方法论:
        - name: test-driven-development
          layer: "2 / load: auto"
        - name: systematic-debugging        # 跨 Agent（同在 error-analyst/诊断）
          layer: "2 / load: auto"
          intentional: true
```

### 持久化缓存 (`.skill-cache.json`)

skill-map.yaml 的 auto/manual 二分摘要（149 行 / 3.3KB）。主 Agent 委派前只读此文件。

```
读取规则（优先级递减）：
1. 缓存存在 + cache_version 匹配 + mtime ≤ 30min  → 直接使用
2. 过期/不存在 → 降级读 skill-map.yaml 全文 → 后台异步刷新缓存
```

### 委派链路

```
主 Agent（pro，session 缓存）
  ├─ 读 .skill-cache.json → 获取目标 Agent 技能摘要
  ├─ 委派 PM-agent：context 注入 L3 manual 技能列表
  │
  └→ PM-agent
       ├─ 查 skill-map.yaml → 按任务选 Agent→分类→技能
       ├─ 输出决策（≤3 行）：目标 + auto 列表 + manual 列表
       └→ worker：1 轮开工（跳过技能探索）
```

关键规则：
- L2 auto 通过 `skill_view` 注入，context 不重复
- L3 manual 在 context 显式指定 + 「按需补充」
- 主 Agent 禁止加载任何已绑定子 Agent 的 Skill

---

## 治理工具链

### 全量审计器 (`validate-skill-map.py`)

309 行 Python 脚本，11 维跨文件一致性检查：

| # | 维度 | 级别 | 说明 |
|---|------|:---:|------|
| 1 | YAML 语法 | ERR | 解析合法性 |
| 2 | 引用技能存在性 | WARN | 每个 name → 有对应 SKILL.md |
| 3 | layer 格式 | ERR | L1-L4 + auto/manual |
| 4 | 跨 Agent 冲突标注 | WARN | layer 不同必须 `intentional: true` |
| 5 | cache 一致性 | WARN | auto/manual 列表与 YAML 对齐 |
| 6 | schema_version | WARN | 必须为 "2.0" |
| 7 | SOUL.md 绑定表对齐 | WARN | 10 Agent 的 L2/L3 列表一致 |
| 8 | Agent SOUL.md 存在性 | ERR | 10 个 profile 目录均有 SOUL.md |
| 9 | Registry 对齐 | WARN | skill-map 与 registry 的 Agent 名一致 |
| 10 | 孤儿技能 | INFO | 未注册的独立技能（70 个，不影响退出码） |
| 11 | agent-environment.md 完整性 | WARN | 缓存/TTL 相关概念存在 |

**退出码**: 0=OK, 1=WARN, 2=ERR。INFO 不影响。cron 每日 3am 自动巡检。

### 缓存重建 (`rebuild-cache.py`)

60 行脚本，从 skill-map.yaml 解析 layer/load 字段，输出 auto/manual 二分格式的 `.skill-cache.json`。

### 自助维护流程 (`skill-map-maintenance` Skill)

186 行 L4 元技能，定义安装/删除的标准步骤：

**安装**：skill_view → 读 frontmatter → 校验 → 上报主 Agent → file-ops 写 YAML → 刷新缓存 → 同步 SOUL.md → 运行审计器

**删除**：file-ops 删 YAML 条目（含跨 Agent） → 删 SOUL.md → 刷新缓存 → 运行审计器 → grep 确认残留

---

## 本次改进（2026-06-26 v2.1）

> 外部审查驱动：DeepSeek 对 v2.0 设计的分析报告 → 可行性评估 → 三合一实施

### 触发

DeepSeek 在审查报告中肯定了架构设计（"设计优雅、务实且轻量级"），同时指出 6 项风险。经可行性评估，选取前 3 项高价值+低投入的立即实施。

### 改进清单

| # | 改进 | 文件 | 影响 |
|---|------|------|------|
| **P0** | 缓存 TTL + 降级 | `SOUL.md`, `.skill-cache.json` | 缓存过期时不再阻塞，降级读 YAML 全文 + 后台异步刷新 |
| **P1** | 冲突标注机制 | `skill-map.yaml` | 3 对跨 Agent 技能（`codebase-inspection`/`llm-wiki`/`ssh-172`）加 `intentional: true` |
| **P2** | 全量审计器 + 日常巡检 | `validate-skill-map.py`, cron | 6 项→11 项检查 + 每日 3am 自动巡检 |

附带修复：
- `rebuild-cache.py` 输出格式从按分类改为 auto/manual 二分，对齐 SOUL.md 需要
- 所有 Python 脚本 shebang 改为 `#!/usr/bin/env -S uv run python`，消除系统 Python 无 pyyaml 的依赖问题
- `agent-environment.md` §8 补缓存/TTL 规则
- SOUL.md 绑定表 programmer 补全 9 个 L1 工具技能
- `skill-map-maintenance` 文档同步更新（审计器 11 维说明 + 流程步骤编号调整）

### 未实施

| # | 建议 | 原因 |
|---|------|------|
| 4 | 技能版本管理 | 140+ 技能阶段过早，需改 YAML 结构 |
| 5 | 监控度量 | 需基础设施，Hermes 框架不提供 hook |
| 6 | PM 决策可解释性 | 投入产出比低，可用 checkpoint 临时覆盖 |

---

## 文件清单

| 文件 | 行数 | 用途 |
|------|:--:|------|
| `skill-map.yaml` | 307 | Skill 目录树（Agent→分类→技能，v2.1） |
| `.skill-cache.json` | 149 | JSON 摘要缓存（auto/manual 二分） |
| `SOUL.md` | 91 | 主 Agent 规则 + 快速索引 + 缓存降级逻辑 |
| `agent-environment.md` | 115 | 通用规范 §1-§8（四层加载 + 缓存规则） |
| `pm-agent/SOUL.md` | 67 | 委派前技能选择流程 |
| `skill-map-maintenance/SKILL.md` | 186 | 安装/删除维护流程 + 审计器说明 |
| `validate-skill-map.py` | 309 | 11 维全量审计器 |
| `rebuild-cache.py` | 60 | 缓存重建脚本 |
| `validate-skill-map-cron.sh` | 4 | cron wrapper |
| `hermes-team-registry.md` | 143 | Agent 角色单源注册表 |
| `commands.md` | 95 | 命令速查 |
| **合计** | **1,526** | |

---

## 关键决策

| 决策 | 理由 |
|------|------|
| 四层而非三层 | L4 与 L3 加载权限不同——合并模糊安全边界，L4 常驻特征单独成层更清晰 |
| PM-agent 负责技能选择 | 是任务拆解的自然延伸，不增新 Agent，不改现有委派链路 |
| 持久化缓存（非 session） | 职责分离：YAML 是 PM-agent 内部数据，主 Agent 只看导出视图 |
| Skill 自声明 + PM-agent 复核 | 作者最了解用途，PM-agent 只做校验，降低分类成本 |
| 跨 Agent 逻辑引用（非物理拷贝） | 单源维护，各 Agent 独立设 layer/load |
| 缓存降级而非阻塞 | 过期时直接读 YAML + 后台异步刷新，零等待 |
| 审计器集成进维护流程 | 安装/删除后必须通过 11 维检查才能报 OK，cron 兜底 |

---

> 版本 v2.1 | 最后更新 2026-06-26T11:40Z | 纯文件变更，零框架依赖 | 审计状态: **OK** (0 ERR / 0 WARN)
