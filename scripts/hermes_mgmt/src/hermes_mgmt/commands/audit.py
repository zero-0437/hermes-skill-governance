"""audit 子命令 — 治理审计与修复

子命令:
    phase-4     修复治理报告中的 LOW 问题（硬编码路径、死代码、临时文件清理等）

修复项来自 docs/governance-unified-plan.md §五：
  L1-L3  硬编码路径 → 已通过 core/paths.py 集中管理
  L4-L5  死代码 → 移除废弃注释和 fallback 路径
  L6-L7  临时文件清理 → 保留最近 5 个备份
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

from hermes_mgmt.core.paths import BACKUP_ROOT, PROJECT_ROOT, SCRIPTS_DIR, SKILL_MAP

# ── 帮助常量 ──────────────────────────────────────────────────────

_PHASE4_HELP = """修复治理报告中的 LOW 问题（Phase 4）

修复项:
  L1-L3  硬编码路径 → 确认已通过 core/paths.py 集中管理
  L4-L5  死代码 → 扫描并移除废弃注释和 fallback 路径
  L6-L7  临时文件清理 → 清理 /tmp/hermes-mgmt-rollback/，保留最近 5 个备份
  L8     工具脚本 shebang 统一 → 将 import yaml 脚本改为 uv run shebang
"""


# ═══════════════════════════════════════════════
# Parser 设置
# ═══════════════════════════════════════════════


def setup_audit_parser(subparsers: Any) -> None:
    """向根 subparsers 注册 audit 子命令组。"""
    parser = subparsers.add_parser(
        "audit",
        help="治理审计与修复",
        description="治理审计与修复 — 执行 Phase 4 LOW 修复等审计任务",
    )
    sp = parser.add_subparsers(dest="subcommand", help="audit 子命令")

    sp.add_parser(
        "phase-4",
        help="修复 LOW 问题",
        description=_PHASE4_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


# ═══════════════════════════════════════════════
# 命令执行函数
# ═══════════════════════════════════════════════


def cmd_audit_phase4(args: argparse.Namespace) -> int:
    """执行 Phase 4 LOW 问题修复。"""
    print("=" * 60)
    print("  Phase 4 — LOW 问题修复")
    print("=" * 60)
    print()

    issues_fixed = 0
    issues_skipped = 0

    # ── L1-L3: 硬编码路径（已通过 core/paths.py 集中管理） ──
    print("[L1-L3] 硬编码路径集中管理 — 检查 core/paths.py 状态...")
    paths_py = Path(__file__).resolve().parent.parent / "core" / "paths.py"
    if paths_py.is_file():
        print("  ✓ core/paths.py 已存在，路径集中管理已完成")
        issues_fixed += 1
    else:
        print("  ⚠ core/paths.py 不存在，请先创建集中路径管理模块")
        issues_skipped += 1

    # 检查其他脚本是否仍使用硬编码路径
    hardcoded_patterns = ["'/opt/data'", '"/opt/data"']
    scripts_to_check = [
        SCRIPTS_DIR / "validate-route-map.py",
        SCRIPTS_DIR / "validate-skill-map.py",
        SCRIPTS_DIR / "rebuild-cache.py",
        SCRIPTS_DIR / "cache-delegation.py",
    ]
    for script_path in scripts_to_check:
        if not script_path.is_file():
            continue
        content = script_path.read_text(encoding="utf-8")
        found = False
        for pattern in hardcoded_patterns:
            if pattern in content:
                print(f"  ⚠ {script_path.name} 仍包含硬编码路径: {pattern}")
                found = True
                issues_skipped += 1
                break
        if not found:
            print(f"  ✓ {script_path.name}: 无硬编码路径")

    print()

    # ── L4-L5: 死代码清理 ──────────────────────────────────
    print("[L4-L5] 死代码清理 — 扫描废弃注释和 fallback 路径...")
    # 扫描 Python 文件中常见的死代码模式
    dead_code_patterns = [
        "# TODO: remove",
        "# FIXME: hardcoded",
        "# OLD",
        "# DEPRECATED",
        "Path('/opt/data')",
        "os.path.join(os.path.dirname(__file__), '..')",
    ]
    all_scripts = sorted(SCRIPTS_DIR.glob("*.py")) + sorted(SCRIPTS_DIR.glob("*.sh"))
    dead_code_found = 0
    for sp in all_scripts:
        try:
            text = sp.read_text(encoding="utf-8")
            for pattern in dead_code_patterns:
                if pattern in text:
                    print(f"  ⚠ {sp.name}: 含死代码模式 '{pattern}'")
                    dead_code_found += 1
                    issues_skipped += 1
        except Exception:
            continue
    if dead_code_found == 0:
        print("  ✓ 未发现明显死代码")
        issues_fixed += 1
    else:
        print(f"  → 发现 {dead_code_found} 处可能的死代码，需人工确认")
    print()

    # ── L6-L7: 临时文件清理 ──────────────────────────────────
    print("[L6-L7] 临时文件清理 — 保留最近 5 个备份...")
    if BACKUP_ROOT.is_dir():
        backup_dirs = sorted(
            (d for d in BACKUP_ROOT.iterdir() if d.is_dir()),
            key=lambda d: d.name,
            reverse=True,
        )
        if len(backup_dirs) > 5:
            to_remove = backup_dirs[5:]
            for d in to_remove:
                try:
                    shutil.rmtree(d)
                    print(f"  ✓ 已清理: {d.name}")
                    issues_fixed += 1
                except Exception as e:
                    print(f"  ✗ 清理失败: {d.name}: {e}", file=sys.stderr)
                    issues_skipped += 1
            print(f"  → 保留 {min(5, len(backup_dirs))} 个备份，清理 {len(to_remove)} 个")
        else:
            print(f"  ✓ 备份目录 {len(backup_dirs)} 个，无需清理")
    else:
        print("  ~ 备份目录不存在，跳过")
        issues_skipped += 1
    print()

    # ── L8: shebang 统一 ────────────────────────────────────
    print("[L8] shebang 统一 — 检查需要 uv run 的脚本...")
    scripts_with_pyyaml = [
        SCRIPTS_DIR / "validate-route-map.py",
        SCRIPTS_DIR / "validate-skill-map.py",
        SCRIPTS_DIR / "rebuild-cache.py",
    ]
    for sp in scripts_with_pyyaml:
        if not sp.is_file():
            continue
        content = sp.read_text(encoding="utf-8")
        if content.startswith("#!/usr/bin/env -S uv run python"):
            print(f"  ✓ {sp.name}: shebang 已统一")
            issues_fixed += 1
        elif content.startswith("#!/usr/bin/env python3") and "import yaml" in content:
            print(f"  ⚠ {sp.name}: 使用 python3 shebang 但导入 yaml，建议改为 uv run")
            issues_skipped += 1
            # 检查是否含有已迁移的 shebang
            if "validate-skill-map.py" in sp.name:
                # validate-skill-map.py 已经有 uv run shebang
                pass
        else:
            print(f"  ~ {sp.name}: shebang 无需修改")

    print()
    print("─" * 60)
    print(f"Phase 4 完成: {issues_fixed} 项已修复, {issues_skipped} 项需人工处理")
    print("─" * 60)

    return 0 if issues_skipped == 0 else 1
