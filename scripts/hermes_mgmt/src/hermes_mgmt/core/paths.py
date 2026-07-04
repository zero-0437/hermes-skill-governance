"""
集中路径管理 — 基于 __file__ 动态推导所有项目路径。

消除所有硬编码路径，所有模块通过此模块获取路径。
路径推导基于 ``__file__`` 的解析路径：

    hermes-mgmt/core/paths.py   →  scripts/hermes-mgmt/core/paths.py
    parent * 3                  →  项目根目录 (/opt/data)
"""

from __future__ import annotations

from pathlib import Path

# ── 路径推导 ───────────────────────────────────────────────────────

# scripts/hermes_mgmt/src/hermes_mgmt/core/paths.py
_CORE_DIR = Path(__file__).resolve().parent

# .../core/ → .../hermes_mgmt/ (包根)
_PKG_DIR = _CORE_DIR.parent

# .../hermes_mgmt/ → .../src/
_SRC_DIR = _PKG_DIR.parent

# .../src/ → .../hermes_mgmt_project/ (项目包目录)
_PROJECT_DIR = _SRC_DIR.parent

# .../hermes_mgmt_project/ → .../scripts/
SCRIPTS_DIR = _PROJECT_DIR.parent

# scripts/ → 项目根目录 (/opt/data)
PROJECT_ROOT = SCRIPTS_DIR.parent

# ── 推导出的子路径 ────────────────────────────────────────────────

# route-map/index.yaml
ROUTE_INDEX = PROJECT_ROOT / "route-map" / "index.yaml"

# route-map/routes/
ROUTES_DIR = PROJECT_ROOT / "route-map" / "routes"

# skill-map.yaml
SKILL_MAP = PROJECT_ROOT / "skill-map.yaml"

# SOUL.md
SOUL_MD = PROJECT_ROOT / "SOUL.md"

# profiles/
PROFILES_DIR = PROJECT_ROOT / "profiles"

# .skill-cache.json
SKILL_CACHE = PROJECT_ROOT / ".skill-cache.json"

# .route-cache.json
ROUTE_CACHE = PROJECT_ROOT / ".route-cache.json"

# agent-mgmt 目录（已有库目录）
AGENT_MGMT_DIR = SCRIPTS_DIR / "agent-mgmt"

# agent-mgmt/templates/
TEMPLATES_DIR_LEGACY = AGENT_MGMT_DIR / "templates"

# hermes-mgmt/templates/（新位置）
TEMPLATES_DIR = _PKG_DIR / "templates"

# logs/
LOGS_DIR = PROJECT_ROOT / "logs"

# /tmp/hermes-mgmt-rollback（事务备份目录）
BACKUP_ROOT = Path("/tmp/hermes-mgmt-rollback")

# contexts/agent-environment.md
ENV_MD = PROJECT_ROOT / "contexts" / "agent-environment.md"

# skills/
SKILLS_DIR = PROJECT_ROOT / "skills"


def resolve_path(*parts: str) -> Path:
    """基于项目根目录解析相对路径。

    Args:
        *parts: 相对于项目根目录的路径片段（如 ``"route-map", "index.yaml"``）。

    Returns:
        组合后的绝对路径。
    """
    return PROJECT_ROOT.joinpath(*parts)


def ensure_dir(path: Path) -> Path:
    """确保目录存在，返回该目录路径。"""
    path.mkdir(parents=True, exist_ok=True)
    return path
