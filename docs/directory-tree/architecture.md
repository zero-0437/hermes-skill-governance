# 目录树架构

> **阅读难度**: ⭐⭐⭐☆☆ (中级)  
> **目标读者**: 需要理解系统设计原理的架构师、需要扩展系统的贡献者

## 目录

1. [核心概念](#核心概念)
2. [skill-map.yaml 结构](#skill-mapyaml-结构)
3. [三端对齐原理](#三端对齐原理)
4. [Agent 生命周期](#agent-生命周期)
5. [数据流全景](#数据流全景)

---

## 核心概念

目录树基于三个核心概念构建：

### 1. 技能层级（Skill Layer）

技能分为 4 层，层号标识抽象等级：

| 层级 | 含义 | 示例 |
|------|------|------|
| **L4 元** | 治理系统本身，操作 skill-map / Agent 边界 | `skill-map-maintenance`, `architecture-integrity-check` |
| **L3 领域** | 特定领域方法，需显式加载 | `product-manager`, `engineering-sre` |
| **L2 角色** | Agent 角色核心能力，自动加载 | `test-driven-development`, `frontend-design` |
| **L1 工具** | 原子工具操作，按需加载 | `pdf`, `xlsx`, `github-search` |

### 2. 加载策略（Load Policy）

每个技能声明 `auto` 或 `manual`：

- **L2 auto**：委派时自动加载到 Agent 上下文，Agent 无需显式声明即可使用。通常是该 Agent 角色定义的核心竞争力。
- **L3 manual**：Agent 必须在委派的 `skill_required` 参数中显式指定后才能使用。通常是辅助/扩展能力，按需激活以避免上下文膨胀。
- **L1 manual**：全局工具池（`shared` 区），所有 Agent 均可按需使用。由 `rebuild-cache.py` 自动合并到各 Agent 的 manual 列表中。

### 3. 技能引用（Skill Ref）

跨 Agent 共享技能通过逻辑引用实现。`ref` 字段指向 `shared` 区中的定义：

```yaml
- name: pdf
  layer: "1 / load: auto"
  ref: shared.文档.pdf  # 指向 shared.文档.pdf，load 可覆盖
```

同一技能在不同 Agent 可有不同的 layer/load，通过 `intentional: true` 标注合法差异。

---

## skill-map.yaml 结构

```
skill-map.yaml
├── schema_version     # 版本号（如 "2.5"）
├── last_updated       # ISO 8601 时间戳
├── maintainer         # 维护者 Agent 名
├── agents/            # 12 个 Agent 的技能分配
│   ├── pm-agent/
│   │   ├── description
│   │   └── categories/
│   │       ├── 架构治理/
│   │       │   └── [skills]  # 每技能含 name, layer, ref(可选), intentional(可选)
│   │       ├── 项目管理/
│   │       ├── 软件工程/
│   │       ├── Hermes_运维/
│   │       └── 系统设计/
│   ├── programmer/
│   ├── error-analyst/
│   ├── ... (共 12 个 Agent)
│   └── docs-writer/
└── shared/            # 全局 L1 工具池，所有 Agent 按需加载
    ├── description
    └── categories/
        ├── 文档/
        ├── 搜索/
        ├── 远程/
        ├── 可视化/
        ├── 数据/
        ├── 调试/
        └── 备份/
```

### 技能条目字段

```yaml
- name: codebase-inspection        # 技能名（对应 skills/<name>/SKILL.md）
  layer: "2 / load: auto"          # 层级 + 加载策略
  ref: shared.审查.codebase-inspection  # 可选，逻辑引用
  intentional: true                # 可选，标注跨 Agent 合法差异
```

- `ref` 指向共享区的技能定义，该 Agent 可覆盖其 `load` 策略
- `intentional` 用于告知校验器「此处的层级/加载策略差异是故意的，非配置错误」

---

## 三端对齐原理

系统存在三个「真相持有者」，校验器确保它们完全一致：

```
skill-map.yaml          .skill-cache.json        SOUL.md(绑定表)
+ 子Agent allowed-skills.md
+ agent-environment.md
```

| 端 | 路径 | 本质 | 维护方式 |
|----|------|------|---------|
| **注册端** | `skill-map.yaml` | 单一真相源（Source of Truth） | 人工编辑 |
| **缓存端** | `.skill-cache.json` | 主 Agent 委派决策的运行时快照 | `rebuild-cache.py` 自动生成 |
| **配置端** | `SOUL.md` 绑定表 + Agent `SOUL.md` | 各 Agent 理解自身能力的元数据 | 人工编辑 + 脚本生成 |

### 校验维度

`validate-skill-map.py` 检查 11 个维度确保三端对齐。详见 [reference.md § 校验维度](./reference.md#校验维度)。

### 缓存过期机制

- `.skill-cache.json` 包含 `ttl_minutes: 30`
- 主 Agent 每次委派前检查 `last_updated` 与当前时间差
- 超过 TTL 则触发 `rebuild-cache.py` 重建
- 子 Agent 的 `allowed-skills.md` 同理，由重建时一并刷新

---

## Agent 生命周期

```
┌─────────────┐    delegation    ┌──────────────┐
│  主 Agent   │ ───────────────→ │  子 Agent    │
│ (pm-agent)  │                  │ (programmer  │
│  只委派     │                  │  error-analyst│
│  不干活     │                  │  ...等12个)   │
└─────────────┘                  └──────────────┘
       │                                │
       │ 检查缓存 TTL                   │ 查 allowed-skills.md
       │ 查 .skill-cache.json           │ 确认技能可用
       │ 从绑定表选 Agent               │
       │                                │
       ▼                                ▼
  rebuild-cache.py               agent-environment.md
  validate-skill-map.py          委派规范 + 执行纪律
```

### 日常运转流程

1. **定义变更**：pm-agent 编辑 `skill-map.yaml`（增删技能、调整 layer/load）
2. **重建缓存**：运行 `rebuild-cache.py` → 生成 `.skill-cache.json` + 各 Agent 的 `allowed-skills.md`
3. **校验对齐**：运行 `validate-skill-map.py` → 确认 11 维度无 ERR
4. **委派执行**：主 Agent 在每次委派时注入 `contexts/agent-environment.md` 中的执行纪律
5. **Agent 自检**：子 Agent 启动时对照 `allowed-skills.md` 确认技能范围

### 架构级任务判定

主 Agent 的 `SOUL.md` 规定：满足以下任一条件的任务必须转交 pm-agent：

1. 操作治理文件（skill-map/SOUL.md 结构/Agent 边界/协议）
2. 跨域联动 — 改后需跑 `rebuild-cache.py` + `validate-skill-map.py`
3. 需拓扑排序/依赖消解/多 Agent 冲突处理

---

## 数据流全景

```
                  ┌────────────────────────┐
                  │    skill-map.yaml      │  ← 单一真相源
                  │   (12 Agent + shared)   │
                  └───────────┬────────────┘
                              │
                    ┌─────────▼──────────┐
                    │  rebuild-cache.py   │  ← 缓存重建
                    └──┬─────────────┬───┘
                       │             │
           ┌───────────▼──┐   ┌──────▼──────────────┐
           │ .skill-cache │   │ profiles/<agent>/    │
           │ .json        │   │ allowed-skills.md    │
           │ (主Agent用)   │   │ (子Agent自检用)       │
           └──────┬───────┘   └─────────────────────┘
                  │
    ┌─────────────▼──────────────┐
    │  validate-skill-map.py     │  ← 11 维度校验
    │  校验三端一致性              │
    └─────────────┬──────────────┘
                  │
    ┌─────────────▼──────────────┐
    │  主 Agent (pm-agent)       │
    │  SOUL.md 绑定表 ←→ 缓存    │
    │  委派决策 ←→ 可用技能列表   │
    └─────────────┬──────────────┘
                  │ delegate_task
    ┌─────────────▼──────────────┐
    │  12 个子 Agent             │
    │  context 注入              │
    │  agent-environment.md      │
    │  执行纪律 + 技能白名单      │
    └────────────────────────────┘
```
