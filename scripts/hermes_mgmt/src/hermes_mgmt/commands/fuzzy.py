"""fuzzy 子命令 — 批量启用路由规则的 fuzzy 匹配

子命令:
    apply-p1    批量设置 P1 优先级规则的 fuzzy: true（~27 条）
    apply-p2    批量设置 P2 优先级规则的 fuzzy: true（~12 条）

规则列表来自 docs/governance-unified-plan.md §四。
路径通过 hermes_mgmt.core.paths 集中管理。
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from hermes_mgmt.core.paths import ROUTES_DIR, PROJECT_ROOT
from hermes_mgmt.core.yaml_ops import read_yaml, write_yaml, backup_file

# ═══════════════════════════════════════════════
# P1 规则定义 — 每一条需要设置 fuzzy: true 的路由规则
# ═══════════════════════════════════════════════
# 格式: (agent_name, pattern, rule_type)

P1_RULES: list[tuple[str, str, str]] = [
    # programmer
    ("programmer", "实现新功能", "phrase"),
    ("programmer", "写一个函数", "phrase"),
    ("programmer", "重构", "phrase"),
    # error-analyst
    ("error-analyst", "内存泄漏", "phrase"),
    ("error-analyst", "诊断错误", "phrase"),
    ("error-analyst", "审查", "phrase"),
    ("error-analyst", "审计", "phrase"),
    ("error-analyst", "漏洞", "phrase"),
    ("error-analyst", "审查代码", "phrase"),
    ("error-analyst", "代码审查", "phrase"),
    ("error-analyst", "复盘", "phrase"),
    ("error-analyst", "事故分析", "phrase"),
    # pm-agent
    ("pm-agent", "治理", "phrase"),
    ("pm-agent", "技能树", "phrase"),
    ("pm-agent", "新增技能", "phrase"),
    ("pm-agent", "一致性", "phrase"),
    ("pm-agent", "拆解", "phrase"),
    ("pm-agent", "设计方案", "phrase"),
    ("pm-agent", "可行性报告", "phrase"),
    ("pm-agent", "技术选型", "phrase"),
    # docs-writer
    ("docs-writer", "写文档", "phrase"),
    ("docs-writer", "说明文档", "phrase"),
    ("docs-writer", "教程", "phrase"),
    ("docs-writer", "写 README", "phrase"),
    # synology-helper
    ("synology-helper", "群晖", "phrase"),
    ("synology-helper", "备份系统", "phrase"),
    ("synology-helper", "完整备份", "phrase"),
    ("synology-helper", "系统维护", "phrase"),
    ("synology-helper", "共享文件夹", "phrase"),
    # prompt-engineer
    ("prompt-engineer", "提示词", "phrase"),
    ("prompt-engineer", "提示工程", "phrase"),
    ("prompt-engineer", "角色定义", "phrase"),
    ("prompt-engineer", "prompt 优化", "phrase"),
    ("prompt-engineer", "prompt 测试", "phrase"),
    # document-processor
    ("document-processor", "文档转换", "phrase"),
    ("document-processor", "格式转换", "phrase"),
    ("document-processor", "文档格式", "phrase"),
    ("document-processor", "扫描件", "phrase"),
    ("document-processor", "提取文字", "phrase"),
    ("document-processor", "公文", "phrase"),
    ("document-processor", "排版", "phrase"),
    # reality-checker
    ("reality-checker", "集成测试", "phrase"),
    ("reality-checker", "验收", "phrase"),
]

# ═══════════════════════════════════════════════
# P2 规则定义
# ═══════════════════════════════════════════════

P2_RULES: list[tuple[str, str, str]] = [
    # programmer
    ("programmer", "编码", "phrase"),
    # error-analyst
    ("error-analyst", "故障", "phrase"),
    ("error-analyst", "崩溃", "phrase"),
    ("error-analyst", "死锁", "phrase"),
    ("error-analyst", "根因", "phrase"),
    ("error-analyst", "审核", "phrase"),
    ("error-analyst", "风险", "phrase"),
    # ui-designer
    ("ui-designer", "动效", "phrase"),
    ("ui-designer", "响应式", "phrase"),
    ("ui-designer", "美化", "phrase"),
    ("ui-designer", "图表设计", "phrase"),
    ("ui-designer", "设计稿", "phrase"),
    ("ui-designer", "配色", "phrase"),
    # file-ops
    ("file-ops", "目录结构", "phrase"),
    ("file-ops", "文件操作", "phrase"),
    ("file-ops", "大文件", "phrase"),
    # data-analyst
    ("data-analyst", "新闻", "phrase"),
    ("data-analyst", "趋势", "phrase"),
    ("data-analyst", "报告", "phrase"),
]


# ── 帮助常量 ──────────────────────────────────────────────────────

_APPLY_P1_HELP = """批量设置 P1 优先级路由规则的 fuzzy: true 字段。

影响 Agent:
  programmer, error-analyst, pm-agent, docs-writer,
  synology-helper, prompt-engineer, document-processor, reality-checker

共 ~27 条规则。

每次修改后自动调用 rebuild-cache + validate 验证。
"""

_APPLY_P2_HELP = """批量设置 P2 优先级路由规则的 fuzzy: true 字段。

影响 Agent:
  programmer, error-analyst, ui-designer, file-ops, data-analyst

共 ~12 条规则。

每次修改后自动调用 rebuild-cache + validate 验证。
"""


# ═══════════════════════════════════════════════
# Parser 设置
# ═══════════════════════════════════════════════


def setup_fuzzy_parser(subparsers: Any) -> None:
    """向根 subparsers 注册 fuzzy 子命令组。"""
    parser = subparsers.add_parser(
        "fuzzy",
        help="批量启用 fuzzy 匹配",
        description="批量设置路由规则的 fuzzy: true 字段（P1/P2 优先级）",
    )
    sp = parser.add_subparsers(dest="subcommand", help="fuzzy 子命令")

    # fuzzy apply-p1
    sp.add_parser("apply-p1", help="应用 P1 fuzzy (~27 条)",
                  description=_APPLY_P1_HELP,
                  formatter_class=argparse.RawDescriptionHelpFormatter)

    # fuzzy apply-p2
    sp.add_parser("apply-p2", help="应用 P2 fuzzy (~12 条)",
                  description=_APPLY_P2_HELP,
                  formatter_class=argparse.RawDescriptionHelpFormatter)


# ═══════════════════════════════════════════════
# 命令执行函数
# ═══════════════════════════════════════════════


def _load_route_file_and_match(
    agent: str,
    pattern: str,
    rule_type: str,
) -> tuple[object, int, object] | None:
    """在 route 文件中按 pattern+type 匹配规则，返回 (data, idx, rule) 或 None。"""
    route_file = ROUTES_DIR / f"{agent}.yaml"
    if not route_file.is_file():
        return None

    try:
        data = read_yaml(str(route_file))
    except Exception:
        return None

    rules = data.get("rules", [])
    for idx, rule in enumerate(rules):
        if not isinstance(rule, dict):
            continue
        if rule.get("type") == rule_type and rule.get("pattern") == pattern:
            return (data, idx, rule)

    return None


def _apply_fuzzy_to_rules(
    rules_def: list[tuple[str, str, str]],
    label: str,
) -> int:
    """批量设置 fuzzy: true 到匹配的规则。

    Args:
        rules_def: (agent, pattern, rule_type) 列表
        label: 日志标签（如 "P1"）

    Returns:
        成功修改的规则数
    """
    modified = 0
    errors = 0
    skipped = 0

    for agent, pattern, rule_type in rules_def:
        result = _load_route_file_and_match(agent, pattern, rule_type)
        if result is None:
            print(f"  ⚠ [{agent}] 未找到匹配规则: type={rule_type}, pattern='{pattern}'")
            skipped += 1
            continue

        data, idx, rule = result
        route_file = ROUTES_DIR / f"{agent}.yaml"

        # 检查是否已设置
        if rule.get("fuzzy") is True:
            print(f"  ~ [{agent}] rule[{idx}] 已设置 fuzzy: true，跳过")
            skipped += 1
            continue

        try:
            backup_file(str(route_file))
            rule["fuzzy"] = True
            write_yaml(str(route_file), data)
            print(f"  ✓ [{agent}] rule[{idx}] (pattern='{pattern}') → fuzzy: true")
            modified += 1
        except Exception as e:
            print(f"  ✗ [{agent}] 写入失败: {e}", file=sys.stderr)
            errors += 1

    print(f"\n{label} 完成: {modified} 修改, {skipped} 跳过, {errors} 错误")

    if errors:
        print(f"  ⚠ 有 {errors} 个错误，请检查日志", file=sys.stderr)

    return modified


def _run_validate_scripts() -> None:
    """修改后自动调用 rebuild-cache + validate 进行验证。"""
    import subprocess

    scripts = ["rebuild-cache.py", "validate-route-map.py", "validate-skill-map.py"]
    for name in scripts:
        script_path = PROJECT_ROOT / "scripts" / name
        if not script_path.is_file():
            print(f"  ⚠ 脚本不存在: {script_path}，跳过")
            continue
        try:
            result = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True, text=True, timeout=60,
                cwd=str(PROJECT_ROOT),
            )
            status = "OK" if result.returncode == 0 else (
                "WARN" if result.returncode == 1 else "ERR"
            )
            print(f"  → {name}: {status}")
            if result.returncode == 2:
                print(f"     {result.stdout[:300]}", file=sys.stderr)
        except subprocess.TimeoutExpired:
            print(f"  → {name}: 超时", file=sys.stderr)
        except Exception as e:
            print(f"  → {name}: 异常: {e}", file=sys.stderr)


def cmd_fuzzy_apply_p1(args: argparse.Namespace) -> int:
    """批量设置 P1 规则的 fuzzy: true。"""
    print("=" * 60)
    print("  应用 P1 Fuzzy 匹配（高优先级）")
    print("=" * 60)
    print()

    modified = _apply_fuzzy_to_rules(P1_RULES, "P1")

    if modified > 0:
        print("\n▸ 正在运行验证脚本...")
        _run_validate_scripts()

    print("\n✓ P1 fuzzy 应用完成")
    return 0


def cmd_fuzzy_apply_p2(args: argparse.Namespace) -> int:
    """批量设置 P2 规则的 fuzzy: true。"""
    print("=" * 60)
    print("  应用 P2 Fuzzy 匹配（观察期）")
    print("=" * 60)
    print()

    modified = _apply_fuzzy_to_rules(P2_RULES, "P2")

    if modified > 0:
        print("\n▸ 正在运行验证脚本...")
        _run_validate_scripts()

    print("\n✓ P2 fuzzy 应用完成")
    return 0
