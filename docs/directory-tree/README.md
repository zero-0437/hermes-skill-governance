# 目录树 — 多 Agent 技能治理系统

> **阅读难度**: ⭐☆☆☆☆ (入门)  
> **目标读者**: 首次接触项目的新成员、想快速跑通验证的工程师

## 这是什么

**目录树**是一个多 Agent 技能治理系统，为 12 个专业子 Agent 分配技能、校验一致性、管理生命周期。核心机制是「**一张注册表 + 两个脚本**」的极简治理模式：

1. **`skill-map.yaml`** — 中心注册表，声明每个 Agent 拥有哪些技能（L2 自动加载 / L3 按需加载）
2. **`rebuild-cache.py`** — 从注册表重建运行时缓存，生成 `.skill-cache.json` 和各 Agent 的 `allowed-skills.md`
3. **`validate-skill-map.py`** — 11 维度校验器，确保注册表、运行时缓存、Agent 配置文件三端对齐

## 为什么需要

在多 Agent 系统中，无治理会迅速失控：

| 问题 | 无治理时的后果 |
|------|-------------|
| **技能幽灵** | 某个技能改参数后，10 个 Agent 仍用旧签名 |
| **权限泄露** | programmer 意外获得 rm-rf 权限 |
| **缓存过期** | 主 Agent 委派决策基于一周前的技能列表 |
| **配置漂移** | SOUL.md、config.yaml、skill-map 三者不一致 |

目录树通过 **单一真相源 + 自动缓存重建 + 全量校验** 三件套，把上述问题发生率降到零。

## 快速开始（30 秒跑通）

```bash
cd /opt/data

# 步骤 1：从 skill-map.yaml 重建所有缓存
uv run python scripts/rebuild-cache.py

# 步骤 2：全量校验（11 个维度）
uv run python scripts/validate-skill-map.py

# 步骤 3：查看校验结果（退出码 0=OK, 1=WARN, 2=ERR）
echo $?
```

**预期输出**：
- `rebuild-cache.py` 打印 `缓存已刷新: .skill-cache.json (12 个 Agent...)` + 每个 Agent 的技能清单生成状态
- `validate-skill-map.py` 输出 JSON 格式的校验报告，包含 `status`、`errors`、`warnings`、`info` 计数

## 关键文件速查

| 文件 | 用途 | 谁修改 |
|------|------|--------|
| `skill-map.yaml` | 技能注册表（单一真相源） | pm-agent |
| `scripts/rebuild-cache.py` | 缓存重建脚本 | pm-agent |
| `scripts/validate-skill-map.py` | 治理校验器 | pm-agent |
| `.skill-cache.json` | 运行时缓存（TTL 30 分钟） | 脚本自动生成 |
| `SOUL.md` | 主 Agent 总控规则 + 绑定表 | pm-agent |
| `contexts/agent-environment.md` | 子 Agent 委派规范 | pm-agent |
| `profiles/<agent>/SOUL.md` | 各子 Agent 的角色定义 | 各 Agent 自行维护 |
| `profiles/<agent>/allowed-skills.md` | 各子 Agent 的技能清单 | 脚本自动生成 |

## 下一步

- 想了解设计原理 → 阅读 [architecture.md](./architecture.md)
- 想查字段定义或命令参数 → 阅读 [reference.md](./reference.md)
- 想了解 12 个 Agent 的分工 → 阅读 [agent-guide.md](./agent-guide.md)
