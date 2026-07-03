"""
校验与冲突检测模块。

所有校验函数统一返回 ``(bool, str)`` 元组。

从原有 ``scripts/agent-mgmt/_validation.py`` 迁移，使用集中路径管理。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from hermes_mgmt.core.paths import (
    PROFILES_DIR,
    ROUTE_INDEX,
    ROUTES_DIR,
    SKILL_MAP,
)
from hermes_mgmt.core.yaml_ops import iter_skills


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
    data = _load_yaml(SKILL_MAP)
    names: set[str] = set()
    for _agent, _cat, skill in iter_skills(data):
        sn = skill.get("name")
        if isinstance(sn, str) and sn:
            names.add(sn)
    return names


def _get_profile_names() -> set[str]:
    """扫描 profiles/ 目录，返回所有 agent 目录名。"""
    if not PROFILES_DIR.is_dir():
        return set()
    return {d.name for d in PROFILES_DIR.iterdir() if d.is_dir()}


# ---------------------------------------------------------------------------
# 公共 API 函数
# ---------------------------------------------------------------------------


def check_agent_exist(name: str) -> tuple[bool, str]:
    """检查 agent 名是否已存在于 route-map/index.yaml、skill-map.yaml 或 profiles/ 中。

    Args:
        name: Agent 名称。

    Returns:
        (True, msg)  — agent 已存在。
        (False, msg) — agent 不存在。
    """
    locations: list[str] = []

    index_data = _load_yaml(ROUTE_INDEX)
    if name in index_data.get("agents", {}):
        locations.append("route-map/index.yaml")

    skill_data = _load_yaml(SKILL_MAP)
    if name in skill_data.get("agents", {}):
        locations.append("skill-map.yaml")

    if (PROFILES_DIR / name).is_dir():
        locations.append("profiles/")

    if locations:
        return True, f"agent「{name}」已存在于 {'、'.join(locations)}"
    return False, f"agent「{name}」在所有位置均未发现"


def check_skill_global_unique(skill_name: str) -> tuple[bool, str]:
    """检查 skill 名称在 skill-map.yaml 中是否全局唯一。

    Args:
        skill_name: 待检测的 skill 名称。

    Returns:
        (True, msg)  — 名称可用。
        (False, msg) — 名称已存在。
    """
    data = _load_yaml(SKILL_MAP)
    if not data:
        return False, "无法读取 skill-map.yaml"

    found_in: list[str] = []
    for agent_name, cat_name, skill in iter_skills(data):
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
    """检查 route-map/index.yaml 与 skill-map.yaml 的 schema_version 是否一致。"""
    index_data = _load_yaml(ROUTE_INDEX)
    skill_data = _load_yaml(SKILL_MAP)

    if not index_data:
        return False, f"无法读取 {ROUTE_INDEX}"
    if not skill_data:
        return False, f"无法读取 {SKILL_MAP}"

    index_ver = index_data.get("schema_version")
    skill_ver = skill_data.get("schema_version")

    if index_ver is None:
        return False, "route-map/index.yaml 缺少 schema_version"
    if skill_ver is None:
        return False, "skill-map.yaml 缺少 schema_version"

    if index_ver == skill_ver:
        return True, f"schema_version 一致: {index_ver}"
    return False, f"schema_version 不一致 — index.yaml: {index_ver}, skill-map.yaml: {skill_ver}"


def check_profiles_consistency() -> tuple[bool, str]:
    """检查 profiles/ 下每个 agent 的 config.yaml 与 skill-map.yaml 是否一致。"""
    issues: list[str] = []

    skill_data = _load_yaml(SKILL_MAP)
    skill_agents: set[str] = set()
    if skill_data:
        for k, v in skill_data.get("agents", {}).items():
            if isinstance(k, str) and isinstance(v, dict):
                skill_agents.add(k)

    profile_agents = _get_profile_names()

    for agent_name in sorted(profile_agents):
        config_path = PROFILES_DIR / agent_name / "config.yaml"
        if not config_path.is_file():
            issues.append(f"profiles/{agent_name}/ 缺少 config.yaml")

    for agent_name in sorted(profile_agents):
        if agent_name not in skill_agents:
            issues.append(
                f"agent「{agent_name}」在 profiles/ 中存在，"
                f"但 skill-map.yaml 中无对应条目"
            )

    for agent_name in sorted(skill_agents):
        if agent_name not in profile_agents:
            issues.append(
                f"agent「{agent_name}」在 skill-map.yaml 中存在，"
                f"但 profiles/ 中无对应目录"
            )

    if issues:
        return False, "一致性检查发现以下问题:\n  - " + "\n  - ".join(issues)
    return True, f"profiles/ 与 skill-map.yaml 完全一致（共 {len(profile_agents)} 个 agent）"


__all__ = [
    "check_agent_exist",
    "check_skill_global_unique",
    "check_file_exists",
    "check_schema_consistency",
    "check_profiles_consistency",
    "get_all_skill_names",
]
