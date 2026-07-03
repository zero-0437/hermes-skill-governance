"""
SOUL.md 绑定表操作模块 — 基于 str/re 解析 Markdown 表格。

从原有 ``scripts/agent-mgmt/_binding_table.py`` 迁移。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, List, Tuple

from hermes_mgmt.core.yaml_ops import read_yaml

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_HEADER_MARKER = "| Agent |"
_EMPTY_SKILL_PLACEHOLDER = "—"
_LAYER_PATTERN = re.compile(
    r"^\s*(?P<layer>\d+)\s*/\s*load\s*:\s*(?P<load>auto|manual)\s*$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


def _parse_skill_list(cell_text: str) -> list[str]:
    """解析表格单元格中的技能名称列表。"""
    text = cell_text.strip()
    if not text or text == _EMPTY_SKILL_PLACEHOLDER or text == "-":
        return []
    return [s.strip() for s in text.split(",") if s.strip()]


def _is_table_separator_line(stripped: str) -> bool:
    """判断 Markdown 表格分隔行。"""
    core = stripped.strip("|").strip()
    return bool(core) and all(ch in ("-", "|", " ", ":") for ch in core)


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------


def parse_binding_table(soul_md_content: str) -> dict[str, dict[str, Any]]:
    """从 SOUL.md Markdown 内容中解析 Agent→Skill 绑定表。

    Args:
        soul_md_content: SOUL.md 的完整文本内容。

    Returns:
        形如 ``{agent_name: {"l2": [...], "l3": [...], "condition": str}, ...}``
    """
    result: dict[str, dict[str, Any]] = {}
    lines = soul_md_content.split("\n")

    header_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(_HEADER_MARKER):
            header_idx = i
            break

    if header_idx < 0:
        return result

    data_start = header_idx + 2
    if data_start >= len(lines):
        return result

    for line in lines[data_start:]:
        stripped = line.strip()

        if not stripped or not stripped.startswith("|"):
            break
        if _is_table_separator_line(stripped):
            continue
        if not stripped.startswith("| "):
            break

        content = stripped.strip("|").strip()
        cells = [c.strip() for c in content.split("|")]
        if len(cells) < 4:
            continue

        agent_name = cells[0].strip("`").strip()
        if not agent_name:
            continue

        l2 = _parse_skill_list(cells[1])
        l3 = _parse_skill_list(cells[2])
        condition = "|".join(cells[3:]).strip()

        result[agent_name] = {
            "l2": l2,
            "l3": l3,
            "condition": condition,
        }

    return result


def add_binding_row(
    agent_name: str,
    l2_skills: list[str],
    l3_skills: list[str],
    condition: str,
) -> str:
    """生成一条符合 SOUL.md 绑定表格式的 Markdown 表格行。

    Args:
        agent_name: Agent 名称。
        l2_skills:  L2 auto 技能名称列表。
        l3_skills:  L3 manual 技能名称列表。
        condition:  触发条件文本。

    Returns:
        以 ``\\n`` 结尾的 Markdown 表格行字符串。
    """
    l2_str = ", ".join(l2_skills) if l2_skills else _EMPTY_SKILL_PLACEHOLDER
    l3_str = ", ".join(l3_skills) if l3_skills else _EMPTY_SKILL_PLACEHOLDER
    return f"| `{agent_name}` | {l2_str} | {l3_str} | {condition} |\n"


def get_auto_manual_from_skill_map(
    agent_name: str,
    skill_map_path: str,
) -> Tuple[List[str], List[str]]:
    """从 skill-map.yaml 读取指定 Agent 的 L2 auto 和 L3 manual 技能列表。

    Returns:
        ``(l2_auto_list, l3_manual_list)``。
        Agent 不存在或文件无法读取时返回 ``([], [])``。
    """
    try:
        data = read_yaml(skill_map_path)
    except Exception:
        return [], []

    if not isinstance(data, dict):
        return [], []

    agents = data.get("agents", {})
    if not isinstance(agents, dict):
        return [], []

    agent_data = agents.get(agent_name)
    if not isinstance(agent_data, dict):
        return [], []

    categories = agent_data.get("categories", {})
    if not isinstance(categories, dict):
        return [], []

    l2_auto: list[str] = []
    l3_manual: list[str] = []

    for category_name, skills in categories.items():
        if not isinstance(skills, list):
            continue
        for skill in skills:
            if not isinstance(skill, dict):
                continue
            skill_name = skill.get("name", "")
            if not isinstance(skill_name, str) or not skill_name:
                continue

            layer_raw = str(skill.get("layer", ""))
            m = _LAYER_PATTERN.match(layer_raw)
            if not m:
                continue

            layer_num = m.group("layer")
            load_mode = m.group("load").lower()

            if layer_num == "2" and load_mode == "auto":
                l2_auto.append(skill_name)
            elif layer_num == "3" and load_mode == "manual":
                l3_manual.append(skill_name)

    return l2_auto, l3_manual


__all__ = [
    "parse_binding_table",
    "add_binding_row",
    "get_auto_manual_from_skill_map",
]
