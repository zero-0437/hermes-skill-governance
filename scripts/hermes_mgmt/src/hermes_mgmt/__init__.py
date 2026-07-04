"""
hermes-mgmt — Hermes Agent 统一治理工具

提供统一的 CLI 入口，替代原有的 3 个独立 CLI（hermes-agent-add、hermes-route-add、hermes-skill-add）。

使用方式：

    python -m hermes_mgmt agent add ...
    python -m hermes_mgmt agent list
    python -m hermes_mgmt skill add ...
    python -m hermes_mgmt route add ...
    python -m hermes_mgmt fuzzy apply-p1
    python -m hermes_mgmt fuzzy apply-p2
    python -m hermes_mgmt audit phase-4
    python -m hermes_mgmt validate
"""

from __future__ import annotations

__version__ = "1.0.0"
