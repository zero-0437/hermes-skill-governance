"""
Jinja2 模板引擎 — 为 Agent 管理提供模板渲染能力。

提供 ``render_template(name, params)`` 函数，读取
``scripts/agent-mgmt/templates/`` 目录下的 ``.j2`` 模板文件，
使用 Jinja2 渲染并返回渲染后的字符串。

模板变量均带有类型注解（PEP 484），IDE 自动补全友好。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import BaseLoader, Environment, FileSystemLoader, StrictUndefined, TemplateNotFound

# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------

_TEMPLATES_DIR: Path = Path(__file__).resolve().parent / "templates"

# ---------------------------------------------------------------------------
# Jinja2 环境
# ---------------------------------------------------------------------------

_loader: BaseLoader = FileSystemLoader(searchpath=str(_TEMPLATES_DIR))
_env: Environment = Environment(
    loader=_loader,
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
    undefined=StrictUndefined,
)

# ---------------------------------------------------------------------------
# 模板变量类型别名（PEP 484 友好）
# ---------------------------------------------------------------------------

TAgentRouteParams = Dict[str, Any]
"""``agent-route.yaml.j2`` 模板参数。

Keys & defaults:
    agent (str)                        — Agent 名称（必填）
    description (str)                  — 路由描述
    priority (int)                     — 路由优先级（默认 99）
    condition (str)                    — 触发条件描述
    placeholder_rule_1_description (str) — 占位规则 1 描述（默认 "匹配规则 A"）
    placeholder_rule_1_pattern (str)   — 占位规则 1 触发词（默认 "占位触发词A"）
    placeholder_rule_1_weight (float)  — 占位规则 1 权重（默认 0.5）
    placeholder_rule_1_skills (list)   — 占位规则 1 技能列表（默认 []）
    placeholder_rule_2_description (str) — 占位规则 2 描述（默认 "匹配规则 B"）
    placeholder_rule_2_pattern (str)   — 占位规则 2 正则（默认 "placeholder_regex"）
    placeholder_rule_2_weight (float)  — 占位规则 2 权重（默认 0.5）
    placeholder_rule_2_skills (list)   — 占位规则 2 技能列表（默认 []）
"""

TAgentConfigParams = Dict[str, Any]
"""``agent-config.yaml.j2`` 模板参数。

Keys & defaults:
    agent (str)                        — Agent 名称（必填）
    description (str)                  — Agent 描述
    model (str)                        — 模型名（默认 "deepseek-v4-flash"）
    model_provider (str)               — 模型提供商（默认 "deepseek"）
    fallback_providers (list)          — 备用提供商列表（默认 []）
    toolsets (list)                    — 启用的工具集（默认 ["delegate_task", "terminal", "session_search"]）
    max_turns (int)                    — 最大对话轮次（默认 60）
    gateway_timeout (int)              — 网关超时秒数（默认 1800）
    terminal_timeout (int)             — 终端超时秒数（默认 120）
"""

TSkillEntryParams = Dict[str, Any]
"""``skill-entry.yaml.j2`` 模板参数。

Keys & defaults:
    agent (str)                        — Agent 名称（必填）
    description (str)                  — Agent 描述
    category_name (str)                — 分类名称（必填）
    skill_name (str)                   — 技能名称（必填）
    skill_layer_load (str)             — Layer / Load 描述，如 "2 / load: auto"（必填）
"""

TBindingRowParams = Dict[str, Any]
"""``binding-row.md.j2`` 模板参数。

Keys & defaults:
    agent (str)                        — Agent 名称（必填）
    l2_skills (list)                   — L2 auto 自动加载技能列表（默认 []）
    l3_skills (list)                   — L3 manual 手动指定技能列表（默认 []）
    condition (str)                    — 触发条件描述（必填）
"""

_TEMPLATE_REGISTRY: Dict[str, str] = {
    "agent-route.yaml.j2": "route-map/routes/<agent>.yaml",
    "agent-config.yaml.j2": "profiles/<agent>/config.yaml",
    "skill-entry.yaml.j2": "skill-map.yaml agent 段",
    "binding-row.md.j2": "SOUL.md 绑定表行",
}

# ---------------------------------------------------------------------------
# 默认值字典（集中管理，避免每处重复）
# ---------------------------------------------------------------------------

_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "agent-route.yaml.j2": {
        "priority": 99,
        "placeholder_rule_1_weight": 0.5,
        "placeholder_rule_2_weight": 0.5,
        "placeholder_rule_1_skills": [],
        "placeholder_rule_2_skills": [],
    },
    "agent-config.yaml.j2": {
        "model": "deepseek-v4-flash",
        "model_provider": "deepseek",
        "fallback_providers": [],
        "toolsets": ["delegate_task", "terminal", "session_search"],
        "max_turns": 60,
        "gateway_timeout": 1800,
        "terminal_timeout": 120,
    },
    "skill-entry.yaml.j2": {},
    "binding-row.md.j2": {
        "l2_skills": [],
        "l3_skills": [],
    },
}


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------


def render_template(name: str, params: Optional[Dict[str, Any]] = None) -> str:
    """渲染指定名称的 Jinja2 模板。

    Args:
        name:   模板文件名（如 ``"agent-route.yaml.j2"``）。
        params: 模板变量字典。未提供的变量将使用默认值。
                若变量既未提供又无默认值，则引发 ``jinja2.UndefinedError``。

    Returns:
        渲染后的字符串。

    Raises:
        TemplateNotFound: 模板文件不存在。
        jinja2.UndefinedError: 模板引用了未定义且无默认值的变量。
    """
    if params is None:
        params = {}

    # 合并默认值
    defaults = _DEFAULTS.get(name, {})
    merged: Dict[str, Any] = {**defaults, **params}

    template = _env.get_template(name)
    return template.render(**merged)


def list_templates() -> Dict[str, str]:
    """列出所有可用模板及其用途。

    Returns:
        模板名 → 用途说明的字典。
    """
    result: Dict[str, str] = {}
    for tmpl_name, purpose in _TEMPLATE_REGISTRY.items():
        tmpl_path = _TEMPLATES_DIR / tmpl_name
        if tmpl_path.is_file():
            result[tmpl_name] = purpose
    return result


def validate_template(name: str) -> bool:
    """检查模板文件是否存在且语法有效。

    Args:
        name: 模板文件名。

    Returns:
        存在且可加载返回 ``True``，否则返回 ``False``。
    """
    tmpl_path = _TEMPLATES_DIR / name
    if not tmpl_path.is_file():
        return False
    try:
        _env.get_template(name)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 便捷函数（类型提示让 IDE 自动补全 params 中的 keys）
# ---------------------------------------------------------------------------


def render_agent_route(
    *,
    agent: str,
    description: str = "",
    priority: int = 99,
    condition: str = "",
) -> str:
    """渲染 ``agent-route.yaml.j2`` 路由模板。

    Args:
        agent:       Agent 名称。
        description: 路由文件描述。
        priority:    路由优先级（默认 99）。
        condition:   触发条件描述。

    Returns:
        渲染后的 YAML 字符串。
    """
    params: Dict[str, Any] = {
        "agent": agent,
        "description": description,
        "priority": priority,
        "condition": condition,
    }
    return render_template("agent-route.yaml.j2", params)


def render_agent_config(
    *,
    agent: str,
    description: str = "",
    model: str = "deepseek-v4-flash",
    model_provider: str = "deepseek",
    fallback_providers: Optional[List[str]] = None,
    toolsets: Optional[List[str]] = None,
    max_turns: int = 60,
    gateway_timeout: int = 1800,
    terminal_timeout: int = 120,
) -> str:
    """渲染 ``agent-config.yaml.j2`` 配置模板。

    Args:
        agent:              Agent 名称。
        description:        Agent 描述。
        model:              模型名（默认 "deepseek-v4-flash"）。
        model_provider:     模型提供商（默认 "deepseek"）。
        fallback_providers: 备用提供商列表。
        toolsets:           工具集列表。
        max_turns:          最大对话轮次（默认 60）。
        gateway_timeout:    网关超时秒数（默认 1800）。
        terminal_timeout:   终端超时秒数（默认 120）。

    Returns:
        渲染后的 YAML 字符串。
    """
    params: Dict[str, Any] = {
        "agent": agent,
        "description": description,
        "model": model,
        "model_provider": model_provider,
        "fallback_providers": fallback_providers or [],
        "toolsets": toolsets or ["delegate_task", "terminal", "session_search"],
        "max_turns": max_turns,
        "gateway_timeout": gateway_timeout,
        "terminal_timeout": terminal_timeout,
    }
    return render_template("agent-config.yaml.j2", params)


def render_skill_entry(
    *,
    agent: str,
    description: str,
    category_name: str,
    skill_name: str,
    skill_layer_load: str,
) -> str:
    """渲染 ``skill-entry.yaml.j2`` skill-map 条目模板。

    Args:
        agent:             Agent 名称。
        description:       Agent 描述。
        category_name:     分类名称（如 "架构治理"）。
        skill_name:        技能名称（如 "multi-agent-arch"）。
        skill_layer_load:  Layer/Load 字符串（如 ``"2 / load: auto"``）。

    Returns:
        渲染后的 YAML 字符串。
    """
    params: Dict[str, Any] = {
        "agent": agent,
        "description": description,
        "category_name": category_name,
        "skill_name": skill_name,
        "skill_layer_load": skill_layer_load,
    }
    return render_template("skill-entry.yaml.j2", params)


def render_binding_row(
    *,
    agent: str,
    l2_skills: Optional[List[str]] = None,
    l3_skills: Optional[List[str]] = None,
    condition: str,
) -> str:
    """渲染 ``binding-row.md.j2`` SOUL.md 绑定表行模板。

    Args:
        agent:      Agent 名称（如 ``pm-agent``）。
        l2_skills:  L2 auto（自动加载）技能名称列表。
        l3_skills:  L3 manual（手动指定）技能名称列表。
        condition:  触发条件描述。

    Returns:
        渲染后的 Markdown 行字符串。
    """
    params: Dict[str, Any] = {
        "agent": agent,
        "l2_skills": l2_skills or [],
        "l3_skills": l3_skills or [],
        "condition": condition,
    }
    return render_template("binding-row.md.j2", params)


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    "render_template",
    "list_templates",
    "validate_template",
    "render_agent_route",
    "render_agent_config",
    "render_skill_entry",
    "render_binding_row",
    # 类型别名（用于 type hint / docstring 参考）
    "TAgentRouteParams",
    "TAgentConfigParams",
    "TSkillEntryParams",
    "TBindingRowParams",
]
