#!/usr/bin/env python3
"""
checker_engine.py — Chain Completion Gate 结构化检查器引擎

提供装饰器注册、统一执行入口、预置检查器和旧 shell 兼容层。
取代裸 shell verify_command，支持结构化参数和 BLOCKED 状态桥接。

用法:
    from scripts.checker_engine import register_checker, run_check, run_shell, list_checkers

    @register_checker("my_check")
    def _my_check(path: str, min: int = 1) -> dict:
        ...
    result = run_check("my_check", path="some/file")
"""

import glob
import inspect
import os
import shlex
import subprocess
import sys as _sys
import time
import warnings
from typing import Any, Callable, Optional

# ── sys.path 补丁：确保 scripts/ 目录和父级目录可访问 ──
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in _sys.path:
    _sys.path.insert(0, _SCRIPTS_DIR)
_PARENT_DIR = os.path.dirname(_SCRIPTS_DIR)
if _PARENT_DIR not in _sys.path:
    _sys.path.insert(0, _PARENT_DIR)

# ── TypedDict 定义 ────────────────────────────────────

try:
    from typing import TypedDict
except ImportError:
    # Python < 3.8 回退：用 dict 类代替
    TypedDict = dict  # type: ignore


class CheckResult(TypedDict):
    """单个 checker 执行结果的类型定义。"""
    name: str          # checker 名称
    passed: bool       # 是否通过
    details: str       # 详细说明（供诊断）
    extra: dict        # 额外信息（如匹配文件列表）


# ── 注册表 ────────────────────────────────────────────

_CHECKERS: dict[str, dict] = {}
"""全局检查器注册表。key: checker 名称, value: {"fn": func, "doc": str, "name": str}"""


def _get_source_file() -> str:
    """返回当前模块的文件路径，供内省用。"""
    return __file__


# ── 装饰器 ────────────────────────────────────────────

def register_checker(name: Optional[str] = None) -> Callable:
    """将函数注册为 checker。

    name 不传时使用函数名（snake_case）。
    注册后可通过 run_check(name) 调用。
    重名时抛出 ValueError。

    用法:
        @register_checker("file_exists")
        def _check_file_exists(path: str, min: int = 1) -> dict:
            ...
    """
    def decorator(func: Callable) -> Callable:
        nonlocal name
        if name is None:
            name = func.__name__
        if name in _CHECKERS:
            raise ValueError(f"Checker '{name}' 已注册")
        _CHECKERS[name] = {
            "fn": func,
            "doc": func.__doc__ or "",
            "name": name,
        }
        return func
    return decorator


# ── 统一执行入口 ─────────────────────────────────────

def run_check(name: str, **kwargs) -> CheckResult:
    """按名称查找已注册 checker 并执行。

    Args:
        name: checker 名称（注册时指定）
        **kwargs: 传给 checker 函数的参数

    Returns:
        CheckResult 字典：
            - name: checker 名称
            - passed: 是否通过
            - details: 详细说明
            - extra: 额外信息

    Raises:
        KeyError: checker 未注册
    """
    if name not in _CHECKERS:
        raise KeyError(f"Checker '{name}' 未注册。可用: {list(_CHECKERS.keys())}")
    entry = _CHECKERS[name]
    fn = entry["fn"]

    try:
        result = fn(**kwargs)
    except TypeError as e:
        return {
            "name": name,
            "passed": False,
            "details": f"参数不匹配: {e}",
            "extra": {"kwargs": kwargs},
        }
    except Exception as e:
        return {
            "name": name,
            "passed": False,
            "details": str(e),
            "extra": {"kwargs": kwargs},
        }

    # 确保返回的是 CheckResult 类型
    if isinstance(result, dict):
        return {
            "name": result.get("name", name),
            "passed": result.get("passed", False),
            "details": result.get("details", ""),
            "extra": result.get("extra", {}),
        }
    return {
        "name": name,
        "passed": bool(result),
        "details": str(result),
        "extra": {},
    }


# ── Shell 兼容层 ─────────────────────────────────────

def run_shell(cmd: str, timeout: int = 30) -> CheckResult:
    """封装 subprocess.run() 执行旧 verify_command。

    向 stderr 打印 DeprecationWarning。
    返回格式与 run_check 一致：
        - passed = (exit_code == 0)
        - details = stdout + stderr（截断至 2000 字符）

    Args:
        cmd: shell 命令字符串
        timeout: 超时秒数（默认 30）

    Returns:
        CheckResult 字典
    """
    warnings.warn(
        f"verify_command 已弃用，请迁移到结构化 checker: {cmd}",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        needs_shell = any(op in cmd for op in ("|", ">", "<", ";&", "&&"))
        if needs_shell:
            cp = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                timeout=timeout,
                text=True,
            )
        else:
            cmd_parts = shlex.split(cmd)
            cp = subprocess.run(
                cmd_parts,
                shell=False,
                capture_output=True,
                timeout=timeout,
                text=True,
            )
        output = (cp.stdout + cp.stderr)[:2000]
        return {
            "name": "__shell__",
            "passed": cp.returncode == 0,
            "details": output,
            "extra": {"exit_code": cp.returncode},
        }
    except subprocess.TimeoutExpired:
        return {
            "name": "__shell__",
            "passed": False,
            "details": f"Command timed out after {timeout}s",
            "extra": {"exit_code": -1},
        }
    except Exception as e:
        return {
            "name": "__shell__",
            "passed": False,
            "details": str(e),
            "extra": {"exit_code": -1},
        }


# ── 内省 ─────────────────────────────────────────────

def list_checkers() -> list[dict]:
    """返回所有已注册 checker 的元信息列表。

    每个条目：
        {
            "name": "file_exists",
            "doc": "检查路径是否存在，支持 glob pattern",
            "params": {"path": "str (required)", "min": "int (default=1)"}
        }
    """
    result = []
    for check_name, entry in _CHECKERS.items():
        fn = entry["fn"]
        sig = inspect.signature(fn)
        params = {}
        for param_name, param in sig.parameters.items():
            if param.default is inspect.Parameter.empty:
                params[param_name] = f"{param.annotation.__name__ if param.annotation is not inspect.Parameter.empty else 'any'} (required)"
            else:
                default_repr = repr(param.default)
                params[param_name] = f"{param.annotation.__name__ if param.annotation is not inspect.Parameter.empty else 'any'} (default={default_repr})"
        doc_line = (entry["doc"] or "").split("\n")[0].strip()
        result.append({
            "name": check_name,
            "doc": doc_line,
            "params": params,
        })
    return result


# ══════════════════════════════════════════════════════
# 预置检查器
# ══════════════════════════════════════════════════════


@register_checker("file_exists")
def _check_file_exists(path: str, min: int = 1) -> dict:
    """检查路径是否存在，支持 glob pattern。

    先用 os.path.exists() 尝试字面匹配，若失败则用 glob.glob() 展开。
    匹配数 < min 时返回 passed=False。

    Args:
        path: 文件/目录路径或 glob pattern
        min: 最小匹配文件数（默认 1）

    Returns:
        包含 matched_files 和 count 的 dict
    """
    # 先尝试字面路径
    if os.path.exists(path):
        return {
            "name": "file_exists",
            "passed": True,
            "details": f"路径存在: {path}",
            "extra": {"matched_files": [path], "count": 1},
        }

    # 检测是否为 glob pattern
    is_glob = any(ch in path for ch in ("*", "?", "["))
    if not is_glob:
        return {
            "name": "file_exists",
            "passed": False,
            "details": f"路径不存在: {path}",
            "extra": {"matched_files": [], "count": 0},
        }

    # glob 展开
    matched = glob.glob(path, recursive=True)
    matched = [m for m in matched if os.path.exists(m)]
    count = len(matched)

    if count == 0:
        return {
            "name": "file_exists",
            "passed": False,
            "details": f"未匹配到任何文件 (glob: {path})",
            "extra": {"matched_files": [], "count": 0},
        }

    if count < min:
        return {
            "name": "file_exists",
            "passed": False,
            "details": f"匹配到 {count} 个文件，要求至少 {min} 个 (glob: {path})",
            "extra": {"matched_files": matched, "count": count},
        }

    return {
        "name": "file_exists",
        "passed": True,
        "details": f"匹配到 {count} 个文件 (glob: {path})",
        "extra": {"matched_files": matched, "count": count},
    }


@register_checker("count_files")
def _count_files(glob_pattern: str, op: str, val: int) -> dict:
    """按 glob pattern 统计文件数，与预期值比较。

    支持操作符: eq, ne, gt, gte, lt, lte

    Args:
        glob_pattern: glob pattern（如 docs/specs/*.md）
        op: 比较操作符 (eq/ne/gt/gte/lt/lte)
        val: 预期值

    Returns:
        包含 matched_count, glob, op, val 的 dict
    """
    matched = glob.glob(glob_pattern, recursive=True)
    matched = [m for m in matched if os.path.exists(m)]
    count = len(matched)

    ops = {
        "eq": count == val,
        "ne": count != val,
        "gt": count > val,
        "gte": count >= val,
        "lt": count < val,
        "lte": count <= val,
    }

    if op not in ops:
        return {
            "name": "count_files",
            "passed": False,
            "details": f"不支持的操作符: {op}，支持: {list(ops.keys())}",
            "extra": {"matched_count": count, "glob": glob_pattern, "op": op, "val": val},
        }

    passed = ops[op]
    status = "通过" if passed else "失败"
    return {
        "name": "count_files",
        "passed": passed,
        "details": f"匹配到 {count} 个文件 (glob: {glob_pattern}, op: {op}, val: {val}) — {status}",
        "extra": {"matched_count": count, "glob": glob_pattern, "op": op, "val": val},
    }


@register_checker("true")
def _true() -> dict:
    """始终通过。

    用于占位或调试。
    """
    return {
        "name": "true",
        "passed": True,
        "details": "始终通过",
        "extra": {},
    }
