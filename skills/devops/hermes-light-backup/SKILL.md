---
name: hermes-light-backup
description: 轻量备份——将所有 SOUL.md、全局治理文件和目录树技能文件打包上传到群晖 NAS。仅备份治理/配置类文本文件，不含项目代码或二进制文件。
version: 1.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [backup, nas, governance, soul, skill-map]
    related_skills: [ssh-172, architecture-backup]
---

# Hermes 轻量备份

## 概述

备份治理文件到 NAS `/volume1/backup/hermes-light/`，文件名格式 `light-backup-YYYYMMDD_HHMMSS.tar.gz`。

与 `architecture-backup`（全量架构备份）不同，本技能仅备份轻量的文本治理文件，不含项目代码、日志、数据库等大文件。

## 备份范围

| 分类 | 路径（tar 递归） |
|------|------|
| SOUL.md | `SOUL.md` + `profiles/*/SOUL.md` |
| 全局治理 | `hermes-team-registry.md` `agent-environment.md` `skill-map.yaml` `.skill-cache.json` |
| 目录树技能 | `projects/directory-tree/` `skills/multi-agent-arch/skill-map-maintenance/` `skills/software-development/delegation-multi-agent/` `skills/devops/github-push/` `scripts/validate-skill-map.py` `scripts/rebuild-cache.py` |

## 使用方式

```bash
# 1. 本地打包
TS=$(date +%Y%m%d_%H%M%S)
cd /opt/data
tar czf /tmp/light-backup-$TS.tar.gz \
  SOUL.md \
  profiles/*/SOUL.md \
  hermes-team-registry.md \
  contexts/agent-environment.md \
  skill-map.yaml \
  .skill-cache.json \
  projects/directory-tree/ \
  skills/multi-agent-arch/skill-map-maintenance/ \
  skills/software-development/delegation-multi-agent/ \
  skills/devops/github-push/ \
  scripts/validate-skill-map.py \
  scripts/rebuild-cache.py

# 2. 上传到 NAS
B64=$(base64 -w0 /tmp/light-backup-$TS.tar.gz)
SSHPASS='Hy199098' python3 /opt/data/ssh_helper.py 192.168.1.172 zero0437 \
  "echo '$B64' | base64 -d > /volume1/backup/hermes-light/light-backup-$TS.tar.gz"

# 3. 验证
SSHPASS='Hy199098' python3 /opt/data/ssh_helper.py 192.168.1.172 zero0437 \
  "ls -la /volume1/backup/hermes-light/ && tar tzf /volume1/backup/hermes-light/light-backup-$TS.tar.gz | grep -v '/\$'"
# 预期输出：列出 tar 内文件清单，人工确认无遗漏

# 4. 清理旧备份（保留最近 10 份）
SSHPASS='Hy199098' python3 /opt/data/ssh_helper.py 192.168.1.172 zero0437 \
  "cd /volume1/backup/hermes-light && ls -1t light-backup-*.tar.gz | tail -n +11 | xargs -r rm -f"
```

## 目录创建（仅首次）

如果 NAS 上目标目录不存在：

```bash
SSHPASS='Hy199098' python3 /opt/data/ssh_helper.py 192.168.1.172 zero0437 \
  "mkdir -p /volume1/backup/hermes-light"
```

## 恢复

```bash
SSHPASS='Hy199098' python3 /opt/data/ssh_helper.py 192.168.1.172 zero0437 \
  "tar xzf /volume1/backup/hermes-light/light-backup-YYYYMMDD_HHMMSS.tar.gz -C /volume1/backup/hermes-light/"
```

## 常见陷阱

1. **路径修正**：NAS 上路径是 `/volume1/backup/` 不是 `/volume1/backups/`。zero0437 用户可能无权限在 `/volume1/` 下创建新目录。
2. **SSH 模板**：必须使用 `SSHPASS='Hy199098' python3 /opt/data/ssh_helper.py 192.168.1.172 zero0437 "命令"`，不能用 `ssh` 直连（会被 fail2ban）。
3. **NAS 是 sh**：不支持 `source`，用 `. .env` 替代。PTY 输出含 `\r` 需 `tr -d` 处理。
4. **base64 单行**：`-w0` 确保不换行，否则 echo 会截断。
