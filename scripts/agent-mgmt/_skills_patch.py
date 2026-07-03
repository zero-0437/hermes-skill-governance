#!/usr/bin/env python3
"""
_skills_patch.py — 批量补 route-map 规则中的 skills 字段

功能：
  - 从 skill-map.yaml 读取每个 Agent 的 L3 manual 技能列表
  - 对 route-map/routes/*.yaml 中 skills: [] 的正权重规则，
    按 pattern 语义匹配 L3 skills（只匹配该 Agent 确实拥有的 L3 skill）
  - 预览模式（--preview）：输出 diff，不写文件
  - 执行模式（--apply）：实际写入 YAML 文件，备份原文件
  - --agent 参数只处理指定 Agent

依赖：PyYAML（读）、ruamel.yaml（写，保留注释与格式）

用法：
  python _skills_patch.py --preview              # 预览全部
  python _skills_patch.py --preview --agent X    # 预览指定 Agent
  python _skills_patch.py --apply                # 执行全部
  python _skills_patch.py --apply --agent X      # 执行指定 Agent
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import yaml
from ruamel.yaml import YAML

# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------

_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
_SKILL_MAP_PATH: Path = _PROJECT_ROOT / "skill-map.yaml"
_ROUTES_DIR: Path = _PROJECT_ROOT / "route-map" / "routes"
_BACKUP_ROOT: Path = Path("/tmp/hermes-mgmt-rollback")

# ---------------------------------------------------------------------------
# Pattern → Skills 语义映射表
# ---------------------------------------------------------------------------
# 每条：(关键词列表, 建议技能名列表)
# 匹配规则：pattern 文本包含任意关键词即命中，将建议技能与该 Agent 的
# L3 manual 列表求交集后赋值。
# 建议技能为 [] 表示「明确留空」——即使 pattern 命中也不补 skills。

_PATTERN_SKILL_MAP: list[tuple[list[str], list[str]]] = [
    # 搜索类
    (["搜索"], ["github-search", "arxiv", "blogwatcher"]),
    (["查询"], ["github-search", "blogwatcher"]),
    # 文档/写作类
    (["文档", "写", "readme", "教程", "指南", "手册"], ["doc-coauthoring", "engineering-technical-writer"]),
    # 记忆/知识类
    (["记忆", "知识库", "笔记"], ["llm-wiki", "obsidian"]),
    # 设计/界面类
    (["设计", "界面", "UI", "布局", "前端", "图表", "视觉", "图标", "草图", "线框图", "海报", "动效", "动画", "原型", "设计稿", "美观", "美化", "配色", "样式", "组件", "响应式"],
     ["taste-skill", "claude-design", "excalidraw"]),
    # 测试/验收类
    (["测试", "验收", "检查", "回归测试", "验证", "集成测试", "端到端"], ["dogfood"]),
    # 文件操作类
    (["文件", "目录", "大文件", "备份", "移动", "复制", "文件操作", "目录结构", "终端", "命令行", "脚本执行"],
     ["token-efficient-file-ops"]),
    # 远程/SSH/NAS
    (["SSH", "远程", "群晖", "NAS", "存储", "磁盘", "硬盘", "卷", "共享文件夹"],
     ["ssh-remote-access"]),
    # 分析/数据类
    (["分析", "数据", "调查", "检索", "查找", "研究", "论文", "新闻", "资料", "趋势", "报告", "对比", "统计数据"],
     ["github-search", "jupyter-live-kernel"]),
    # 故障/诊断/安全
    (["故障", "诊断", "错误", "崩溃", "死锁", "根因", "漏洞", "审查", "审核", "审计", "安全", "风险", "异常", "内存泄漏", "复盘", "事故分析"],
     ["network-debugging", "github-code-review", "engineering-security-engineer"]),
    # 提示词 → 明确留空
    (["提示词", "prompt", "角色定义", "提示工程"], []),
    # 技能创作
    (["技能", "创建技能", "训练", "新增技能", "技能树"], ["skill-creator"]),
    # 架构/构建类
    (["构建", "架构", "方案", "一致", "治理", "拓扑", "拆解", "技术选型", "可行性", "跨域", "冲突"],
     ["architecture-integrity-check", "multi-agent-swarm"]),
    # 集成 → 明确留空
    (["集成", "端到端"], []),
]

# ---------------------------------------------------------------------------
# Layer 解析正则（与 _binding_table.py 一致）
# ---------------------------------------------------------------------------

_LAYER_PATTERN = re.compile(
    r"^\s*(?P<layer>\d+)\s*/\s*load\s*:\s*(?P<load>auto|manual)\s*$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# 核心函数
# ---------------------------------------------------------------------------


def load_skill_map(path: Path) -> dict[str, list[str]]:
    """从 skill-map.yaml 读取每个 Agent 的 L3 manual 技能列表。

    Args:
        path: skill-map.yaml 路径。

    Returns:
        {agent_name: [skill_name, ...]} — 仅包含 L3 manual 技能。
        不含 L2 auto、L1 manual 或 shared 段技能。
    """
    if not path.is_file():
        print(f"[WARN] skill-map.yaml not found: {path}", file=sys.stderr)
        return {}

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        return {}

    agents = data.get("agents", {})
    if not isinstance(agents, dict):
        return {}

    result: dict[str, list[str]] = {}

    for agent_name, agent_data in agents.items():
        if not isinstance(agent_data, dict):
            continue
        categories = agent_data.get("categories", {})
        if not isinstance(categories, dict):
            continue

        l3_manual: list[str] = []
        for _cat_name, skills in categories.items():
            if not isinstance(skills, list):
                continue
            for skill in skills:
                if not isinstance(skill, dict):
                    continue
                skill_name = skill.get("name", "")
                if not isinstance(skill_name, str) or not skill_name:
                    continue
                layer_raw = str(skill.get("layer", ""))
                m = _LAYER_PATTERN.match(layer_raw)
                if m and m.group("layer") == "3" and m.group("load").lower() == "manual":
                    l3_manual.append(skill_name)

        if l3_manual:
            result[agent_name] = l3_manual

    return result


def match_skills(
    pattern: str,
    agent_name: str,
    skill_map: dict[str, list[str]],
) -> list[str]:
    """按 pattern 语义匹配 L3 skills。

    对 _PATTERN_SKILL_MAP 中每条 (keywords, suggested_skills) 映射，
    检查 pattern 是否包含任意 keyword。若匹配则将 suggested_skills 中
    属于该 Agent L3 manual 的技能加入结果。

    Args:
        pattern:   规则 pattern 文本（已转为 str）。
        agent_name: Agent 名称。
        skill_map: load_skill_map() 返回的 {agent: [skills]}。

    Returns:
        匹配到的技能列表（去重，按映射表顺序优先）。
    """
    agent_skills = skill_map.get(agent_name, [])
    if not agent_skills:
        return []

    matched: list[str] = []
    seen: set[str] = set()
    pattern_lower = pattern.lower()

    for keywords, suggested in _PATTERN_SKILL_MAP:
        # 如果建议技能为空，说明该关键词类别「明确留空」，跳过
        if not suggested:
            continue
        if any(kw.lower() in pattern_lower for kw in keywords):
            for sk in suggested:
                if sk in agent_skills and sk not in seen:
                    matched.append(sk)
                    seen.add(sk)

    return matched


def _is_target_rule(rule: dict) -> bool:
    """判断规则是否需要补 skills。

    条件：
      - skills 是空列表
      - weight 为正数（排除负权重误匹配防护规则）
    """
    skills = rule.get("skills")
    if not isinstance(skills, list) or len(skills) > 0:
        return False
    weight = rule.get("weight", 0)
    if not isinstance(weight, (int, float)) or weight <= 0:
        return False
    return True


def _get_pattern_text(rule: dict) -> str:
    """从 rule 中提取 pattern 文本用于匹配。"""
    pattern = rule.get("pattern", "")
    if isinstance(pattern, list):
        pattern = " ".join(str(p) for p in pattern)
    return str(pattern)


def _backup_file(src: Path, backup_root: Path) -> Path | None:
    """备份文件到 backup_root/<timestamp>/<relative_path>。"""
    ts = f"{int(time.time())}_{os.getpid()}"
    if src.is_absolute():
        rel = src.relative_to(src.anchor)
    else:
        rel = Path.cwd().relative_to(Path.cwd().anchor) / src
    dest = backup_root / ts / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def patch_skills_preview(
    routes_dir: Path,
    skill_map: dict[str, list[str]],
    agent_filter: str | None = None,
) -> list[dict]:
    """预览模式：扫描 route 文件，输出每条规则原本 vs 修改后的 diff。

    Args:
        routes_dir:   route-map/routes/ 目录。
        skill_map:    load_skill_map() 返回的 skill 映射。
        agent_filter: 可选 Agent 名称过滤。

    Returns:
        [{"file": str, "agent": str, "pattern": str,
          "old_skills": [], "new_skills": [...]}, ...]
    """
    changes: list[dict] = []
    route_files = sorted(routes_dir.glob("*.yaml"))

    for rpath in route_files:
        with open(rpath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            continue

        agent_name = data.get("agent", "")
        if not agent_name:
            continue

        if agent_filter and agent_name != agent_filter:
            continue

        rules = data.get("rules", [])
        if not isinstance(rules, list):
            continue

        for rule in rules:
            if not isinstance(rule, dict):
                continue
            if not _is_target_rule(rule):
                continue

            pattern = _get_pattern_text(rule)
            new_skills = match_skills(pattern, agent_name, skill_map)

            if new_skills:
                changes.append({
                    "file": rpath.name,
                    "agent": agent_name,
                    "pattern": pattern,
                    "old_skills": [],
                    "new_skills": new_skills,
                })

    return changes


def patch_skills_apply(
    routes_dir: Path,
    skill_map: dict[str, list[str]],
    agent_filter: str | None = None,
    backup_root: Path | None = None,
) -> int:
    """执行模式：实际写入 YAML 文件，备份原文件。

    使用 ruamel.yaml（RoundTrip）保留注释与格式。

    Args:
        routes_dir:   route-map/routes/ 目录。
        skill_map:    load_skill_map() 返回的 skill 映射。
        agent_filter: 可选 Agent 名称过滤。
        backup_root:  备份根目录，默认 /tmp/hermes-mgmt-rollback。

    Returns:
        修改的文件数量。
    """
    if backup_root is None:
        backup_root = _BACKUP_ROOT

    ryaml = YAML(typ="rt")
    ryaml.indent(mapping=2, sequence=4, offset=2)

    modified_count = 0
    route_files = sorted(routes_dir.glob("*.yaml"))

    for rpath in route_files:
        with open(rpath, "r", encoding="utf-8") as f:
            data = ryaml.load(f)

        if not isinstance(data, dict):
            continue

        agent_name = data.get("agent", "")
        if not agent_name:
            continue

        if agent_filter and agent_name != agent_filter:
            continue

        rules = data.get("rules", [])
        if not isinstance(rules, list):
            continue

        file_modified = False
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            if not _is_target_rule(rule):
                continue

            pattern = _get_pattern_text(rule)
            new_skills = match_skills(pattern, agent_name, skill_map)

            if new_skills:
                rule["skills"] = new_skills
                file_modified = True

        if file_modified:
            # 备份原文件
            try:
                _backup_file(rpath, backup_root)
            except Exception as e:
                print(f"[WARN] 备份失败 {rpath}: {e}", file=sys.stderr)

            # 用 ruamel.yaml 写回（保留注释）
            with open(rpath, "w", encoding="utf-8") as f:
                ryaml.dump(data, f)

            modified_count += 1
            print(f"[OK] 已修补: {rpath.name} (agent: {agent_name})")

    return modified_count


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="批量补 route-map 规则中的 skills 字段",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  %(prog)s --preview                 # 预览全部变化\n"
            "  %(prog)s --preview --agent programmer  # 只看 programmer\n"
            "  %(prog)s --apply                   # 执行全部修补\n"
            "  %(prog)s --apply --agent ui-designer   # 只修补 ui-designer\n"
        ),
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="预览模式：输出每条规则原本 vs 修改后的 diff，不写文件",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="执行模式：实际写入 YAML 文件（自动备份到 /tmp/hermes-mgmt-rollback/）",
    )
    parser.add_argument(
        "--agent",
        type=str,
        default=None,
        metavar="NAME",
        help="只处理指定 Agent（如 --agent programmer）",
    )

    args = parser.parse_args()

    if not args.preview and not args.apply:
        parser.print_help()
        print("\n[ERROR] 请指定 --preview 或 --apply", file=sys.stderr)
        return 1

    # ── 加载 skill-map ──────────────────────────────────
    skill_map = load_skill_map(_SKILL_MAP_PATH)
    if not skill_map:
        print("[ERROR] skill-map.yaml 中未发现 L3 manual 技能", file=sys.stderr)
        return 1

    print(f"[INFO] 从 skill-map.yaml 读取了 {len(skill_map)} 个 Agent 的 L3 manual 技能:")
    for agent, skills in sorted(skill_map.items()):
        print(f"       {agent}: {skills}")

    # 检查 routes 目录
    if not _ROUTES_DIR.is_dir():
        print(f"[ERROR] route 目录不存在: {_ROUTES_DIR}", file=sys.stderr)
        return 1

    # ── 预览模式 ─────────────────────────────────────────
    if args.preview:
        print("\n[PREVIEW] 扫描 route 文件…\n")
        changes = patch_skills_preview(_ROUTES_DIR, skill_map, args.agent)

        if not changes:
            print("[INFO] 未发现需要修补的规则。")
            return 0

        for c in changes:
            print(f"  文件:     {c['file']}")
            print(f"  Agent:    {c['agent']}")
            print(f"  Pattern:  {c['pattern']}")
            print(f"  Skills:   [] → {c['new_skills']}")
            print()
        print(f"[SUMMARY] 共 {len(changes)} 条规则将被修补。")
        return 0

    # ── 执行模式 ─────────────────────────────────────────
    if args.apply:
        print("\n[APPLY] 开始修补 route 文件…\n")
        count = patch_skills_apply(_ROUTES_DIR, skill_map, args.agent)
        print(f"\n[DONE] 共修改 {count} 个文件。")
        print(f"[INFO] 备份已保存至 {_BACKUP_ROOT}/")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
