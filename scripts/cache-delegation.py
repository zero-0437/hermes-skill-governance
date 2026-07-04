#!/usr/bin/env python3
"""委派缓存脚本 — 管理 agent session 缓存，避免重复注入上下文。"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

CACHE_DIR = "/opt/data/contexts/agent-session-cache"
CONTEXT_VERSION = "v1.14"
STALE_HOURS = 72


def usage():
    print("用法:", file=sys.stderr)
    print("  cache-delegation.py check <agent_name>", file=sys.stderr)
    print("  cache-delegation.py update <agent_name> <task_summary>", file=sys.stderr)
    print("  cache-delegation.py warm", file=sys.stderr)
    sys.exit(3)


def cache_path(agent_name: str) -> str:
    return os.path.join(CACHE_DIR, f"{agent_name}.json")


def check(agent_name: str) -> None:
    path = cache_path(agent_name)
    if not os.path.isfile(path):
        print("missing")
        sys.exit(2)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        print("stale")
        sys.exit(1)

    updated_str = data.get("updated_at", "")
    if not updated_str:
        print("stale")
        sys.exit(1)

    # 解析 ISO 8601 时间戳
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            updated = datetime.strptime(updated_str, fmt)
            break
        except ValueError:
            continue
    else:
        print("stale")
        sys.exit(1)

    # 无时区则视为 UTC
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    age = now - updated
    if age >= timedelta(hours=STALE_HOURS):
        print("stale")
        sys.exit(1)

    summary = data.get("task_summary", "")
    print(f"fresh {summary}")
    sys.exit(0)


def update(agent_name: str, task_summary: str) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    payload = {
        "agent": agent_name,
        "task_summary": task_summary,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "context_version": CONTEXT_VERSION,
    }
    path = cache_path(agent_name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("ok")


WARM_AGENTS = [
    "programmer", "data-analyst", "error-analyst", "ui-designer",
    "civil-servant", "memory-agent", "复盘分析师", "synology-helper",
    "teacher", "document-processor", "file-ops", "pm-agent",
]


def warm() -> None:
    """为所有 Agent 创建缓存预热条目"""
    for agent_name in WARM_AGENTS:
        update(agent_name, "缓存预热")
        print(f"warmed {agent_name}", file=sys.stderr)


def main() -> None:
    if len(sys.argv) < 2:
        usage()

    subcmd = sys.argv[1]
    if subcmd == "check":
        if len(sys.argv) != 3:
            usage()
        check(sys.argv[2])
    elif subcmd == "update":
        if len(sys.argv) < 4:
            usage()
        agent_name = sys.argv[2]
        task_summary = " ".join(sys.argv[3:])
        update(agent_name, task_summary)
    elif subcmd == "warm":
        warm()
    else:
        usage()


if __name__ == "__main__":
    main()
