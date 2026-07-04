#!/usr/bin/env python3
"""validate-route-map.py — route-map 目录结构验证器（12 维审计）
与 validate-skill-map.py 对齐：退出码 0=OK, 1=WARN, 2=ERR
"""
import json, os, re, sys, yaml

ROUTE_MAP_DIR = os.path.join(os.path.dirname(__file__), "..", "route-map")
SKILL_MAP = os.path.join(os.path.dirname(__file__), "..", "skill-map.yaml")
INDEX_FILE = os.path.join(ROUTE_MAP_DIR, "index.yaml")
ROUTES_DIR = os.path.join(ROUTE_MAP_DIR, "routes")


def err(msg, field=""):
    return {"field": field, "message": msg}


def warn(msg, field=""):
    return {"field": field, "message": msg}


def info(msg, field=""):
    return {"field": field, "message": msg}


def validate():
    errors = []
    warnings = []
    infos = []

    # 1. index.yaml YAML 合法性
    if not os.path.exists(INDEX_FILE):
        errors.append(err("index.yaml 不存在", "index.yaml"))
    else:
        try:
            with open(INDEX_FILE) as f:
                index = yaml.safe_load(f)
            if not isinstance(index, dict):
                errors.append(err("index.yaml 不是有效 dict", "index.yaml"))
        except yaml.YAMLError as e:
            errors.append(err(f"index.yaml YAML 语法错误: {e}", "index.yaml"))

    # 2. 每个 routes/*.yaml YAML 合法性
    agents_map = index.get("agents", {})
    route_files = {}
    for fname in os.listdir(ROUTES_DIR):
        if fname.endswith(".yaml"):
            fpath = os.path.join(ROUTES_DIR, fname)
            try:
                with open(fpath) as f:
                    data = yaml.safe_load(f)
                if not isinstance(data, dict):
                    errors.append(err(f"{fname} 不是有效 dict", fname))
                route_files[fname] = data
            except yaml.YAMLError as e:
                errors.append(err(f"{fname} YAML 语法错误: {e}", fname))

    # 3. agents 映射完整性
    expected_agents = {"pm-agent", "programmer", "error-analyst", "data-analyst",
                       "ui-designer", "document-processor", "file-ops",
                       "synology-helper", "memory-agent", "prompt-engineer",
                       "reality-checker", "docs-writer"}
    indexed_agents = set(agents_map.keys())
    missing = expected_agents - indexed_agents
    extra = indexed_agents - expected_agents
    if missing:
        errors.append(err(f"index.yaml 缺少 Agent: {missing}", "agents"))
    if extra:
        warnings.append(warn(f"index.yaml 有未预期的 Agent: {extra}", "agents"))

    # 4. 交叉验证：index.yaml 引用的 file 路径必须存在
    for name, info in agents_map.items():
        fpath = os.path.join(ROUTES_DIR, info.get("file", "").replace("routes/", ""))
        if not os.path.exists(fpath):
            errors.append(err(f"Agent '{name}' 引用的文件不存在: {info.get('file')}", name))
        elif "file" not in info:
            errors.append(err(f"Agent '{name}' 缺少 file 字段", name))

    # 5. 逆向检查：routes/ 下每个 .yaml 必须在 index.yaml agents 中有对应
    indexed_files = {info.get("file", "").replace("routes/", "") for info in agents_map.values()}
    for fname in route_files:
        if fname not in indexed_files and fname != "shared.yaml":
            warnings.append(warn(f"routes/{fname} 在 index.yaml 中无对应 agent", fname))

    # 6. schema_version 一致性
    try:
        with open(SKILL_MAP) as f:
            skill_map = yaml.safe_load(f)
        sv_index = index.get("schema_version")
        sv_skill = skill_map.get("schema_version")
        if sv_index and sv_skill and sv_index != sv_skill:
            errors.append(err(
                f"schema_version 不一致: index.yaml={sv_index}, skill-map.yaml={sv_skill}",
                "schema_version"))
    except (yaml.YAMLError, FileNotFoundError):
        warnings.append(warn("无法读取 skill-map.yaml，跳过 schema_version 检查"))

    # 7. rules[] 结构完整性
    for fname, data in route_files.items():
        if fname == "shared.yaml":
            continue
        rules = data.get("rules", [])
        if not isinstance(rules, list):
            errors.append(err(f"{fname}: rules 不是数组", fname))
            continue
        for i, rule in enumerate(rules):
            for field in ("type", "pattern", "weight"):
                if field not in rule:
                    errors.append(err(f"{fname} rule[{i}]: 缺少 '{field}'", fname))

    # 8. regex pattern 语法检查
    for fname, data in route_files.items():
        if fname == "shared.yaml":
            continue
        for i, rule in enumerate(data.get("rules", [])):
            if rule.get("type") == "regex":
                try:
                    re.compile(rule["pattern"])
                except re.error as e:
                    errors.append(err(f"{fname} rule[{i}] regex 语法错误: {e}", fname))

    # 9. 每个 Agent 至少 2 条正权重规则
    for fname, data in route_files.items():
        if fname == "shared.yaml":
            continue
        agent_name = data.get("agent", fname.replace(".yaml", ""))
        pos_rules = [r for r in data.get("rules", []) if r.get("weight", 0) > 0]
        if len(pos_rules) < 2:
            errors.append(err(f"Agent '{agent_name}' 正权重规则不足 ({len(pos_rules)} < 2)", agent_name))

    # 10. weight 范围检查（允许负权重用于误匹配防护，须在 -2.0~2.0 之间）
    for fname, data in route_files.items():
        if fname == "shared.yaml":
            continue
        for i, rule in enumerate(data.get("rules", [])):
            w = rule.get("weight", 0)
            if not isinstance(w, (int, float)):
                errors.append(err(f"{fname} rule[{i}] weight 不是数字: {w}", fname))
            elif w < -2.0 or w > 2.0:
                errors.append(err(f"{fname} rule[{i}] weight 越界: {w} (允许 -2.0~2.0)", fname))

    # 11. agent 名一致性
    for fname, data in route_files.items():
        if fname == "shared.yaml":
            continue
        expected_name = fname.replace(".yaml", "")
        actual_name = data.get("agent", "")
        if actual_name and actual_name != expected_name:
            errors.append(err(
                f"{fname}: agent 名 '{actual_name}' 与文件名 '{expected_name}' 不一致",
                fname))

    # 12. 重复规则检测
    for fname, data in route_files.items():
        if fname == "shared.yaml":
            continue
        seen = {}
        for i, rule in enumerate(data.get("rules", [])):
            key = (rule.get("type", ""), rule.get("pattern", ""))
            if key in seen:
                warnings.append(warn(
                    f"{fname}: rule[{i}] 与 rule[{seen[key]}] 重复 (type={key[0]}, pattern={key[1]})",
                    fname))
            seen[key] = i

    # 判定状态
    if errors:
        status = "ERR"
    elif warnings:
        status = "WARN"
    else:
        status = "OK"

    return {"status": status, "errors": errors, "warnings": warnings, "info": infos}


def main():
    result = validate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] == "ERR":
        return 2
    elif result["status"] == "WARN":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
