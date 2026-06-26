#!/usr/bin/env -S uv run python
"""skill-map 全量治理审计器 — 结构校验 + 跨文件一致性 + 孤儿检测

检查维度 (11 项):
  1. YAML 语法
  2. 引用技能存在性 (SKILL.md)
  3. layer 格式合法性
  4. 跨 Agent 冲突标注 (intentional)
  5. cache 结构 + 一致性
  6. schema_version
  7. SOUL.md 绑定表对齐
  8. Agent SOUL.md 存在性
  9. registry 对齐
 10. 孤儿技能检测 (INFO)
 11. agent-environment.md 完整性

严重级别: ERR(阻塞) > WARN(需关注) > INFO(信息)
退出码: 2=ERR, 1=WARN, 0=OK (INFO 不影响)
"""
import json, os, re, sys, yaml
from collections import defaultdict
from datetime import datetime, timezone

SKILL_MAP    = '/opt/data/skill-map.yaml'
CACHE        = '/opt/data/.skill-cache.json'
SKILLS_DIR   = '/opt/data/skills'
AGENTS_DIR   = '/opt/data/profiles'
SOUL_MD      = '/opt/data/SOUL.md'
REGISTRY     = '/opt/data/hermes-team-registry.md'
ENV_MD       = '/opt/data/contexts/agent-environment.md'

EXIT_OK, EXIT_WARN, EXIT_ERR = 0, 1, 2

errors   = []
warnings = []
infos    = []

def info(msg): infos.append(msg)
def warn(msg): warnings.append(msg)
def err(msg):  errors.append(msg)


# ═══════════ 1. YAML 语法 ═══════════
def check_yaml():
    try:
        with open(SKILL_MAP) as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        err(f"YAML 语法错误: {e}")
        return None
    except FileNotFoundError:
        err(f"文件不存在: {SKILL_MAP}")
        return None


# ═══════════ 2. Skill 存在性 ═══════════
def check_skill_exists(name, agent, category):
    for root, dirs, files in os.walk(SKILLS_DIR):
        if os.path.basename(root) == name and 'SKILL.md' in files:
            return True
    warn(f"[{agent}→{category}] '{name}' 未找到 SKILL.md")
    return False


# ═══════════ 3. layer 格式 ═══════════
VALID_LAYERS = {'1', '2', '3', '4'}
VALID_LOADS  = {'auto', 'manual'}

def check_layer(layer_str, name, agent):
    parts = layer_str.split('/')
    if len(parts) != 2:
        warn(f"[{agent}] {name} layer 格式异常: '{layer_str}'")
        return
    layer_num = parts[0].strip().split()[-1]
    load_val  = parts[1].strip().split()[-1]
    if layer_num not in VALID_LAYERS:
        err(f"[{agent}] {name} 非法 layer: '{layer_num}' (应为 1-4)")
    if load_val not in VALID_LOADS:
        err(f"[{agent}] {name} 非法 load: '{load_val}' (应为 auto|manual)")


# ═══════════ 4. 跨 Agent 冲突 ═══════════
def check_cross_agent(agents_data):
    skill_map = defaultdict(list)
    for agent_name, agent_data in agents_data.items():
        for cat_name, skills in agent_data.get('categories', {}).items():
            for s in skills:
                skill_map[s['name']].append({
                    'agent': agent_name,
                    'layer': s['layer'],
                    'intentional': s.get('intentional', False)
                })
    for name, instances in skill_map.items():
        if len(instances) <= 1:
            continue
        layers = set(i['layer'] for i in instances)
        if len(layers) > 1:
            if not all(i['intentional'] for i in instances):
                agents = ', '.join(f"{i['agent']}({i['layer']})" for i in instances)
                warn(f"跨 Agent 冲突未标注 intentional: {name} → {agents}")


# ═══════════ 5. cache 一致性 ═══════════
def check_cache(agents_data):
    if not os.path.exists(CACHE):
        warn("缓存文件不存在")
        return
    with open(CACHE) as f:
        cache = json.load(f)

    for field in ['cache_version', 'ttl_minutes']:
        if field not in cache:
            warn(f"缓存缺少 {field} 字段")

    yaml_agents = set(agents_data.keys())
    cache_agents = set(cache.get('agents', {}).keys())
    if missing := yaml_agents - cache_agents:
        warn(f"缓存缺失 Agent: {missing}")
    if extra := cache_agents - yaml_agents:
        warn(f"缓存多余 Agent: {extra}")

    for agent in yaml_agents & cache_agents:
        yaml_auto, yaml_manual = set(), set()
        for cat, skills in agents_data[agent].get('categories', {}).items():
            for s in skills:
                load = s['layer'].split('/')[-1].strip().split(':')[-1].strip()
                (yaml_auto if load == 'auto' else yaml_manual).add(s['name'])
        cache_auto   = set(cache['agents'][agent].get('auto', []))
        cache_manual = set(cache['agents'][agent].get('manual', []))
        if yaml_auto != cache_auto or yaml_manual != cache_manual:
            a_diff = yaml_auto ^ cache_auto
            m_diff = yaml_manual ^ cache_manual
            warn(f"[{agent}] 缓存不一致: auto={a_diff}, manual={m_diff}")


# ═══════════ 6. schema_version ═══════════
def check_schema(data):
    sv = data.get('schema_version', '')
    if sv != '2.0':
        warn(f"schema_version 期望 2.0，实际 {sv}")


# ═══════════ 7. SOUL.md 绑定表对齐 ═══════════
def check_binding_table(agents_data):
    if not os.path.exists(SOUL_MD):
        warn("SOUL.md 不存在")
        return
    with open(SOUL_MD) as f:
        soul = f.read()

    # 解析绑定表: | agent | auto_skills | manual_skills |
    soul_agents = {}
    in_table = False
    for line in soul.split('\n'):
        stripped = line.strip()
        if 'Agent | L2 auto' in stripped:
            in_table = True
            continue
        if not in_table:
            continue
        if stripped == '' or (stripped.startswith('##') and 'Skill' not in stripped):
            in_table = False
            continue
        if '---' in stripped:
            continue
        if not stripped.startswith('| '):
            continue
        cols = [c.strip() for c in stripped.split('|')[1:-1]]
        if len(cols) < 2:
            continue
        agent_name = cols[0].replace('`', '')
        # 跳过非 Agent 行（如 "context 注入规则"）
        if agent_name.startswith('**') or agent_name in ('', 'Agent') or not agent_name:
            continue
        auto_str   = cols[1] if len(cols) > 1 else ''
        manual_str = cols[2] if len(cols) > 2 else ''
        auto_skills   = {s.strip().replace('`','') for s in auto_str.split(',') if s.strip() and s.strip() != '—'}
        manual_skills = {s.strip().replace('`','') for s in manual_str.split(',') if s.strip() and s.strip() != '—'}
        soul_agents[agent_name] = (auto_skills, manual_skills)

    for agent in agents_data:
        if agent not in soul_agents:
            warn(f"绑定表缺失: {agent}")
            continue
        yaml_auto, yaml_manual = set(), set()
        for cat, skills in agents_data[agent].get('categories', {}).items():
            for s in skills:
                load = s['layer'].split('/')[-1].strip().split(':')[-1].strip()
                (yaml_auto if load == 'auto' else yaml_manual).add(s['name'])
        soul_auto, soul_manual = soul_agents[agent]
        if yaml_auto != soul_auto:
            warn(f"[{agent}] 绑定表 auto 不一致: YAML有但表缺={yaml_auto-soul_auto}, 表有但YAML缺={soul_auto-yaml_auto}")
        if yaml_manual != soul_manual:
            warn(f"[{agent}] 绑定表 manual 不一致: YAML有但表缺={yaml_manual-soul_manual}, 表有但YAML缺={soul_manual-yaml_manual}")


# ═══════════ 8. Agent SOUL.md 存在性 ═══════════
def check_agent_souls(agents_data):
    for agent in agents_data:
        soul = os.path.join(AGENTS_DIR, agent, 'SOUL.md')
        if not os.path.isfile(soul):
            err(f"Agent SOUL.md 缺失: {agent}")


# ═══════════ 9. Registry 对齐 ═══════════
def check_registry(agents_data):
    if not os.path.exists(REGISTRY):
        warn("registry 不存在")
        return
    with open(REGISTRY) as f:
        reg = f.read()
    yaml_agents = set(agents_data.keys())
    reg_agents = {a for a in yaml_agents if a in reg}
    missing = yaml_agents - reg_agents
    if missing:
        warn(f"Registry 中未找到: {missing}")


# ═══════════ 10. 孤儿技能 (INFO) ═══════════
def check_orphans(agents_data):
    # 收集所有已注册技能名
    registered = set()
    for agent, data in agents_data.items():
        for cat, skills in data.get('categories', {}).items():
            for s in skills:
                registered.add(s['name'])
    if 'shared' in data:
        for cat, skills in data.get('shared', {}).get('categories', {}).items():
            for s in skills:
                registered.add(s['name'])

    orphans = []
    for root, dirs, files in os.walk(SKILLS_DIR):
        if root == SKILLS_DIR:
            continue
        name = os.path.basename(root)
        if 'SKILL.md' in files and name not in registered and '/' not in root.replace(SKILLS_DIR+'/', '').rsplit('/', 2)[0]:
            # 仅统计直接子目录和二级子目录的技能
            rel = os.path.relpath(root, SKILLS_DIR)
            depth = rel.count(os.sep)
            if depth <= 2:
                orphans.append(name)

    if orphans:
        info(f"未注册的独立技能 ({len(orphans)} 个): {', '.join(sorted(orphans)[:10])}{'...' if len(orphans) > 10 else ''}")


# ═══════════ 11. agent-environment.md 完整性 ═══════════
def check_env_doc():
    if not os.path.exists(ENV_MD):
        warn("agent-environment.md 不存在")
        return
    with open(ENV_MD) as f:
        env = f.read()
    checks = ['.skill-cache.json', 'skill-map.yaml', 'TTL']
    for c in checks:
        if c.lower() not in env.lower():
            warn(f"agent-environment.md 未提及: {c}")


# ═══════════════════════════
# Main
# ═══════════════════════════

def main():
    data = check_yaml()
    if data is None:
        print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
        return EXIT_ERR

    check_schema(data)

    agents_data = data.get('agents', {})
    for agent, agent_data in agents_data.items():
        for cat, skills in agent_data.get('categories', {}).items():
            for s in skills:
                check_skill_exists(s['name'], agent, cat)
                check_layer(s['layer'], s['name'], agent)

    check_cross_agent(agents_data)
    check_cache(agents_data)
    check_binding_table(agents_data)
    check_agent_souls(agents_data)
    check_registry(agents_data)
    check_orphans(agents_data)
    check_env_doc()

    exit_code = EXIT_OK
    if errors:
        exit_code = EXIT_ERR
    elif warnings:
        exit_code = EXIT_WARN

    result = {
        "status": "OK" if exit_code == EXIT_OK else ("WARN" if exit_code == EXIT_WARN else "FAIL"),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "errors": len(errors),
        "warnings": len(warnings),
        "info": len(infos),
        "errors_list": errors,
        "warnings_list": warnings,
        "info_list": infos
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
