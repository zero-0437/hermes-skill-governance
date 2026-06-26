---
name: skill-map-maintenance
description: skill-map.yaml 目录树维护——新 Skill 安装时分类归位、废弃 Skill 时清理条目。PM-agent 分类决策→file-ops 物理写入。当用户安装/删除 Skill、委派「更新 skill-map.yaml」、或触发架构治理任务时使用此技能。
layer: "4 / load: auto"
load: auto
category: 架构治理
maintainer: pm-agent
---

# skill-map-maintenance — Skill 目录树维护工作流

## 定位

L4 元技能（架构治理）。skill-map.yaml 是 Agent→Skill 映射的单源真相，本技能定义其读写工作流。PM-agent 负责分类决策，file-ops 负责物理写入。

## 触发条件

- 用户安装新 Skill（`hermes skills install` 或手动创建）
- 用户删除 Skill
- 主 Agent 委派「更新 skill-map.yaml」「注册新 Skill 到目录树」
- 架构审计发现 skill-map.yaml 与实际 skill 目录不一致

## 核心原则

1. **决策与执行分离**：PM-agent 分类决策 → 主 Agent 确认 → file-ops 物理写入
2. **skill-map.yaml 单源真相**：SOUL.md 绑定表从 skill-map.yaml 导出，修改以 skill-map.yaml 为准
   - 绑定表位于主 Agent 配置文件 `/opt/data/SOUL.md` 第 51-67 行（Markdown 表格），并非各子 Agent 的 profile SOUL.md
3. **跨 Agent 技能逻辑引用**：同一技能可在多个 Agent 节点列出，不复制文件
4. **Skill 自声明优先** — 新建 Skill 在 frontmatter 中声明 layer/load/assign_to/category，PM-agent 复核。无声明时 PM-agent 自行分类。
5. **layer 值含冒号必须双引号包裹**：YAML 陷阱——`layer: "4 / load: auto"`

## 安装流程

```
1. skill_view('新技能名') → 理解用途与领域
2. read_file('/opt/data/skill-map.yaml') → 浏览现有分类结构
3. 读 SKILL.md frontmatter → 取声明字段（如果存在的话）：
   - layer / load / assign_to / category
   有声明 → 校验合理性（分类是否存在、层级是否合理）
     - 合理 → 直接使用
     - 不合理 → 上报主 Agent 说明差异
   无声明 → PM-agent 自行判断：
     - 归属 Agent: <name>
     - 所属分类: <category>
     - 层级: L1/L2/L3/L4 / 加载: auto|manual
4. 上报主 Agent 确认分类决策
5. 主 Agent 确认 → 委派 file-ops:
   「在 skill-map.yaml → agents → <agent> → <category> 下追加：
     - name: xxx
       layer: "X / load: auto|manual"」
5.5. 委派 file-ops 刷新缓存:
    cd /opt/data && ./skills/multi-agent-arch/skill-map-maintenance/scripts/rebuild-cache.py
    （直接 `./` 执行，禁止加 python3 前缀——shebang 内建 uv run python）
6. 委派 file-ops 同步更新 `/opt/data/SOUL.md` 绑定表（所有新增技能，不分层级）
   - 定位第 51-67 行的 Markdown 表格
   - L2/L4 auto → 追加到目标 Agent 的 L2 auto 列
   - L1/L3 manual → 追加到目标 Agent 的 L3 manual 列
6.5. 运行校验器:
    cd /opt/data && ./scripts/validate-skill-map.py
    （直接 `./` 执行，禁止加 python3 前缀）
   若有 WARN 或 FAIL → 修复后重新运行，确认 OK 再汇报
7. 验证：skill_view 确认 SKILL.md 存在 + grep 确认 skill-map.yaml 无残留
```

### 分类决策原则

| 原则 | 说明 |
|------|------|
| **Agent 专用** | 仅一个 Agent 使用的工具 → 该 Agent 对应分类下 |
| **跨 Agent 共享** | 多个 Agent 均需使用 → 各 Agent 节点 + shared 区各加一条 |
| **架构/治理** | 元技能，系统自身管理 → pm-agent → 架构治理，L4/auto |
| **单一专属优先** | 优先归属最相关的 Agent，避免共享造成的维护负担 |
| **存疑上报** | 分类不确定时上报主 Agent，不自行决定 |
| **layer/load 差异标注** | 同一技能跨 Agent 有不同 layer/load → 所有条目加 `intentional: true` |

### L4 元技能归属规则

L4 技能（架构治理类）归入 pm-agent → 架构治理，双层属性：
- **pm-agent**：运行时使用（分类决策时查此技能）
- **架构治理**：所属分类标签

## 删除流程

```
1. 委派 file-ops: 从 skill-map.yaml 删除该 Skill 的所有条目
   （注意跨 Agent 引用——删除所有节点中的同名条目）
2. 委派 file-ops: 从 SOUL.md 绑定表删除（如果存在）
2.5. 委派 file-ops 刷新缓存:
    cd /opt/data && ./skills/multi-agent-arch/skill-map-maintenance/scripts/rebuild-cache.py
    （直接 `./` 执行，禁止加 python3 前缀）
2.5.5. 运行校验器:
    cd /opt/data && ./scripts/validate-skill-map.py
    （直接 `./` 执行，禁止加 python3 前缀）
3. search_files 确认 skill-map.yaml 和 SOUL.md 中残留为 0
4. 汇报主 Agent：「已清理 xxx 的全部目录引用」
```

## 跨 Agent 引用处理

某些 Skill 出现在多个 Agent 节点下（如 `systematic-debugging` 在 programmer 和 error-analyst 均列出）。

- **安装**：分别在每个目标 Agent → categories → 对应分类 下追加条目
- **删除**：搜索 skill-map.yaml 中该 skill 名的全部出现位置 → 全部删除
- **Shared 区同步**：若该 Skill 在 shared 区也有条目，同步增删

### 跨 Agent 的 layer/load 差异标注

同一技能在不同 Agent 下可能有不同 layer/load（如 `ssh-172` 在 file-ops 是 L1 manual 按需工具，在 synology-helper 是 L2 auto 角色技能）。这种差异是**有意设计**，不是配置错误。

**规则**：当为同一技能在不同 Agent 下设定不同 layer/load 时，必须在每个条目追加 `intentional: true` 注释：

```yaml
- name: ssh-172
  layer: "1 / load: manual"
  intentional: true  # 在 file-ops 是按需工具，在 synology-helper 是角色技能
```

校验器会对未标注 `intentional: true` 的跨 Agent layer/load 差异发出 WARN。

## 四层判断速查

| 问题 | 答案→层级 |
|------|----------|
| 是不是系统自身管理的技能？ | 是 → L4 (元技能) |
| 是不是特定 Agent 工作必备？ | 是 → L2 (角色技能) |
| 是不是需要特定领域知识才能用？ | 是 → L3 (领域技能) |
| 是不是纯粹的工具封装？ | 是 → L1 (工具技能) |

## 常见陷阱

### YAML 冒号问题
`layer: 4 / load: auto` 会导致 YAML 解析错误（`mapping values are not allowed here`）。
**修复**：所有含冒号的 layer 值必须用双引号包裹：`layer: "4 / load: auto"`。

### 只更新 skill-map 忘记 SOUL.md
skill-map.yaml 更新后，**所有新技能**必须同步更新 SOUL.md 绑定表，不分层级。
**判定**：
- **auto 加载**（L2 auto / L4 auto）→ SOUL.md 目标 Agent 的 L2 auto 列追加技能名
- **manual 加载**（L1 manual / L3 manual）→ SOUL.md 目标 Agent 的 L3 manual 列追加技能名
**陷阱**：L1 manual 技能同样需要加入绑定表（归入 L3 manual 列），不要漏掉。校验器维度 7 对任何缺失条目发出 WARN，遗漏 L1 技能是常见错误根因。

### 误报跨 Agent 冲突
同一技能在多个 Agent 上出现但 **layer 和 load 完全相同**时（如 `hermes-agent-skill-authoring` 在 pm-agent 和 programmer 都是 L3/manual），这不是冲突，不需要 `intentional: true`。
- ✅ 需要标注：layer 或 load 不同 → `intentional: true`
- ❌ 不需要标注：layer 和 load 完全相同 → 无需额外标记
审计器维度 4 仅对 layer 不同的跨 Agent 引用发出 WARN，同层同载的不触发。

### 绕过 PM-agent 直接委派 file-ops

主 Agent 可能为省事直接委派 file-ops 写 skill-map.yaml，跳过 PM-agent。file-ops 只管物理写入，不知道还有缓存刷新、绑定表同步、校验器运行三个后续步骤。

**症状**：skill-map.yaml 更新成功，但 `.skill-cache.json` 过期、SOUL.md 绑定表脱节、validate-skill-map.py 报 WARN。

**预防**：所有 skill-map.yaml 修改必须走 PM-agent → skill-map-maintenance。主 Agent SOUL.md 委派路由表中「技能注册安装 → pm-agent」即为此约束。

### 跨 Agent 技能只删了一个节点
删除跨 Agent 技能时，必须 `search_files` 搜索全量确认所有节点都已删除。
**验证**：`grep -n "name: <skill>" /opt/data/skill-map.yaml` 返回空。

### Shared 区忘记同步
L1 级别工具技能在分配给 Agent 后，shared 区也应保留其条目（供其他 Agent 按需使用）。
**规则**：Agent 专属节点 + Shared 区各一条（除非确认只有该 Agent 会用）。

### 用户自建 Skill 无声明
用户用 skill_manage(action='create') 自建 Skill 时可能未填 layer/load/assign_to/category。
安装时 PM-agent 会自动分类，但仍应建议用户在 SKILL.md 中补上声明字段，方便后续维护。

### 缓存过期未察觉
`.skill-cache.json` 由本流程的安装/删除步骤自动刷新。若有人**绕过本流程**直接编辑 skill-map.yaml（如手动 vim），缓存会过期。
**症状**：SOUL.md 的缓存读取规则检测到 mtime 不一致 → 主 Agent 会降级读 YAML 并后台委派 file-ops 刷新。
**预防**：所有 skill-map.yaml 修改统一走本流程。

### 校验器未执行
安装/删除后必须运行 `/opt/data/scripts/validate-skill-map.py`。若跳过此步骤，YAML 缩进错误、残留引用等可能进入生产。
**症状**：后续委派时 skill-map.yaml 解析失败或子 Agent 收到不存在的 skill 引用。
**预防**：本流程步骤 6.5 和 2.5.5 已内建校验器调用，不跳过。

### 重建脚本输出格式不匹配
`rebuild-cache.py` 输出必须与 SOUL.md 期望格式一致：`{agents: {agent: {auto: [...], manual: [...]}}}`（含 cache_version, ttl_minutes, schema_version）。
**症状**：缓存重建后 validator 报所有 Agent 缺失、缓存缺少字段。
**预防**：修改 rebuild-cache.py 后运行 `/opt/data/scripts/validate-skill-map.py` 验证。

### Python 解释器缺失依赖
系统 `/usr/bin/python3` 无 pyyaml。所有脚本 shebang 必须为 `#!/usr/bin/env -S uv run python`。
**症状**：直接 `./script.py` 报 `ModuleNotFoundError: No module named 'yaml'`。
**预防**：新建 Python 脚本时检查 shebang，用 `./script.py` 直接执行验证。

### 批量注册时部分技能不存在
用户说"注册 N 个技能"时，必须**先全量验证技能存在性**再开始修改 skill-map.yaml。
**症状**：修改到一半发现某技能在 `/opt/data/skills/` 下不存在，进退两难。
**预防**：安装流程步骤 1 改为并发 `skill_view` 所有待注册技能，全部返回成功后再继续。若有缺失，立即上报主 Agent 列出缺失清单，不部分执行。

### 重建脚本或校验器不存在
`rebuild-cache.py` 和 `validate-skill-map.py` 是架构基础设施的一部分。若执行时发现脚本不存在，
说明这些组件尚未部署——此时**跳过对应步骤并明确汇报**「缓存刷新/校验器未部署，已跳过」，
不要静默绕过。
**症状**：search_files 返回空或执行报 No such file。
**后续**：上报主 Agent，架构补全由 `architecture-integrity-check` 审计后统一处理。

### 脚本执行连续失败（迭代杀手）

重建脚本或校验器执行失败时，PM-agent 容易陷入「换 python3 → 换 uv → 换路径 → 超时」的试探死循环。

**规则**：同一脚本连续失败 2 次 → 立即执行 `agent-environment.md` §3 **故障上报**规则——附带已尝试的方法、完整错误信息、建议的下一步，不得继续换参数试探。剩余迭代留给主 Agent 分配。

**注意**：脚本 shebang 已统一为 `#!/usr/bin/env -S uv run python`，直接用 `./script.py` 执行即可，不要加 `python3` 前缀。

| 重复验证上下文已指定的信息（PM-agent 迭代杀手） |

### 直接委派 file-ops 绕过 PM-agent

主 Agent 直接委派 file-ops 写 skill-map.yaml → 步骤 5.5/6/6.5（缓存刷新、绑定表同步、校验器）被跳过。

**症状**：skill-map.yaml 正确但 .skill-cache.json 过期、SOUL.md 绑定表缺条目、validate-skill-map.py 报 WARN。
**判定**：所有技能注册/安装/删除必须走「主 Agent → PM-agent → file-ops」链路。主 Agent 铁律#2 强制执行。
**预防**：主 Agent SOUL.md 铁律#2「多 Agent 必走 PM-agent」覆盖此场景。技能注册本质是多 Agent 协作（PM-agent 决策 + file-ops 执行 + 校验器审计）。

### 重复验证上下文已指定的信息（PM-agent 迭代杀手） |

委派 context 中已明确列出的信息（技能名列表、文件路径、Agent 归属、分类名），PM-agent **禁止重复验证**。

**症状**：10 次迭代中 5-8 次花在 `skill_view` `search_files` `read_file` 验证已知信息，0-2 次实际写入，耗尽 `max_iterations`。
**根因**：PM-agent 把「查 skill-map.yaml 确定 worker 技能」的习惯泛化到了所有任务——即使 context 已给完整列表，仍逐项验证。
**判定**：context 中已列出以下三类信息时，直接使用，禁止验证：

| 信息类型 | context 示例 | 禁止动作 |
|---------|-------------|---------|
| 技能名列表 | 「注册 superpowers、skill-creator…」 | 禁止逐个 `skill_view` |
| 文件路径 | 「/opt/data/scripts/validate-skill-map.py」 | 禁止 `search_files` 确认 |
| Agent 归属+分类 | 「pm-agent → 架构治理」 | 禁止重读 `skill-map.yaml` |

**例外**：context 未列出明确清单（如「把所有新技能注册了」）时，PM-agent 仍需自行探索。
**预防**：主 Agent 委派时在 context 中加一句「以下信息已验证，直接使用不重复验证」，触发本规则。

## 记忆同步

维护完成后，主 Agent memory 可能与实际状态不一致（技能总数、manual/auto 计数、缓存时间戳等）。PM-agent 须在汇报末尾附「记忆更新块」，供主 Agent 自动 diff 并更新。

**PM-agent 汇报格式——在报告末尾追加（key:value 或 JSON 均可）：**

Key:value 格式（推荐，纯文本易解析）：
```
[MEMORY_UPDATE]
skill_count: <当前 YAML 唯一技能数>
auto: <auto 技能数>
manual: <manual 技能数>
cache_updated: <ISO 时间戳>
cache_file: /opt/data/.skill-cache.json
skill_map_updated: <ISO 时间戳>
skill_map_file: /opt/data/skill-map.yaml
disk_skill_count: <磁盘实际 SKILL.md 数>
soul_binding_agents: <绑定表 Agent 数>
[/MEMORY_UPDATE]
```

JSON 格式（备选）：
```
[MEMORY_UPDATE]
{"key": "...", "data": {"skill_count": N, "auto": N, "manual": N, ...}}
[/MEMORY_UPDATE]
```

**主 Agent 收到后**：对比 `[MEMORY_UPDATE]` 区块中的数值与 memory 中已存数值，有差异即更新 memory（target=memory）。不依赖人工触发，自动化执行。

## 交付标准

- skill-map.yaml 中新增/删除条目正确，无 YAML 语法错误
- SOUL.md 绑定表同步更新（如适用）
- 运行 `/opt/data/scripts/validate-skill-map.py` 返回 OK（0 errors / 0 warnings）
- 向主 Agent 汇报变更摘要（Agent / 分类 / 层级 / 操作）
- **必须附带 `[MEMORY_UPDATE]` 区块**，否则视为未完成交付

## 校验器说明

`/opt/data/scripts/validate-skill-map.py` 执行 11 维全量审计：

| # | 维度 | 级别 |
|---|------|:---:|
| 1 | YAML 语法 | ERR |
| 2 | 引用技能存在性 | WARN |
| 3 | layer 格式 | ERR |
| 4 | 跨 Agent 冲突标注 | WARN |
| 5 | cache 一致性 | WARN |
| 6 | schema_version | WARN |
| 7 | SOUL.md 绑定表对齐 | WARN |
| 8 | Agent SOUL.md 存在性 | ERR |
| 9 | Registry 对齐 | WARN |
| 10 | 孤儿技能 | INFO |
| 11 | agent-environment.md 完整性 | WARN |

退出码：0=OK, 1=WARN, 2=ERR。INFO 不影响退出码。cron 每日 3am 自动巡检。

缓存降级模式详见 `references/cache-degradation-pattern.md`。
