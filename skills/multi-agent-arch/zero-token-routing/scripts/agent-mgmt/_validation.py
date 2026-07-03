"""
校验与冲突检测模块。

所有校验函数统一返回 ``(bool, str)`` 元组：
  ``True``  — 校验通过（或存在）
  ``False`` — 校验失败（或不存在）
第二元素为中文错误/提示信息。

约束：仅使用标准库 ``yaml`` 和 ``os.path``／``pathlib``。
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

# 共享辅助函数（_yaml_ops 只有 ruamel.yaml 依赖，不影响本模块纯度）
from _yaml_ops import _iter_skills


# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------

# scripts/agent-mgmt/  → 项目根目录
_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent

_ROUTE_INDEX: Path = _PROJECT_ROOT / "route-map" / "index.yaml"
_SKILL_MAP: Path = _PROJECT_ROOT / "skill-map.yaml"
_PROFILES_DIR: Path = _PROJECT_ROOT / "profiles"
_ROUTES_DIR: Path = _PROJECT_ROOT / "route-map" / "routes"


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict:
    """安全加载 YAML 文件，失败时返回空 dict。"""
    if not path.is_file():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def get_all_skill_names() -> set[str]:
    """从 skill-map.yaml 收集所有 skill 名称（含 shared 区）。"""
    data = _load_yaml(_SKILL_MAP)
    names: set[str] = set()
    for _agent, _cat, skill in _iter_skills(data):
        sn = skill.get("name")
        if isinstance(sn, str) and sn:
            names.add(sn)
    return names


def _get_profile_names() -> set[str]:
    """扫描 profiles/ 目录，返回所有 agent 目录名。"""
    if not _PROFILES_DIR.is_dir():
        return set()
    return {d.name for d in _PROFILES_DIR.iterdir() if d.is_dir()}


# ---------------------------------------------------------------------------
# 公共 API 函数
# ---------------------------------------------------------------------------


def check_agent_exist(name: str) -> tuple[bool, str]:
    """检查 agent 名是否已存在于 route-map/index.yaml、skill-map.yaml 或 profiles/ 中。

    任一位置存在即视为已存在（用于新建 agent 前的冲突检测）。

    Args:
        name: Agent 名称。

    Returns:
        (True, msg)  — agent 已存在（含位置说明）。
        (False, msg) — agent 不存在。
    """
    locations: list[str] = []

    # 1) route-map/index.yaml
    index_data = _load_yaml(_ROUTE_INDEX)
    if name in index_data.get("agents", {}):
        locations.append("route-map/index.yaml")

    # 2) skill-map.yaml
    skill_data = _load_yaml(_SKILL_MAP)
    if name in skill_data.get("agents", {}):
        locations.append("skill-map.yaml")

    # 3) profiles/ 目录
    if (_PROFILES_DIR / name).is_dir():
        locations.append("profiles/")

    if locations:
        return True, f"agent「{name}」已存在于 {'、'.join(locations)}"
    return False, f"agent「{name}」在所有位置均未发现"


def check_skill_global_unique(skill_name: str) -> tuple[bool, str]:
    """检查 skill 名称在 skill-map.yaml 中是否全局唯一。

    扫描 skill-map.yaml 中所有 agent（含 shared 区）下的 skill 名称。
    适用于新建 skill 前的重名检测。

    Args:
        skill_name: 待检测的 skill 名称。

    Returns:
        (True, msg)  — 名称可用，未发现重复。
        (False, msg) — 名称已存在（含所在 agent/类别信息）。
    """
    data = _load_yaml(_SKILL_MAP)
    if not data:
        return False, "无法读取 skill-map.yaml"

    found_in: list[str] = []

    for agent_name, cat_name, skill in _iter_skills(data):
        if skill.get("name") == skill_name:
            found_in.append(f"{agent_name} > {cat_name}")

    if found_in:
        return False, f"skill「{skill_name}」已存在于 {'、'.join(found_in)}"
    return True, f"skill「{skill_name}」名称可用，未发现重复"


def check_file_exists(path: str) -> tuple[bool, str]:
    """检查路径是否存在（文件或目录均可）。

    Args:
        path: 文件或目录路径。

    Returns:
        (True, msg)  — 路径存在。
        (False, msg) — 路径不存在。
    """
    p = Path(path)
    if p.exists():
        return True, f"路径存在: {p.resolve()}"
    return False, f"路径不存在: {path}"


def check_schema_consistency() -> tuple[bool, str]:
    """检查 route-map/index.yaml 与 skill-map.yaml 的 schema_version 是否一致。

    Returns:
        (True, msg)  — 版本一致。
        (False, msg) — 版本不一致或读取失败。
    """
    index_data = _load_yaml(_ROUTE_INDEX)
    skill_data = _load_yaml(_SKILL_MAP)

    if not index_data:
        return False, f"无法读取 {_ROUTE_INDEX}"
    if not skill_data:
        return False, f"无法读取 {_SKILL_MAP}"

    index_ver = index_data.get("schema_version")
    skill_ver = skill_data.get("schema_version")

    if index_ver is None:
        return False, "route-map/index.yaml 缺少 schema_version"
    if skill_ver is None:
        return False, "skill-map.yaml 缺少 schema_version"

    if index_ver == skill_ver:
        return True, f"schema_version 一致: {index_ver}"
    return False, f"schema_version 不一致 — index.yaml: {index_ver}, skill-map.yaml: {skill_ver}"


def check_route_skills_exist(route_file: str) -> tuple[bool, str]:
    """检查 route 文件中引用的 skills 是否在 skill-map.yaml 中存在。

    遍历 route 文件中所有规则的 ``skills`` 列表，逐一核对
    skill-map.yaml 中的所有 skill 名称（含 shared 区）。

    Args:
        route_file: route 文件路径（相对项目根目录或绝对路径均可）。

    Returns:
        (True, msg)  — 所有引用的 skill 均存在。
        (False, msg) — 存在缺失的 skill（列出具体名称）。
    """
    # 解析 route 文件路径
    rpath = Path(route_file)
    if not rpath.is_absolute():
        rpath = _PROJECT_ROOT / rpath

    if not rpath.is_file():
        return False, f"route 文件不存在: {rpath}"

    route_data = _load_yaml(rpath)
    if not route_data:
        return False, f"无法读取 route 文件: {rpath}"

    # 收集 route 中所有 rules 引用的 skill 名称
    referenced_skills: set[str] = set()
    rules = route_data.get("rules", [])
    if isinstance(rules, list):
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            skills_list = rule.get("skills", [])
            if isinstance(skills_list, list):
                for sk in skills_list:
                    if isinstance(sk, str) and sk.strip():
                        referenced_skills.add(sk.strip())

    if not referenced_skills:
        return True, "route 文件中未引用任何 skill（或引用为空）"

    # 获取 skill-map 中所有 skill 名称
    all_skills = get_all_skill_names()

    missing = referenced_skills - all_skills
    if missing:
        return False, f"route 文件引用了不存在的 skill: {', '.join(sorted(missing))}"
    return True, f"route 文件引用的 {len(referenced_skills)} 个 skill 均在 skill-map.yaml 中存在"


def check_profiles_consistency() -> tuple[bool, str]:
    """检查 profiles/ 下每个 agent 的 config.yaml 与 skill-map.yaml 是否一致。

    一致性规则:
      1. profiles/ 下每个 agent 目录都应包含 ``config.yaml``。
      2. profiles/ 下每个 agent 都应在 skill-map.yaml 中有对应条目。
      3. skill-map.yaml 中的每个 agent 都应在 profiles/ 中有对应目录。

    Returns:
        (True, msg)  — 完全一致。
        (False, msg) — 存在不一致项（逐条列出）。
    """
    issues: list[str] = []

    # 读取 skill-map 中的 agent 列表
    skill_data = _load_yaml(_SKILL_MAP)
    skill_agents: set[str] = set()
    if skill_data:
        for k, v in skill_data.get("agents", {}).items():
            if isinstance(k, str) and isinstance(v, dict):
                skill_agents.add(k)

    # 读取 profiles/ 中的 agent 目录列表
    profile_agents = _get_profile_names()

    # 检查 profiles/ 下每个 agent 是否有 config.yaml
    for agent_name in sorted(profile_agents):
        config_path = _PROFILES_DIR / agent_name / "config.yaml"
        if not config_path.is_file():
            issues.append(f"profiles/{agent_name}/ 缺少 config.yaml")

    # 检查 profiles/ 下的 agent 是否在 skill-map.yaml 中
    for agent_name in sorted(profile_agents):
        if agent_name not in skill_agents:
            issues.append(
                f"agent「{agent_name}」在 profiles/ 中存在，"
                f"但 skill-map.yaml 中无对应条目"
            )

    # 检查 skill-map.yaml 中的 agent 是否在 profiles/ 中
    for agent_name in sorted(skill_agents):
        if agent_name not in profile_agents:
            issues.append(
                f"agent「{agent_name}」在 skill-map.yaml 中存在，"
                f"但 profiles/ 中无对应目录"
            )

    if issues:
        return False, "一致性检查发现以下问题:\n  - " + "\n  - ".join(issues)
    return True, f"profiles/ 与 skill-map.yaml 完全一致（共 {len(profile_agents)} 个 agent）"


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    "check_agent_exist",
    "check_skill_global_unique",
    "check_file_exists",
    "check_schema_consistency",
    "check_route_skills_exist",
    "check_profiles_consistency",
    "get_all_skill_names",
]
