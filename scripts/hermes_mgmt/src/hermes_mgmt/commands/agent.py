"""agent 子命令 — Agent 增删查

子命令:
    add <name>     调用 scripts/hermes-agent-add 注册新 Agent
    list           列出所有已注册 Agent
    rm  <name>     删除指定 Agent（从 index、skill-map、routes、profiles）

所有路径通过 hermes_mgmt.core.paths 集中管理。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from typing import Any

from hermes_mgmt.core.paths import (
    PROFILES_DIR,
    PROJECT_ROOT,
    ROUTES_DIR,
    ROUTE_INDEX,
    SCRIPTS_DIR,
    SKILL_MAP,
    SOUL_MD,
)
from hermes_mgmt.core.yaml_ops import read_yaml, write_yaml
from hermes_mgmt.core.validation import check_agent_exist

# ── 帮助常量 ──────────────────────────────────────────────────────

_ADD_HELP = """注册新 Agent（调用 hermes-agent-add CLI）

示例:
    hermes-mgmt agent add my-agent \\
        --description "我的新 Agent" \\
        --condition "触发条件" \\
        --priority 50
"""

_LIST_HELP = """列出所有已注册 Agent（从 route-map/index.yaml 读取）"""

_RM_HELP = """删除指定 Agent

从以下位置移除 Agent 的所有制品:
  - route-map/index.yaml
  - route-map/routes/<name>.yaml
  - skill-map.yaml
  - profiles/<name>/
  - SOUL.md 绑定表

注意: 此操作不可逆，请谨慎使用。
"""


# ═══════════════════════════════════════════════
# Parser 设置
# ═══════════════════════════════════════════════


def setup_agent_parser(subparsers: Any) -> None:
    """向根 subparsers 注册 agent 子命令组。"""
    parser = subparsers.add_parser(
        "agent",
        help="Agent 增删查",
        description="Agent 增删查 — 注册、列出、删除 Agent",
    )
    sp = parser.add_subparsers(dest="subcommand", help="agent 子命令")

    # agent add
    add_p = sp.add_parser("add", help="注册新 Agent", description=_ADD_HELP,
                          formatter_class=argparse.RawDescriptionHelpFormatter)
    add_p.add_argument("name", type=str, help="Agent 名称（如 my-agent）")
    add_p.add_argument("--priority", type=int, default=99,
                       help="路由优先级（默认 99，数值越小优先级越高）")
    add_p.add_argument("--condition", type=str, required=True, help="触发条件（必填）")
    add_p.add_argument("--description", type=str, required=True, help="Agent 描述（必填）")
    add_p.add_argument("--model", type=str, default="deepseek-v4-flash",
                       help="模型名称（默认 deepseek-v4-flash）")
    add_p.add_argument("--toolsets", type=str, default="terminal,file",
                       help="工具集，逗号分隔（默认 terminal,file）")
    add_p.add_argument("--skills", type=str, default=None,
                       help="L3 技能名称列表，逗号分隔（可选）")

    # agent list
    sp.add_parser("list", help="列出所有 Agent", description=_LIST_HELP,
                  formatter_class=argparse.RawDescriptionHelpFormatter)

    # agent rm
    rm_p = sp.add_parser("rm", help="删除 Agent", description=_RM_HELP,
                         formatter_class=argparse.RawDescriptionHelpFormatter)
    rm_p.add_argument("name", type=str, help="待删除的 Agent 名称")
    rm_p.add_argument("--force", action="store_true",
                      help="强制删除，跳过确认提示")


# ═══════════════════════════════════════════════
# 命令执行函数
# ═══════════════════════════════════════════════


def cmd_agent_add(args: argparse.Namespace) -> int:
    """调用 scripts/hermes-agent-add 注册新 Agent。"""
    script_path = SCRIPTS_DIR / "hermes-agent-add"

    if not script_path.is_file():
        print(f"错误: CLI 脚本不存在: {script_path}", file=sys.stderr)
        return 1

    cli_args = [
        str(script_path),
        args.name,
        "--priority", str(args.priority),
        "--condition", args.condition,
        "--description", args.description,
        "--model", args.model,
        "--toolsets", args.toolsets,
    ]
    if args.skills:
        cli_args.extend(["--skills", args.skills])

    print(f"▶ 调用 hermes-agent-add 注册 Agent「{args.name}」...")
    result = subprocess.run(
        [sys.executable] + cli_args,
        capture_output=False,
        text=True,
        timeout=120,
        cwd=str(PROJECT_ROOT),
    )
    return result.returncode


def cmd_agent_list(args: argparse.Namespace) -> int:
    """从 route-map/index.yaml 列出所有已注册 Agent。"""
    if not ROUTE_INDEX.is_file():
        print(f"错误: index.yaml 不存在: {ROUTE_INDEX}", file=sys.stderr)
        return 1

    try:
        data = read_yaml(str(ROUTE_INDEX))
    except Exception as e:
        print(f"错误: 读取 index.yaml 失败: {e}", file=sys.stderr)
        return 1

    agents = data.get("agents", {})
    if not agents:
        print("当前没有任何已注册的 Agent。")
        return 0

    print(f"已注册的 Agent（共 {len(agents)} 个）:\n")

    # 按 priority 排序
    sorted_agents = sorted(
        agents.items(),
        key=lambda item: item[1].get("priority", 99),
    )

    for name, info in sorted_agents:
        priority = info.get("priority", "?")
        desc = info.get("description", "")
        cond = info.get("condition", "")
        route_file = info.get("file", "")
        print(f"  {name}")
        print(f"    优先级:   {priority}")
        print(f"    描述:     {desc}")
        print(f"    触发条件: {cond}")
        print(f"    路由文件: {route_file}")
        print()

    return 0


def cmd_agent_rm(args: argparse.Namespace) -> int:
    """删除指定 Agent（从 index、skill-map、routes、profiles）。"""
    name = args.name

    # ── 校验 ──────────────────────────────────────────────────
    exists, msg = check_agent_exist(name)
    if not exists:
        print(f"错误: {msg}", file=sys.stderr)
        return 1

    # ── 确认 ──────────────────────────────────────────────────
    if not args.force:
        print(f"警告: 将永久删除 Agent「{name}」的所有制品！", file=sys.stderr)
        print("  以下位置将受影响:", file=sys.stderr)
        print(f"    - route-map/index.yaml", file=sys.stderr)
        print(f"    - route-map/routes/{name}.yaml", file=sys.stderr)
        print(f"    - skill-map.yaml", file=sys.stderr)
        print(f"    - profiles/{name}/", file=sys.stderr)
        print(f"    - SOUL.md 绑定表", file=sys.stderr)
        try:
            confirm = input("确认删除？(yes/no): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消", file=sys.stderr)
            return 1
        if confirm not in ("yes", "y"):
            print("已取消")
            return 0

    # ── 执行删除 ──────────────────────────────────────────────
    removed: list[str] = []

    try:
        # 1) route-map/index.yaml — 从 agents 段移除
        if ROUTE_INDEX.is_file():
            data = read_yaml(str(ROUTE_INDEX))
            agents = data.get("agents", {})
            if name in agents:
                del agents[name]
                write_yaml(str(ROUTE_INDEX), data)
                removed.append(str(ROUTE_INDEX.relative_to(PROJECT_ROOT)))

        # 2) route-map/routes/{name}.yaml
        route_file = ROUTES_DIR / f"{name}.yaml"
        if route_file.is_file():
            route_file.unlink()
            removed.append(str(route_file.relative_to(PROJECT_ROOT)))

        # 3) skill-map.yaml — 从 agents 段移除
        if SKILL_MAP.is_file():
            data = read_yaml(str(SKILL_MAP))
            agents = data.get("agents", {})
            if name in agents:
                del agents[name]
                write_yaml(str(SKILL_MAP), data)
                removed.append(str(SKILL_MAP.relative_to(PROJECT_ROOT)))

        # 4) profiles/{name}/
        profile_dir = PROFILES_DIR / name
        if profile_dir.is_dir():
            import shutil
            shutil.rmtree(profile_dir)
            removed.append(str(profile_dir.relative_to(PROJECT_ROOT)))

        # 5) SOUL.md 绑定表 — 移除对应行
        if SOUL_MD.is_file():
            _remove_agent_from_soul_binding(name)

        print(f"✓ Agent「{name}」已删除。")
        if removed:
            print("已清理:")
            for p in removed:
                print(f"  - {p}")

        return 0

    except Exception as e:
        print(f"错误: 删除 Agent 时发生异常: {e}", file=sys.stderr)
        return 1


def _remove_agent_from_soul_binding(agent_name: str) -> None:
    """从 SOUL.md 绑定表中移除指定 Agent 的行。"""
    content = SOUL_MD.read_text(encoding="utf-8")
    lines = content.split("\n")

    new_lines: list[str] = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        if "## Agent→Skill 绑定表" in stripped:
            in_table = True
            new_lines.append(line)
            continue
        if in_table:
            # 跳过数据行中等于 agent_name 的行
            if stripped.startswith("| `"):
                cells = [c.strip() for c in stripped.strip("|").split("|")]
                if cells and cells[0].strip("`") == agent_name:
                    continue  # 跳过该行
            # 检查是否离开表格区域
            if stripped.startswith("##") and "Skill" not in stripped:
                in_table = False
                new_lines.append(line)
                continue
            if not stripped:
                in_table = False
        new_lines.append(line)

    SOUL_MD.write_text("\n".join(new_lines), encoding="utf-8")
