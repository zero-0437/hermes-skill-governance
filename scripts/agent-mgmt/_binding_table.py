"""
SOUL.md 绑定表操作模块

基于 str/re 解析 Markdown 表格，无第三方 Markdown 依赖。
绑定表位于 SOUL.md 的 "## Agent→Skill 绑定表" 章节。

Functions:
    parse_binding_table(soul_md_content) -> dict
    add_binding_row(agent_name, l2_skills, l3_skills, condition) -> str
    get_auto_manual_from_skill_map(agent_name, skill_map_path) -> (list, list)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, List, Tuple

# ---------------------------------------------------------------------------
# 导入兄弟模块 _yaml_ops
# 由于所在目录名包含连字符 "agent-mgmt"，无法作为标准 Python 包导入，
# 因此通过 sys.path 添加本目录路径来导入兄弟模块。
# ---------------------------------------------------------------------------
_mgmt_dir = Path(__file__).resolve().parent
if str(_mgmt_dir) not in sys.path:
    sys.path.insert(0, str(_mgmt_dir))

from _yaml_ops import read_yaml  # noqa: E402

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 绑定表表头标识（用于定位表格起始行）
_HEADER_MARKER = "| Agent |"

# 空技能占位符
_EMPTY_SKILL_PLACEHOLDER = "—"

# skill-map.yaml layer 字段解析正则
# 格式: "<N> / load: auto|manual"  例如 "2 / load: auto"
_LAYER_PATTERN = re.compile(
    r"^\s*(?P<layer>\d+)\s*/\s*load\s*:\s*(?P<load>auto|manual)\s*$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


def _parse_skill_list(cell_text: str) -> list[str]:
    """解析表格单元格中的技能名称列表。

    Args:
        cell_text: 单元格内容，如 ``"multi-agent-arch, plan"`` 或 ``"—"``。

    Returns:
        技能名称列表。空单元格或 ``"—"`` 返回空列表。
    """
    text = cell_text.strip()
    if not text or text == _EMPTY_SKILL_PLACEHOLDER or text == "-":
        return []
    return [s.strip() for s in text.split(",") if s.strip()]


def _is_table_separator_line(stripped: str) -> bool:
    """判断 Markdown 表格分隔行（如 |---|---|...|）。"""
    # 去掉首尾 | 后，只应包含 -、| 和空白
    core = stripped.strip("|").strip()
    return bool(core) and all(ch in ("-", "|", " ", ":") for ch in core)


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------


def parse_binding_table(soul_md_content: str) -> dict[str, dict[str, Any]]:
    """从 SOUL.md Markdown 内容中解析 Agent→Skill 绑定表。

    绑定表格式（Markdown 表格）::

        | Agent | L2 auto（自动加载） | L3 manual（context 显式指定） | condition（触发条件） |
        |-------|-------------------|---------------------------|----------------------|
        | ``agent-name`` | skill1, skill2 | skill3, skill4 | condition text |

    Args:
        soul_md_content: SOUL.md 的完整文本内容。

    Returns:
        形如 ``{agent_name: {"l2": [...], "l3": [...], "condition": str}, ...}``
        的字典。未找到绑定表时返回空 ``dict``。
    """
    result: dict[str, dict[str, Any]] = {}
    lines = soul_md_content.split("\n")

    # 1) 定位表头行
    header_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(_HEADER_MARKER):
            header_idx = i
            break

    if header_idx < 0:
        return result

    # 2) 跳过表头和分隔行，到达数据行起始
    data_start = header_idx + 2
    if data_start >= len(lines):
        return result

    # 3) 逐行解析数据行
    for line in lines[data_start:]:
        stripped = line.strip()

        # 空行或非表格行结束表格
        if not stripped or not stripped.startswith("|"):
            break

        # 跳过可能残留的分隔行
        if _is_table_separator_line(stripped):
            continue

        # 确保这是数据行（以 | 开头，agent 名称通常以 | ` 开头）
        if not stripped.startswith("| "):
            break

        # 去掉首尾 |
        content = stripped.strip("|").strip()
        # 用 | 分割各列
        cells = [c.strip() for c in content.split("|")]
        if len(cells) < 4:
            continue

        # 第 0 列: Agent 名称（带反引号，如 `pm-agent`）
        agent_name = cells[0].strip("`").strip()
        if not agent_name:
            continue

        # 第 1 列: L2 auto 技能
        l2 = _parse_skill_list(cells[1])

        # 第 2 列: L3 manual 技能
        l3 = _parse_skill_list(cells[2])

        # 第 3 列及之后: condition（可能包含 | 字符）
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

    输出格式（与 ``binding-row.md.j2`` 模板对齐）::

        | ``agent_name`` | skill1, skill2 | skill3, skill4 | condition text |

    当技能列表为空时使用 ``"—"`` 占位（与 SOUL.md 现有行对齐）。

    Args:
        agent_name: Agent 名称（将被包裹在反引号中）。
        l2_skills:  L2 auto（自动加载）技能名称列表。
        l3_skills:  L3 manual（context 显式指定）技能名称列表。
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

    skill-map.yaml 中每个技能项的 ``layer`` 字段格式::

        layer: "<N> / load: auto|manual"

    本函数收集:
        - **L2 auto**: layer 为 ``"2 / load: auto"`` 的技能名称
        - **L3 manual**: layer 为 ``"3 / load: manual"`` 的技能名称

    技能按在 YAML 中出现的顺序返回。

    Args:
        agent_name:     Agent 名称（如 ``"pm-agent"``）。
        skill_map_path: ``skill-map.yaml`` 的文件路径。

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


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    "parse_binding_table",
    "add_binding_row",
    "get_auto_manual_from_skill_map",
]
