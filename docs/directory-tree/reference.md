# 参考手册

> **阅读难度**: ⭐⭐☆☆☆ (查阅型)  
> **目标读者**: 需要查字段定义、命令参数、校验规则的开发者和运维者

## 目录

1. [skill-map.yaml 字段说明](#skill-mapyaml-字段说明)
2. [rebuild-cache.py 参考](#rebuild-cachepy-参考)
3. [validate-skill-map.py 参考](#validate-skill-mappy-参考)
4. [.skill-cache.json 结构](#skill-cachejson-结构)
5. [退出码速查](#退出码速查)

---

## skill-map.yaml 字段说明

### 顶层字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `schema_version` | string | ✅ | 模式版本号，校验器要求 `"2.5"` |
| `last_updated` | string | ✅ | ISO 8601 UTC 时间戳，格式 `YYYY-MM-DDTHH:MM:SSZ` |
| `maintainer` | string | ✅ | 维护者 Agent 名（固定 `pm-agent`） |
| `agents` | map | ✅ | Agent→技能映射表，12 个 Agent 条目 |
| `shared` | map | ✅ | 全局 L1 工具池，所有 Agent 可引用 |

### agents.<agent_name> 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `description` | string | ✅ | Agent 角色描述 |
| `categories` | map | ✅ | 分类→技能列表，键为中文分类名 |

### 技能条目字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| `name` | string | ✅ | 技能名，对应 `skills/<name>/SKILL.md` |
| `layer` | string | ✅ | 格式 `"<L> / load: <auto|manual>"`，如 `"2 / load: auto"` |
| `ref` | string | ❌ | 逻辑引用，格式 `shared.<类别>.<技能名>` |
| `intentional` | bool | ❌ | 跨 Agent 合法差异标注，告知校验器忽略此技能的分层冲突 |

### layer 字段格式

```yaml
layer: "4 / load: auto"
#      │    │     │
#      L   分隔  加载策略
```

| 组件 | 有效值 | 说明 |
|------|--------|------|
| L（层级） | `1`, `2`, `3`, `4` | L1=工具, L2=角色, L3=领域, L4=元 |
| load（加载） | `auto`, `manual` | auto=自动加载, manual=需显式指定 |

### shared 字段

```yaml
shared:
  description: "全局可用 L1 工具技能，所有 Agent 按需 skill_view"
  categories:
    文档:
      - name: pdf
        layer: "1 / load: manual"
      - name: docx
        layer: "1 / load: manual"
```

`shared` 区所有技能均为 L1 manual，由 `rebuild-cache.py` 自动合并到每个 Agent 的 manual 列表中。若 Agent 已有同名技能（可能以不同 layer/load），则 shared 版本不覆盖。

---

## rebuild-cache.py 参考

### 命令

```bash
cd /opt/data && uv run python scripts/rebuild-cache.py
```

### 输入 / 输出

| 方向 | 路径 | 说明 |
|------|------|------|
| **输入** | `/opt/data/skill-map.yaml` | 技能注册表 |
| **输出 1** | `/opt/data/.skill-cache.json` | 主 Agent 委派决策缓存 |
| **输出 2** | `/opt/data/profiles/<agent>/allowed-skills.md` | 各 Agent 技能清单 |

### 参数（无命令行参数）

脚本不接受命令行参数。所有配置硬编码于脚本：

| 常量 | 值 | 说明 |
|------|----|------|
| `SKILL_MAP` | `/opt/data/skill-map.yaml` | 输入路径 |
| `CACHE_FILE` | `/opt/data/.skill-cache.json` | 缓存输出路径 |
| `PROFILES_DIR` | `/opt/data/profiles` | 子 Agent 目录 |
| `TTL_MINUTES` | `30` | 缓存有效期 |

### 缓存结构

`rebuild-cache.py` 生成的 `.skill-cache.json`：

```json
{
  "schema_version": "2.5",
  "cache_version": 1,
  "ttl_minutes": 30,
  "last_updated": "2026-06-28T11:44:01Z",
  "agents": {
    "<agent_name>": {
      "role": "角色描述",
      "auto": ["skill_a", "skill_b"],
      "manual": ["skill_x", "skill_y", ...]
    }
  }
}
```

- `auto` 列表：L2 auto 技能 + shared 区中 AI 技能若 Agent 定义中覆盖 load 为 auto
- `manual` 列表：L3 manual 技能 + shared 区所有 L1 manual 工具（已去重）
- `agents` 条目总数 = skill-map.yaml 中定义的 Agent 数（当前 12 个）

### 退出码

| 退出码 | 含义 |
|:------:|------|
| `0` | 成功重建 |
| `1` | 致命错误（skill-map.yaml 不存在 / YAML 解析失败 / PyYAML 未安装） |

---

## validate-skill-map.py 参考

### 命令

```bash
cd /opt/data && uv run python scripts/validate-skill-map.py
```

### 参数（无命令行参数）

脚本不接受命令行参数。所有路径硬编码于脚本常量（见 [输入路径](#输入路径)）。

### 输入路径

| 常量 | 路径 | 用途 |
|------|------|------|
| `SKILL_MAP` | `/opt/data/skill-map.yaml` | 注册表 |
| `CACHE` | `/opt/data/.skill-cache.json` | 运行时缓存 |
| `SKILLS_DIR` | `/opt/data/skills` | 技能目录 |
| `AGENTS_DIR` | `/opt/data/profiles` | Agent 配置目录 |
| `SOUL_MD` | `/opt/data/SOUL.md` | 主 Agent 总控规则 |
| `ENV_MD` | `/opt/data/contexts/agent-environment.md` | 委派规范 |

### 校验维度

| # | 维度 | 检查内容 | 严重级别 |
|:--:|------|----------|:--------:|
| 1 | **YAML 语法** | skill-map.yaml 可被 yaml.safe_load 正确解析 | ERR |
| 2 | **技能存在性** | 每个注册的技能在 `skills/<name>/SKILL.md` 有对应文件 | WARN |
| 3 | **layer 格式** | layer 字段符合 `"<1-4> / load: <auto|manual>"`，层级和加载策略均在有效值范围内 | ERR |
| 4 | **跨 Agent 冲突** | 同一技能被多个 Agent 以不同 layer 使用时，必须标注 `intentional: true` | WARN |
| 5 | **缓存一致性** | `.skill-cache.json` 的 Agent 列表、auto/manual 技能集合与 skill-map.yaml 完全一致（含 shared 合并） | WARN |
| 6 | **schema_version** | skill-map.yaml 的 schema_version 为 `"2.0"` 或更新 | WARN |
| 7 | **SOUL.md 绑定表** | SOUL.md 中的 Agent→Skill 绑定表与 skill-map.yaml 的 auto/manual 技能集合完全一致 | WARN |
| 8 | **Agent SOUL.md** | 每个注册 Agent 在 `profiles/<agent>/SOUL.md` 有对应文件 | ERR |
| 9 | **孤儿技能** | `skills/` 目录中存在未在 skill-map.yaml 中注册的 SKILL.md（深度 ≤2 的子目录） | INFO |
| 10 | **registry 对齐** | 备用预留（实际检查合并于维度 5/7） | — |
| 11 | **agent-environment.md** | 委派规范文档存在且提及 `.skill-cache.json`、`skill-map.yaml`、`TTL` 等关键字 | WARN |

### 退出码

| 退出码 | 含义 | 触发条件 |
|:------:|------|----------|
| `0` | 校验通过 | 无 ERR，无 WARN（INFO 不影响） |
| `1` | 存在警告 | 无 ERR，但至少 1 条 WARN |
| `2` | 存在错误 | 至少 1 条 ERR（PASS 阻塞） |

### 输出格式

标准输出为 JSON，包含以下字段：

```json
{
  "status": "OK|WARN|FAIL",
  "checked_at": "2026-06-28T12:00:00+0000",
  "errors": 0,
  "warnings": 2,
  "info": 1,
  "errors_list": [],
  "warnings_list": ["[agent] 缓存不一致: ...", "..." ],
  "info_list": ["未注册的独立技能 (3 个): ..."]
}
```

### 典型工作流

```bash
# 修改 skill-map.yaml 后
cd /opt/data

# 1. 重建缓存
uv run python scripts/rebuild-cache.py

# 2. 全量校验
uv run python scripts/validate-skill-map.py

# 3. 若退出码非0，查看具体问题
uv run python scripts/validate-skill-map.py 2>&1 | python -m json.tool | grep -E 'errors_list|warnings_list'

# 4. 修复后重复步骤 1-3 直到退出码为 0
```

---

## .skill-cache.json 结构

```json
{
  "schema_version": "2.5",
  "cache_version": 1,
  "ttl_minutes": 30,
  "last_updated": "2026-06-28T11:44:01Z",
  "agents": {
    "pm-agent": {
      "role": "技术架构师 + 执行调度者",
      "auto": ["multi-agent-arch", "delegation-multi-agent", "skill-map-maintenance", "skill-creator", "plan", "engineering-software-architect", "engineering-multi-agent-systems-architect"],
      "manual": ["architecture-integrity-check", "multi-agent-swarm", "product-manager", "...", "pdf", "docx", "..."]
    }
    // ... 其余 11 个 Agent
  }
}
```

**注意**：`manual` 列表包含 shared 全局 L1 工具（`pdf`、`docx`、`github-search` 等），这些是 `rebuild-cache.py` 自动合并进去的，不在 skill-map.yaml 的 Agent 节点下显式出现。

---

## 退出码速查

| 脚本 | 退出码 0 | 退出码 1 | 退出码 2 |
|------|:--------:|:--------:|:--------:|
| `rebuild-cache.py` | 成功重建 | 致命错误 | — |
| `validate-skill-map.py` | OK（通过） | WARN（警告） | FAIL（错误） |
