"""route 子命令 — 路由规则管理

子命令:
    add              调用 scripts/hermes-route-add 追加路由规则
    list             列出路由规则（可选按 agent 过滤）
    rm               删除指定路由规则

路径通过 hermes_mgmt.core.paths 集中管理。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

from hermes_mgmt.core.paths import (
    PROJECT_ROOT,
    ROUTES_DIR,
    SCRIPTS_DIR,
)
from hermes_mgmt.core.yaml_ops import read_yaml, write_yaml, backup_file

# ── 帮助常量 ──────────────────────────────────────────────────────

_ADD_HELP = """追加路由规则到已有 Agent（调用 hermes-route-add CLI）

示例:
    hermes-mgmt route add --agent programmer --type phrase --pattern "写代码" --weight 1.0
"""

_LIST_HELP = """列出所有路由规则

示例:
    hermes-mgmt route list
    hermes-mgmt route list --agent programmer
"""

_RM_HELP = """删除指定 Agent 的某条路由规则

通过规则索引删除（从 0 开始计数，通过 route list 查看）。

示例:
    hermes-mgmt route rm programmer 2
"""


# ═══════════════════════════════════════════════
# Parser 设置
# ═══════════════════════════════════════════════


def setup_route_parser(subparsers: Any) -> None:
    """向根 subparsers 注册 route 子命令组。"""
    parser = subparsers.add_parser(
        "route",
        help="路由规则管理",
        description="路由规则管理 — 追加、列出、删除路由规则",
    )
    sp = parser.add_subparsers(dest="subcommand", help="route 子命令")

    # route add
    add_p = sp.add_parser("add", help="追加路由规则", description=_ADD_HELP,
                          formatter_class=argparse.RawDescriptionHelpFormatter)
    add_p.add_argument("--agent", required=True, help="Agent 名")
    add_p.add_argument("--type", required=True,
                       choices=["keyword", "phrase", "regex"],
                       help="匹配类型")
    add_p.add_argument("--pattern", required=True, help="匹配模式")
    add_p.add_argument("--weight", required=True, type=float,
                       help="权重（自动钳位到 [-2.0, 2.0]）")
    add_p.add_argument("--skills", default="",
                       help="关联的 L3 skills，逗号分隔（可选）")
    add_p.add_argument("--neg-weight", action="store_true",
                       help="将 weight 转负值")

    # route list
    list_p = sp.add_parser("list", help="列出路由规则", description=_LIST_HELP,
                           formatter_class=argparse.RawDescriptionHelpFormatter)
    list_p.add_argument("--agent", default=None, help="按 Agent 名过滤")

    # route rm
    rm_p = sp.add_parser("rm", help="删除路由规则", description=_RM_HELP,
                         formatter_class=argparse.RawDescriptionHelpFormatter)
    rm_p.add_argument("agent", type=str, help="Agent 名")
    rm_p.add_argument("rule_index", type=int, help="规则索引（从 0 开始）")


# ═══════════════════════════════════════════════
# 命令执行函数
# ═══════════════════════════════════════════════


def cmd_route_add(args: argparse.Namespace) -> int:
    """调用 scripts/hermes-route-add 追加路由规则。"""
    script_path = SCRIPTS_DIR / "hermes-route-add"

    if not script_path.is_file():
        print(f"错误: CLI 脚本不存在: {script_path}", file=sys.stderr)
        return 1

    cli_args = [
        str(script_path),
        "--agent", args.agent,
        "--type", args.type,
        "--pattern", args.pattern,
        "--weight", str(args.weight),
    ]
    if args.skills:
        cli_args.extend(["--skills", args.skills])
    if args.neg_weight:
        cli_args.append("--neg-weight")

    print(f"▶ 调用 hermes-route-add 追加规则到 Agent「{args.agent}」...")
    result = subprocess.run(
        [sys.executable] + cli_args,
        capture_output=False,
        text=True,
        timeout=120,
        cwd=str(PROJECT_ROOT),
    )
    return result.returncode


def cmd_route_list(args: argparse.Namespace) -> int:
    """列出所有路由规则（可选按 agent 过滤）。"""
    if not ROUTES_DIR.is_dir():
        print(f"错误: routes 目录不存在: {ROUTES_DIR}", file=sys.stderr)
        return 1

    route_files = sorted(ROUTES_DIR.glob("*.yaml"))
    if not route_files:
        print("没有发现任何路由规则文件。")
        return 0

    total_rules = 0
    for rfile in route_files:
        if rfile.name == "shared.yaml":
            continue

        try:
            data = read_yaml(str(rfile))
        except Exception:
            continue

        agent_name = data.get("agent") or rfile.stem
        if args.agent and agent_name != args.agent:
            continue

        rules = data.get("rules", [])
        if not rules:
            continue

        print(f"Agent: {agent_name}  [{rfile.name}]")
        for idx, rule in enumerate(rules):
            if not isinstance(rule, dict):
                continue
            rtype = rule.get("type", "?")
            pattern = rule.get("pattern", "?")
            weight = rule.get("weight", "?")
            skills = rule.get("skills", [])
            fuzzy = rule.get("fuzzy", False)
            skills_str = ", ".join(skills) if skills else "(空)"
            fuzzy_flag = " [fuzzy]" if fuzzy else ""
            print(f"  [{idx}] type={rtype}, pattern='{pattern}', "
                  f"weight={weight}, skills=[{skills_str}]{fuzzy_flag}")

        total_rules += len(rules)
        print()

    if args.agent:
        print(f"Agent「{args.agent}」共 {total_rules} 条规则")
    else:
        print(f"共计 {len(route_files)} 个 Agent，{total_rules} 条规则")

    return 0


def cmd_route_rm(args: argparse.Namespace) -> int:
    """删除指定 Agent 的某条路由规则。"""
    agent = args.agent
    rule_idx = args.rule_index

    route_file = ROUTES_DIR / f"{agent}.yaml"
    if not route_file.is_file():
        print(f"错误: route 文件不存在: {route_file}", file=sys.stderr)
        return 1

    try:
        data = read_yaml(str(route_file))
    except Exception as e:
        print(f"错误: 读取 route 文件失败: {e}", file=sys.stderr)
        return 1

    rules = data.get("rules", [])
    if rule_idx < 0 or rule_idx >= len(rules):
        print(f"错误: 规则索引 {rule_idx} 超出范围（共有 {len(rules)} 条规则）",
              file=sys.stderr)
        return 1

    removed_rule = rules[rule_idx]
    pattern_desc = removed_rule.get("pattern", "?")
    del rules[rule_idx]

    backup_file(str(route_file))
    write_yaml(str(route_file), data)

    print(f"✓ 已删除 Agent「{agent}」的第 {rule_idx} 条规则 (pattern='{pattern_desc}')")
    return 0
