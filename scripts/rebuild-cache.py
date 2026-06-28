#!/usr/bin/env -S uv run python
"""从 skill-map.yaml 重建缓存 + 子 Agent 技能清单。

输入: /opt/data/skill-map.yaml
输出:
  1. /opt/data/.skill-cache.json          — 主 Agent 委派决策用
  2. /opt/data/profiles/<agent>/allowed-skills.md  — 子 Agent 自检用
格式: {schema_version, cache_version, ttl_minutes, last_updated, agents: {agent: {auto: [...], manual: [...]}}}
"""

import json, os, sys
from datetime import datetime, timezone

try:
    import yaml
except ImportError:
    print("FATAL: PyYAML 未安装。请执行: uv pip install pyyaml", file=sys.stderr)
    sys.exit(1)

SKILL_MAP = "/opt/data/skill-map.yaml"
CACHE_FILE = "/opt/data/.skill-cache.json"

try:
    with open(SKILL_MAP) as f:
        tree = yaml.safe_load(f)
except FileNotFoundError:
    print(f"FATAL: {SKILL_MAP} 不存在", file=sys.stderr)
    sys.exit(1)
except yaml.YAMLError as e:
    print(f"FATAL: YAML 解析失败: {e}", file=sys.stderr)
    sys.exit(1)

def parse_skills(categories):
    """从 categories 字典中提取 auto/manual 技能名列表"""
    auto_skills = []
    manual_skills = []
    for cat_name, skills in categories.items():
        for s in skills:
            layer_str = s.get("layer", "")
            # 解析 "4 / load: auto" 或 "3 / load: manual"
            parts = layer_str.split("/")
            if len(parts) == 2:
                load_part = parts[1].strip()  # "load: auto"
                load_val = load_part.split(":")[-1].strip()
                if load_val == "auto":
                    auto_skills.append(s["name"])
                elif load_val == "manual":
                    manual_skills.append(s["name"])
    return auto_skills, manual_skills

# ── 提取 shared 全局技能（L1 manual）──
shared_cats = tree.get("shared", {}).get("categories", {})
shared_auto, shared_manual = parse_skills(shared_cats)
# shared 下都是 L1 manual，但用 parse_skills 统一处理以防未来有 auto

agents = {}        # 含 shared → 写入 .skill-cache.json
agent_only = {}    # 仅自身 → 写入 allowed-skills.md

for agent_name, data in tree.get("agents", {}).items():
    auto_skills, manual_skills = parse_skills(data.get("categories", {}))
    # 仅自身技能（不含 shared）→ 子 Agent 清单
    agent_only[agent_name] = {"auto": list(auto_skills), "manual": list(manual_skills)}
    # 合并 shared 全局技能 → 主 Agent 缓存
    for name in shared_manual:
        if name not in manual_skills and name not in auto_skills:
            manual_skills.append(name)
    role_desc = data.get("description", "")
    agents[agent_name] = {"role": role_desc, "auto": auto_skills, "manual": manual_skills}

cache = {
    "schema_version": tree.get("schema_version", "2.0"),
    "cache_version": 1,
    "ttl_minutes": 30,
    "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "agents": agents
}

with open(CACHE_FILE, "w") as f:
    json.dump(cache, f, ensure_ascii=False, indent=2)

print(f"缓存已刷新: {CACHE_FILE} ({len(agents)} 个 Agent, auto={sum(len(v['auto']) for v in agents.values())}, manual={sum(len(v['manual']) for v in agents.values())})")

# ═══════════════════════════════════════════
# 2. 生成子 Agent 技能清单
# ═══════════════════════════════════════════
PROFILES_DIR = "/opt/data/profiles"
CHANGED = []

for agent_name, skills in agent_only.items():
    profile_dir = os.path.join(PROFILES_DIR, agent_name)
    if not os.path.isdir(profile_dir):
        print(f"  跳过（无 profile 目录）: {agent_name}")
        continue

    auto_list = '\n'.join(f'- `{s}`' for s in skills['auto']) or '- _(无)_'
    manual_list = '\n'.join(f'- `{s}`' for s in skills['manual']) or '- _(无)_'

    content = f"""# {agent_name} 可用技能清单
> 来源: skill-map.yaml | 生成: {datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
> 自动生成，勿手动编辑

## L2 auto（委派时自动加载，无需手动指定）
{auto_list}

## L3 manual（委派 context 中显式指定后可用）
{manual_list}
"""
    filepath = os.path.join(profile_dir, 'allowed-skills.md')
    with open(filepath, 'w') as f:
        f.write(content)
    auto_n = len(skills['auto'])
    manual_n = len(skills['manual'])
    CHANGED.append(f"  {agent_name}: L2={auto_n} L3={manual_n}")

print(f"技能清单已生成: {len(CHANGED)} 个 Agent 的 allowed-skills.md")
for line in CHANGED:
    print(line)
