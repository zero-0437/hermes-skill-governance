"""validate 子命令 — 全量验证

调用 validate-route-map.py + validate-skill-map.py 进行全量验证。
路径通过 hermes_mgmt.core.paths 集中管理。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any

from hermes_mgmt.core.paths import PROJECT_ROOT, SCRIPTS_DIR

# ── 帮助常量 ──────────────────────────────────────────────────────

_VALIDATE_HELP = """全量验证 — 调用 validate-route-map.py + validate-skill-map.py

对所有 Agent 的 route-map 和 skill-map 进行 12 维审计验证。
退出码: 0=OK, 1=WARN, 2=ERR
"""


# ═══════════════════════════════════════════════
# Parser 设置
# ═══════════════════════════════════════════════


def setup_validate_parser(subparsers: Any) -> None:
    """向根 subparsers 注册 validate 子命令。"""
    subparsers.add_parser(
        "validate",
        help="全量验证",
        description=_VALIDATE_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


# ═══════════════════════════════════════════════
# 命令执行函数
# ═══════════════════════════════════════════════


def _run_validation_script(
    script_name: str,
) -> tuple[int, dict[str, Any]]:
    """运行一个验证脚本，返回 (exit_code, parsed_json_output)。"""
    script_path = SCRIPTS_DIR / script_name
    if not script_path.is_file():
        print(f"  ✗ {script_name}: 脚本不存在 ({script_path})", file=sys.stderr)
        return (2, {"status": "ERR", "error": "脚本不存在"})

    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True, text=True, timeout=60,
            cwd=str(PROJECT_ROOT),
        )
    except subprocess.TimeoutExpired:
        print(f"  ✗ {script_name}: 执行超时（60s）", file=sys.stderr)
        return (2, {"status": "ERR", "error": "超时"})
    except FileNotFoundError:
        print(f"  ✗ {script_name}: python 解释器未找到", file=sys.stderr)
        return (2, {"status": "ERR", "error": "解释器未找到"})
    except Exception as e:
        print(f"  ✗ {script_name}: 执行异常: {e}", file=sys.stderr)
        return (2, {"status": "ERR", "error": str(e)})

    # 解析 JSON 输出
    try:
        report = json.loads(result.stdout) if result.stdout.strip() else {}
    except json.JSONDecodeError as e:
        print(f"  ⚠ {script_name}: 输出非 JSON（fallback 原始输出）")
        print(f"    stderr: {result.stderr.strip()[:500]}")
        print(f"    stdout: {result.stdout.strip()[:500]}")
        # 根据退出码构建简易报告
        report = {
            "status": "OK" if result.returncode == 0 else (
                "WARN" if result.returncode == 1 else "ERR"
            ),
            "errors": [],
            "warnings": [],
            "info": [],
        }

    return (result.returncode, report)


def cmd_validate(args: argparse.Namespace) -> int:
    """全量验证 — 运行 route-map 和 skill-map 验证脚本。"""
    print("=" * 60)
    print("  全量验证")
    print("=" * 60)
    print()

    scripts = [
        ("validate-route-map.py", "route-map 验证"),
        ("validate-skill-map.py", "skill-map 验证"),
    ]

    has_errors = False
    has_warnings = False
    all_reports: dict[str, dict[str, Any]] = {}

    for script_name, label in scripts:
        print(f"▸ {label} ({script_name})")
        print("-" * 40)

        exit_code, report = _run_validation_script(script_name)
        all_reports[script_name] = report

        status = report.get("status", "?")
        err_count = len(report.get("errors", [])) if isinstance(report.get("errors"), list) else report.get("errors", 0)
        warn_count = len(report.get("warnings", [])) if isinstance(report.get("warnings"), list) else report.get("warnings", 0)
        info_count = len(report.get("info", [])) if isinstance(report.get("info"), list) else report.get("info", 0)

        # 状态图标
        status_icon = "✓" if status == "OK" else ("⚠" if status == "WARN" else "✗")
        print(f"  {status_icon} 状态: {status}")
        print(f"  errors={err_count}, warnings={warn_count}, info={info_count}")

        # 打印错误详情
        errors_list = report.get("errors_list") or report.get("errors") or []
        if isinstance(errors_list, list) and errors_list:
            print(f"\n  错误详情:")
            for e in errors_list:
                if isinstance(e, dict):
                    msg = e.get("message", str(e))
                else:
                    msg = str(e)
                print(f"    ✗ {msg}")

        # 打印警告详情
        warnings_list = report.get("warnings_list") or report.get("warnings") or []
        if isinstance(warnings_list, list) and warnings_list:
            print(f"\n  警告详情:")
            for w in warnings_list:
                if isinstance(w, dict):
                    msg = w.get("message", str(w))
                else:
                    msg = str(w)
                print(f"    ⚠ {msg}")

        print()

        if exit_code == 2:
            has_errors = True
        elif exit_code == 1:
            has_warnings = True

    # ── 汇总 ──────────────────────────────────────────────────
    print("=" * 60)
    if has_errors:
        print("  结果: ✗ 存在阻塞性错误（ERR）")
        print("=" * 60)
        return 2
    elif has_warnings:
        print("  结果: ⚠ 通过（含警告）")
        print("=" * 60)
        return 1
    else:
        print("  结果: ✓ 全部通过")
        print("=" * 60)
        return 0
