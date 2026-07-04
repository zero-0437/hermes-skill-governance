#!/usr/bin/env -S uv run python
"""hermes-mgmt — Hermes Agent 统一治理 CLI 入口

使用方式:

    python -m hermes_mgmt agent add <name> ...
    python -m hermes_mgmt agent list
    python -m hermes_mgmt agent rm <name>
    python -m hermes_mgmt skill add ...
    python -m hermes_mgmt skill list
    python -m hermes_mgmt skill rm <name>
    python -m hermes_mgmt skill patch-skills [--preview|--apply] [--agent NAME]
    python -m hermes_mgmt route add ...
    python -m hermes_mgmt route list [--agent NAME]
    python -m hermes_mgmt route rm <agent> <rule-index>
    python -m hermes_mgmt fuzzy apply-p1
    python -m hermes_mgmt fuzzy apply-p2
    python -m hermes_mgmt audit phase-4
    python -m hermes_mgmt validate
"""

from __future__ import annotations

import argparse
import sys

from hermes_mgmt.commands import agent, skill, route, fuzzy, audit, validate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hermes-mgmt",
        description="Hermes Agent 统一治理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python -m hermes_mgmt agent add my-agent --description ...\n"
            "  python -m hermes_mgmt agent list\n"
            "  python -m hermes_mgmt skill list\n"
            "  python -m hermes_mgmt skill patch-skills --preview\n"
            "  python -m hermes_mgmt route list\n"
            "  python -m hermes_mgmt fuzzy apply-p1\n"
            "  python -m hermes_mgmt audit phase-4\n"
            "  python -m hermes_mgmt validate\n"
        ),
    )
    parser.add_argument(
        "--version", action="store_true",
        help="显示版本号并退出",
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    agent.setup_agent_parser(subparsers)
    skill.setup_skill_parser(subparsers)
    route.setup_route_parser(subparsers)
    fuzzy.setup_fuzzy_parser(subparsers)
    audit.setup_audit_parser(subparsers)
    validate.setup_validate_parser(subparsers)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        from hermes_mgmt import __version__
        print(f"hermes-mgmt v{__version__}")
        return 0

    if not args.command:
        parser.print_help()
        return 1

    # 路由到各子命令
    dispatch: dict[str, dict[str, object]] = {
        "agent":   {"add": agent.cmd_agent_add,   "list": agent.cmd_agent_list,   "rm": agent.cmd_agent_rm},
        "skill":   {"add": skill.cmd_skill_add,   "list": skill.cmd_skill_list,
                    "rm": skill.cmd_skill_rm,     "patch-skills": skill.cmd_skill_patch_skills},
        "route":   {"add": route.cmd_route_add,   "list": route.cmd_route_list,   "rm": route.cmd_route_rm},
        "fuzzy":   {"apply-p1": fuzzy.cmd_fuzzy_apply_p1, "apply-p2": fuzzy.cmd_fuzzy_apply_p2},
        "audit":   {"phase-4": audit.cmd_audit_phase4},
        "validate": {"run": validate.cmd_validate},
    }

    cmd_map = dispatch.get(args.command)
    if cmd_map is None:
        parser.print_help()
        return 1

    sub = getattr(args, "subcommand", None)
    if sub is None:
        # 没有子命令时打印该命令的帮助
        if args.command == "validate":
            return validate.cmd_validate(args)
        parser.print_help()
        return 1

    handler = cmd_map.get(sub)
    if handler is None:
        print(f"错误: 未知子命令「{args.command} {sub}」", file=sys.stderr)
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
