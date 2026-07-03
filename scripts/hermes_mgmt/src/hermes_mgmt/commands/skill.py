"""skill 子命令 — 技能管理

子命令:
    add                调用 scripts/hermes-skill-add 注册新技能
    list               列出所有已注册技能（从 skill-map.yaml）
    rm                 删除指定技能
    patch-skills       批量修补路由规则中的 skills: [] 字段（自动匹配 L3 manual 技能）

路径通过 hermes_mgmt.core.paths 集中管理。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

import ruamel.yaml

from hermes_mgmt.core.paths import (
    PROJECT_ROOT,
    ROUTES_DIR,
    SCRIPTS_DIR,
    SKILL_MAP,
    SOUL_MD,
)
from hermes_mgmt.core.yaml_ops import read_yaml, write_yaml, iter_skills, backup_file

# ── 帮助常量 ──────────────────────────────────────────────────────

_ADD_HELP = """注册新技能（调用 hermes-skill-add CLI）

示例:
    hermes-mgmt skill add --agent pm-agent --category 新分类 --name my-skill --layer 3 --load manual
"""

_LIST_HELP = """列出所有已注册技能（从 skill-map.yaml 读取）"""

_RM_HELP = """删除指定技能

从 skill-map.yaml 中移除指定 Agent 下指定分类中的指定技能。
"""

_PATCH_HELP = """批量修补路由规则中的 skills: [] 字段

根据 SOUL.md 绑定表中的 L3 manual 技能，自动补全空 skills 字段。
按 pattern 语义匹配规则与技能。

选项:
    --preview           仅输出 diff 预览，不执行写入
    --apply             执行批量写入
    --agent NAME        仅处理指定 Agent（不指定则处理所有）

示例:
    hermes-mgmt skill patch-skills --preview
    hermes-mgmt skill patch-skills --apply
    hermes-mgmt skill patch-skills --apply --agent programmer
"""

# ── pattern → skills 语义匹配表 ──────────────────────────────────
# 键：规则 pattern 应包含的关键词
# 值：应关联的 L3 manual 技能列表

_PATTERN_SKILL_MAP: dict[str, list[str]] = {
    "搜索":    ["github-search", "arxiv", "blogwatcher"],
    "查询":    ["github-search", "arxiv", "blogwatcher"],
    "文档":    ["doc-coauthoring", "engineering-technical-writer"],
    "写":     ["doc-coauthoring", "engineering-technical-writer"],
    "记忆":    ["llm-wiki", "obsidian"],
    "知识库":   ["llm-wiki", "obsidian"],
    "设计":    ["taste-skill", "claude-design", "excalidraw"],
    "界面":    ["taste-skill", "claude-design", "excalidraw"],
    "代码":    ["conventional-commit", "code-review-checklist", "design-pattern-rules", "live-api-skill"],
    "开发":    ["conventional-commit", "code-review-checklist", "design-pattern-rules"],
    "测试":    ["pytest-skill", "playwright-skill"],
    "部署":    ["deployment-skill", "docker-skill"],
    "修复":    ["debug-skill", "code-review-checklist"],
    "审查":    ["code-review-checklist"],
    "审计":    ["code-review-checklist", "compliance-check"],
    "故障":    ["debug-skill", "error-diagnosis"],
    "错误":    ["debug-skill", "error-diagnosis"],
    "监控":    ["monitoring-skill", "alerting-skill"],
    "日志":    ["log-analysis", "monitoring-skill"],
    "数据":    ["data-analysis", "data-visualization"],
    "报告":    ["data-analysis", "report-generation"],
    "配置":    ["config-management", "env-setup"],
    "安全":    ["security-audit", "compliance-check"],
    "备份":    ["backup-skill", "disaster-recovery"],
    "迁移":    ["migration-skill"],
}


# ═══════════════════════════════════════════════
# Parser 设置
# ═══════════════════════════════════════════════


def setup_skill_parser(subparsers: Any) -> None:
    """向根 subparsers 注册 skill 子命令组。"""
    parser = subparsers.add_parser(
        "skill",
        help="技能管理",
        description="技能管理 — 注册、列出、删除技能，批量修补 skills 字段",
    )
    sp = parser.add_subparsers(dest="subcommand", help="skill 子命令")

    # skill add
    add_p = sp.add_parser("add", help="注册新技能", description=_ADD_HELP,
                          formatter_class=argparse.RawDescriptionHelpFormatter)
    add_p.add_argument("--agent", required=True, help="Agent 名")
    add_p.add_argument("--category", required=True, help="技能分类")
    add_p.add_argument("--name", required=True, help="技能名")
    add_p.add_argument("--layer", required=True, choices=["1", "2", "3", "4"],
                       help="技能层级 (1-4)")
    add_p.add_argument("--load", required=True, choices=["auto", "manual"],
                       help="加载模式")
    add_p.add_argument("--intentional", action="store_true",
                       help="是否需明确调用")
    add_p.add_argument("--ref", help="参考文档路径")
    add_p.add_argument("--add-route", action="store_true",
                       help="是否同时加路由规则")
    add_p.add_argument("--route-pattern", help="路由匹配模式")
    add_p.add_argument("--route-type", default="phrase",
                       choices=["phrase", "regex", "keyword"],
                       help="路由规则类型（默认 phrase）")
    add_p.add_argument("--route-weight", type=float, default=1.0,
                       help="路由规则权重（默认 1.0）")

    # skill list
    sp.add_parser("list", help="列出所有技能", description=_LIST_HELP,
                  formatter_class=argparse.RawDescriptionHelpFormatter)

    # skill rm
    rm_p = sp.add_parser("rm", help="删除技能", description=_RM_HELP,
                         formatter_class=argparse.RawDescriptionHelpFormatter)
    rm_p.add_argument("--agent", required=True, help="Agent 名")
    rm_p.add_argument("--category", required=True, help="技能分类")
    rm_p.add_argument("--name", required=True, help="技能名")

    # skill patch-skills
    patch_p = sp.add_parser("patch-skills", help="批量修补 skills 字段",
                            description=_PATCH_HELP,
                            formatter_class=argparse.RawDescriptionHelpFormatter)
    group = patch_p.add_mutually_exclusive_group(required=True)
    group.add_argument("--preview", action="store_true",
                       help="输出 diff 预览，不执行写入")
    group.add_argument("--apply", action="store_true",
                       help="执行批量写入")
    patch_p.add_argument("--agent", default=None,
                         help="仅处理指定 Agent（不指定则处理所有）")


# ═══════════════════════════════════════════════
# 命令执行函数
# ═══════════════════════════════════════════════


def cmd_skill_add(args: argparse.Namespace) -> int:
    """调用 scripts/hermes-skill-add 注册新技能。"""
    script_path = SCRIPTS_DIR / "hermes-skill-add"

    if not script_path.is_file():
        print(f"错误: CLI 脚本不存在: {script_path}", file=sys.stderr)
        return 1

    cli_args = [
        str(script_path),
        "--agent", args.agent,
        "--category", args.category,
        "--name", args.name,
        "--layer", args.layer,
        "--load", args.load,
    ]
    if args.intentional:
        cli_args.append("--intentional")
    if args.ref:
        cli_args.extend(["--ref", args.ref])
    if args.add_route:
        cli_args.append("--add-route")
    if args.route_pattern:
        cli_args.extend(["--route-pattern", args.route_pattern])
    if args.route_type:
        cli_args.extend(["--route-type", args.route_type])
    if args.route_weight:
        cli_args.extend(["--route-weight", str(args.route_weight)])

    print(f"▶ 调用 hermes-skill-add 注册技能「{args.name}」→ {args.agent}...")
    result = subprocess.run(
        [sys.executable] + cli_args,
        capture_output=False,
        text=True,
        timeout=120,
        cwd=str(PROJECT_ROOT),
    )
    return result.returncode


def cmd_skill_list(args: argparse.Namespace) -> int:
    """从 skill-map.yaml 列出所有已注册技能。"""
    if not SKILL_MAP.is_file():
        print(f"错误: skill-map.yaml 不存在: {SKILL_MAP}", file=sys.stderr)
        return 1

    try:
        data = read_yaml(str(SKILL_MAP))
    except Exception as e:
        print(f"错误: 读取 skill-map.yaml 失败: {e}", file=sys.stderr)
        return 1

    agents_data = data.get("agents", {})
    shared_data = data.get("shared", {})

    if not agents_data and not shared_data:
        print("当前没有任何已注册的技能。")
        return 0

    total_skills = 0

    print(f"=== skill-map.yaml 技能清单 ===\n")

    # agents 段
    for agent_name in sorted(agents_data.keys()):
        agent_info = agents_data[agent_name]
        categories = agent_info.get("categories", {})
        if not categories:
            continue
        print(f"Agent: {agent_name}")
        for cat_name in sorted(categories.keys()):
            skills = categories[cat_name]
            if not skills:
                continue
            print(f"  [{cat_name}]")
            for s in skills:
                if isinstance(s, dict):
                    name = s.get("name", "?")
                    layer = s.get("layer", "?")
                    flags = []
                    if s.get("intentional"):
                        flags.append("intentional")
                    flag_str = f" ({', '.join(flags)})" if flags else ""
                    print(f"    - {name}  [layer: {layer}]{flag_str}")
                elif isinstance(s, str):
                    print(f"    - {s}")
                total_skills += 1
        print()

    # shared 段
    shared_cats = shared_data.get("categories", {})
    if shared_cats:
        print("Shared（全局技能）:")
        for cat_name in sorted(shared_cats.keys()):
            skills = shared_cats[cat_name]
            if not skills:
                continue
            print(f"  [{cat_name}]")
            for s in skills:
                if isinstance(s, dict):
                    name = s.get("name", "?")
                    layer = s.get("layer", "?")
                    print(f"    - {name}  [layer: {layer}]")
                elif isinstance(s, str):
                    print(f"    - {s}")
                total_skills += 1
        print()

    print(f"共计: {total_skills} 个技能")

    return 0


def cmd_skill_rm(args: argparse.Namespace) -> int:
    """从 skill-map.yaml 中移除指定技能。"""
    agent = args.agent
    category = args.category
    name = args.name

    if not SKILL_MAP.is_file():
        print(f"错误: skill-map.yaml 不存在: {SKILL_MAP}", file=sys.stderr)
        return 1

    try:
        data = read_yaml(str(SKILL_MAP))
    except Exception as e:
        print(f"错误: 读取 skill-map.yaml 失败: {e}", file=sys.stderr)
        return 1

    agents_data = data.get("agents", {})
    if agent not in agents_data:
        print(f"错误: Agent「{agent}」在 skill-map.yaml 中不存在", file=sys.stderr)
        return 1

    categories = agents_data[agent].get("categories", {})
    if category not in categories:
        print(f"错误: 分类「{category}」在 Agent「{agent}」中不存在", file=sys.stderr)
        return 1

    skills_list = categories[category]
    found = False
    for i, s in enumerate(skills_list):
        if isinstance(s, dict) and s.get("name") == name:
            del skills_list[i]
            found = True
            break
        elif isinstance(s, str) and s == name:
            del skills_list[i]
            found = True
            break

    if not found:
        print(f"错误: 技能「{name}」在 {agent} > {category} 中不存在", file=sys.stderr)
        return 1

    # 清理空分类
    if not skills_list:
        del categories[category]

    backup_file(str(SKILL_MAP))
    write_yaml(str(SKILL_MAP), data)

    print(f"✓ 已删除技能: {agent} > {category} > {name}")
    return 0


# ═══════════════════════════════════════════════
# patch-skills 实现
# ═══════════════════════════════════════════════


def _get_l3_manual_skills_for_agent(
    agent: str,
    skill_map_data: dict,
) -> set[str]:
    """从 skill-map.yaml 获取指定 Agent 的所有 L3 manual 技能。"""
    skills_set: set[str] = set()
    for agent_name, cat_name, skill in iter_skills(skill_map_data):
        if agent_name != agent:
            continue
        layer_str = str(skill.get("layer", ""))
        if "/ load: manual" in layer_str or layer_str.startswith("3"):
            name = skill.get("name", "")
            if name:
                skills_set.add(name)
    return skills_set


def _get_agent_from_route_file(route_path: Path) -> str | None:
    """从 route 文件中读取 agent 名。"""
    try:
        data = read_yaml(str(route_path))
    except Exception:
        return None
    return data.get("agent") if isinstance(data, dict) else None


def _match_skills_for_pattern(pattern: str, available_skills: set[str]) -> list[str]:
    """按 pattern 语义匹配可用的 L3 manual 技能。

    策略：
    1. 对 _PATTERN_SKILL_MAP 中的每个关键词，检查 pattern 是否包含该关键词
    2. 返回匹配的技能中在 available_skills 存在的子集
    """
    matched: set[str] = set()
    pattern_lower = pattern.lower()

    for keyword, candidate_skills in _PATTERN_SKILL_MAP.items():
        if keyword.lower() in pattern_lower:
            for sk in candidate_skills:
                if sk in available_skills:
                    matched.add(sk)

    return sorted(matched)


def _preview_diff(
    agent: str,
    route_file: str,
    rule_idx: int,
    rule_data: dict,
    matched_skills: list[str],
) -> str:
    """生成单条规则的 diff 预览字符串。"""
    pattern = rule_data.get("pattern", "?")
    rule_type = rule_data.get("type", "?")
    return (
        f"  [{agent}] {route_file} rule[{rule_idx}] "
        f"(type={rule_type}, pattern='{pattern}'):\n"
        f"    skills: [] → {matched_skills}\n"
    )


def cmd_skill_patch_skills(args: argparse.Namespace) -> int:
    """批量修补路由规则中的空 skills 字段。"""
    is_preview = args.preview
    filter_agent = args.agent

    # ── 读取 skill-map.yaml ───────────────────────────────────
    if not SKILL_MAP.is_file():
        print(f"错误: skill-map.yaml 不存在: {SKILL_MAP}", file=sys.stderr)
        return 1

    try:
        skill_data = read_yaml(str(SKILL_MAP))
    except Exception as e:
        print(f"错误: 读取 skill-map.yaml 失败: {e}", file=sys.stderr)
        return 1

    # ── 收集所有 Agent 的 L3 manual 技能 ───────────────────────
    agent_skills: dict[str, set[str]] = {}
    for agent_name, cat_name, skill in iter_skills(skill_data):
        layer_str = str(skill.get("layer", ""))
        if "manual" not in layer_str and layer_str.strip() not in ("3",):
            continue
        if agent_name not in agent_skills:
            agent_skills[agent_name] = set()
        name = skill.get("name", "")
        if name:
            agent_skills[agent_name].add(name)

    if not agent_skills:
        print("没有找到任何 L3 manual 技能，跳过修补。")
        return 0

    # ── 遍历 route 文件 ────────────────────────────────────────
    if not ROUTES_DIR.is_dir():
        print(f"错误: routes 目录不存在: {ROUTES_DIR}", file=sys.stderr)
        return 1

    route_files = sorted(ROUTES_DIR.glob("*.yaml"))
    changes: list[tuple[Path, int, dict, list[str]]] = []  # (path, idx, rule, matched)

    for rfile in route_files:
        if rfile.name == "shared.yaml":
            continue

        try:
            route_data = read_yaml(str(rfile))
        except Exception:
            continue

        agent_name = route_data.get("agent") or rfile.stem
        if filter_agent and agent_name != filter_agent:
            continue

        if agent_name not in agent_skills:
            continue

        rules = route_data.get("rules", [])
        for idx, rule in enumerate(rules):
            if not isinstance(rule, dict):
                continue
            current_skills = rule.get("skills")
            # 只修补空 skills 且为正权重的规则
            if current_skills is not None and len(current_skills) > 0:
                continue
            if rule.get("weight", 0) <= 0:
                continue

            pattern = rule.get("pattern", "")
            matched = _match_skills_for_pattern(pattern, agent_skills[agent_name])
            if matched:
                changes.append((rfile, idx, rule, matched))

    if not changes:
        print("没有发现需要修补的空 skills 规则。")
        return 0

    # ── 预览 ────────────────────────────────────────────────────
    print(f"发现 {len(changes)} 条规则需要修补:\n")
    for rfile, idx, rule, matched in changes:
        agent_name = route_data.get("agent") or rfile.stem
        # 需要重新读取 agent 名
        rd = read_yaml(str(rfile))
        an = rd.get("agent") or rfile.stem
        print(_preview_diff(an, rfile.name, idx, rule, matched))

    if is_preview:
        print(f"\n预览完成，共 {len(changes)} 条规则将修改。")
        print("使用 --apply 执行写入。")
        return 0

    # ── 执行写入 ────────────────────────────────────────────────
    print("正在执行批量写入...\n")

    applied = 0
    for rfile, idx, rule, matched in changes:
        try:
            # 备份
            backup_file(str(rfile))

            # 重新读取确保一致性
            route_data = read_yaml(str(rfile))
            route_data["rules"][idx]["skills"] = matched
            write_yaml(str(rfile), route_data)
            applied += 1
        except Exception as e:
            print(f"  写入失败: {rfile.name} rule[{idx}]: {e}", file=sys.stderr)

    print(f"✓ 已修补 {applied}/{len(changes)} 条规则。")
    if applied < len(changes):
        print(f"  {len(changes) - applied} 条失败（见上方错误）", file=sys.stderr)
        return 1

    return 0
