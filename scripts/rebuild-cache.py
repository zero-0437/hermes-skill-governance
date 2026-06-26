#!/usr/bin/env -S uv run python
"""从 skill-map.yaml 重建 /opt/data/.skill-cache.json。

输入: /opt/data/skill-map.yaml
输出: /opt/data/.skill-cache.json
格式: {schema_version, cache_version, ttl_minutes, last_updated, agents: {agent: {auto: [...], manual: [...]}}}
"""

import json, sys
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

agents = {}
for agent_name, data in tree.get("agents", {}).items():
    auto_skills = []
    manual_skills = []
    for cat_name, skills in data.get("categories", {}).items():
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
    agents[agent_name] = {"auto": auto_skills, "manual": manual_skills}

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
