"""
Jinja2 模板引擎 — 为 Agent 管理提供模板渲染能力。

从原有 ``scripts/agent-mgmt/_templates.py`` 迁移，模板目录同时
支持 agent-mgmt/templates（旧）和 hermes-mgmt/templates（新）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import BaseLoader, Environment, FileSystemLoader, StrictUndefined

from hermes_mgmt.core.paths import TEMPLATES_DIR, TEMPLATES_DIR_LEGACY

# ---------------------------------------------------------------------------
# Jinja2 环境 — 优先使用新模板目录，回退到旧目录
# ---------------------------------------------------------------------------

_TEMPLATE_SEARCH_PATHS = [str(TEMPLATES_DIR), str(TEMPLATES_DIR_LEGACY)]

_loader: BaseLoader = FileSystemLoader(searchpath=_TEMPLATE_SEARCH_PATHS)
_env: Environment = Environment(
    loader=_loader,
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
    undefined=StrictUndefined,
)

# ---------------------------------------------------------------------------
# 默认值字典
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
        params: 模板变量字典。

    Returns:
        渲染后的字符串。
    """
    if params is None:
        params = {}
    defaults = _DEFAULTS.get(name, {})
    merged: Dict[str, Any] = {**defaults, **params}
    template = _env.get_template(name)
    return template.render(**merged)


def list_templates() -> Dict[str, str]:
    """列出所有可用模板及其用途。"""
    registry: Dict[str, str] = {
        "agent-route.yaml.j2": "route-map/routes/<agent>.yaml",
        "agent-config.yaml.j2": "profiles/<agent>/config.yaml",
        "skill-entry.yaml.j2": "skill-map.yaml agent 段",
        "binding-row.md.j2": "SOUL.md 绑定表行",
    }
    result: Dict[str, str] = {}
    for tmpl_name, purpose in registry.items():
        try:
            _env.get_template(tmpl_name)
            result[tmpl_name] = purpose
        except Exception:
            pass
    return result


def validate_template(name: str) -> bool:
    """检查模板文件是否存在且语法有效。"""
    try:
        _env.get_template(name)
        return True
    except Exception:
        return False


def render_agent_route(
    *,
    agent: str,
    description: str = "",
    priority: int = 99,
    condition: str = "",
) -> str:
    """渲染 ``agent-route.yaml.j2`` 路由模板。"""
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
    """渲染 ``agent-config.yaml.j2`` 配置模板。"""
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
    """渲染 ``skill-entry.yaml.j2`` skill-map 条目模板。"""
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
    """渲染 ``binding-row.md.j2`` SOUL.md 绑定表行模板。"""
    params: Dict[str, Any] = {
        "agent": agent,
        "l2_skills": l2_skills or [],
        "l3_skills": l3_skills or [],
        "condition": condition,
    }
    return render_template("binding-row.md.j2", params)


__all__ = [
    "render_template",
    "list_templates",
    "validate_template",
    "render_agent_route",
    "render_agent_config",
    "render_skill_entry",
    "render_binding_row",
]
