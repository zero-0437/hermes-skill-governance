#!/usr/bin/env python3
"""
analyze-route-log.py — 路由日志分析维护脚本

读取 logs/route-engine.jsonl，输出统计摘要、Agent 排名、
Flagged 条目清单及改进建议。
"""

import json
import os
from collections import Counter, defaultdict

_LOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "logs", "route-engine.jsonl"
)


def load_entries():
    """加载所有日志条目"""
    if not os.path.exists(_LOG_PATH):
        print(f"[错误] 日志文件不存在: {_LOG_PATH}")
        return []

    entries = []
    with open(_LOG_PATH, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[警告] 第 {lineno} 行格式错误，已跳过: {e}")

    return entries


def analyze(entries):
    """分析日志条目并输出报告"""
    if not entries:
        print("没有日志数据可分析。")
        return

    total = len(entries)

    # ── 统计按 method ──────────────────────────────────────────────
    method_counter = Counter(e.get("method", "unknown") for e in entries)
    auto_count = method_counter.get("auto", 0)
    fallback_count = method_counter.get("llm_fallback", 0)
    tiebreak_count = method_counter.get("auto_tiebreak", 0)

    # ── Flagged 统计 ──────────────────────────────────────────────
    flagged_entries = [e for e in entries if e.get("flagged")]
    flagged_count = len(flagged_entries)

    # ── 按 Agent 调用次数 ──────────────────────────────────────────
    agent_counter = Counter(e.get("agent", "") for e in entries)
    agent_sorted = agent_counter.most_common()

    # ── 按 Agent 回退率 ───────────────────────────────────────────
    agent_fallback = defaultdict(lambda: {"total": 0, "fallback": 0})
    for e in entries:
        agent = e.get("agent", "")
        agent_fallback[agent]["total"] += 1
        if e.get("method") == "llm_fallback":
            agent_fallback[agent]["fallback"] += 1

    # ── 时间范围 ──────────────────────────────────────────────────
    timestamps = [e.get("ts", "") for e in entries if e.get("ts")]
    ts_min = min(timestamps)[:10] if timestamps else "N/A"
    ts_max = max(timestamps)[:10] if timestamps else "N/A"

    # ══════════════════════════════════════════════════════════════
    #  输出报告
    # ══════════════════════════════════════════════════════════════
    print("=== 路由日志分析报告 ===")
    print(f"统计周期: {ts_min} ~ {ts_max}")
    print(f"总路由次数: {total}")
    print(f"auto: {auto_count} ({auto_count / total * 100:.1f}%)" if total else "auto: 0 (0.0%)")
    print(f"llm_fallback: {fallback_count} ({fallback_count / total * 100:.1f}%)" if total else "llm_fallback: 0 (0.0%)")
    print(f"auto_tiebreak: {tiebreak_count} ({tiebreak_count / total * 100:.1f}%)" if total else "auto_tiebreak: 0 (0.0%)")
    print(f"flagged: {flagged_count} ({flagged_count / total * 100:.1f}%)")

    # ── Top Agent ──────────────────────────────────────────────────
    print(f"\nTop Agent 调用:")
    for agent, count in agent_sorted:
        print(f"  {agent}: {count}")

    # ── Flagged 条目 ──────────────────────────────────────────────
    if flagged_entries:
        print(f"\nFlagged 条目:")
        for e in flagged_entries:
            reason = e.get("flag_reason", "?")
            snippet = e.get("input", "")[:40]
            agent = e.get("agent", "?")
            conf = e.get("confidence", "?")
            print(f"  [{reason}] \"{snippet}\" → {agent} (conf={conf})")

    # ── 改进建议 ──────────────────────────────────────────────────
    print(f"\n改进建议:")
    suggestions = []
    for agent, stats in sorted(agent_fallback.items(), key=lambda x: x[1]["fallback"] / max(x[1]["total"], 1), reverse=True):
        total_a = stats["total"]
        fall_a = stats["fallback"]
        rate = fall_a / total_a if total_a else 0
        if rate >= 0.15 and total_a >= 3:
            if fall_a == total_a:
                suggestions.append(
                    f"  - {agent} 回退率 {rate:.0%}（共 {total_a} 次全部回退），"
                    f"建议补充\"{agent.replace('-', '')}\"相关关键词规则"
                )
            else:
                suggestions.append(
                    f"  - {agent} 回退率 {rate:.0%}（{fall_a}/{total_a}），"
                    f"建议补充匹配关键词以降低回退"
                )

    # 额外建议：flagged 比例过高
    if flagged_count > 0 and total > 0:
        flagged_rate = flagged_count / total
        if flagged_rate > 0.2:
            suggestions.append(
                f"  - 异常标记比例 {flagged_rate:.0%}，建议审查路由规则阈值"
            )

    if not suggestions:
        print("  (暂无改进建议)")
    else:
        for s in suggestions:
            print(s)


def main():
    entries = load_entries()
    analyze(entries)


if __name__ == "__main__":
    main()
