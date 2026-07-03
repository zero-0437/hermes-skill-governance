#!/usr/bin/env python3
"""清理 /opt/data/.shared/ 中超过 48h 未修改的产出目录。"""
import time, shutil
from pathlib import Path

shared = Path("/opt/data/.shared")
if not shared.exists():
    exit(0)

now = time.time()
cutoff = 48 * 3600
cleaned = []

for child in shared.iterdir():
    if not child.is_dir():
        continue
    # 取目录自身的 mtime
    mtime = child.stat().st_mtime
    if now - mtime > cutoff:
        shutil.rmtree(child)
        cleaned.append(child.name)

if cleaned:
    print(f"清理 {len(cleaned)} 个过期产出目录: {', '.join(cleaned)}")
# 无输出 = 无事发生（watchdog 静默模式）
