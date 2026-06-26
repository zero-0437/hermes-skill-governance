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
   /opt/data/skills/multi-agent-arch/skill-map-maintenance/scripts/rebuild-cache.py
6. 委派 file-ops 同步更新 SOUL.md 绑定表（如果新增 L2 auto 或 L3 manual）
6.5. 运行校验器:
   /opt/data/scripts/validate-skill-map.py
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
   /opt/data/skills/multi-agent-arch/skill-map-maintenance/scripts/rebuild-cache.py
2.5.5. 运行校验器:
   /opt/data/scripts/validate-skill-map.py
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
skill-map.yaml 更新后，如果新技能是 L2 auto 或 L3 manual，必须同步更新 SOUL.md 绑定表。
**判定**：新增 L2 auto → SOUL.md 目标 Agent 的 L2 auto 列追加技能名。新增 L3 manual → L3 manual 列追加。

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
安装/删除后必须运行 `uv run python /opt/data/scripts/validate-skill-map.py`。若跳过此步骤，YAML 缩进错误、残留引用等可能进入生产。
**症状**：后续委派时 skill-map.yaml 解析失败或子 Agent 收到不存在的 skill 引用。
**预防**：本流程步骤 6.5 和 2.5.5 已内建校验器调用（`uv run python`），不跳过。

### 单次委派超限未分段

单次委派超过 10 个文件或 3 个步骤时，子 Agent 容易遗漏或超时。必须按拆分原则分段确认。

**规则**：单次委派 ≤10 文件或 ≤3 步。超限时分段委派，每段完成后确认再继续。

### /tmp 目录写入陷阱（write_file 被 Hermes 拦截）

Hermes 沙箱会拦截 `/tmp` 目录下的 `write_file`/`patch` 调用。在 `/tmp` 目录操作文件时，必须使用 terminal 命令（cat heredoc、sed 等）代替。

**症状**：`write_file` 返回成功但文件内容未改变。
**修复**：改为 `terminal: cat > /tmp/path/file << 'EOF'`。

### 推送前未加载 github-push 技能

推送到 GitHub 前必须先 `skill_view('github-push')` 加载专用推送流程，避免使用错误的认证方式或遗漏步骤。

**规则**：任何涉及 `git push` 的操作前，先 `skill_view('github-push')`。hermes-skill-governance 仓库使用专用 SSH key（`GIT_SSH_COMMAND='ssh -i /opt/data/home/.ssh/id_ed25519'`）。

### 用错 Python 二进制（python3 vs uv run python）
系统 `/usr/bin/python3` 无 pyyaml 模块，所有涉及 YAML 解析的脚本必须用 `uv run python`。
**症状**：`ModuleNotFoundError: No module named 'yaml'`。
**修复**：将命令从 `python3` 替换为 `uv run python`。
**影响脚本**：rebuild-cache.py、validate-skill-map.py、validate-skill-map-cron.sh 均已改用 `uv run python`。

## 交付标准

- skill-map.yaml 中新增/删除条目正确，无 YAML 语法错误
- SOUL.md 绑定表同步更新（如适用）
- 运行 `/opt/data/scripts/validate-skill-map.py` 返回 OK（0 errors / 0 warnings）
- 向主 Agent 汇报变更摘要（Agent / 分类 / 层级 / 操作）

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
