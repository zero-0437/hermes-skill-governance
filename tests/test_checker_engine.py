"""单元测试：checker_engine.py — Chain Completion Gate"""

import os
import sys
import tempfile
import pytest

# Ensure the project root is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.checker_engine import (
    register_checker,
    run_check,
    run_shell,
    list_checkers,
    _CHECKERS,
    CheckResult,
)


# ══════════════════════════════════════════════════════════════════
# 1. @register_checker 注册后 run_check() 可调用
# ══════════════════════════════════════════════════════════════════
def test_register_and_run():
    """@register_checker 注册后 run_check() 可调用"""
    # 使用唯一名称避免污染其他测试
    name = "_test_reg_1"

    @register_checker(name)
    def _check():
        return {"name": name, "passed": True, "details": "ok", "extra": {}}

    result = run_check(name)
    assert result["passed"] is True
    assert result["name"] == name


# ══════════════════════════════════════════════════════════════════
# 2. @register_checker("custom_name") 自定义名称
# ══════════════════════════════════════════════════════════════════
def test_register_custom_name():
    """@register_checker(\"custom_name\") 自定义名称"""

    @register_checker("my_custom_checker")
    def _some_func():
        return {"name": "my_custom_checker", "passed": True, "details": "custom", "extra": {}}

    result = run_check("my_custom_checker")
    assert result["passed"] is True
    assert result["name"] == "my_custom_checker"


# ══════════════════════════════════════════════════════════════════
# 3. run_check() 传入不存在的 checker → KeyError
# ══════════════════════════════════════════════════════════════════
def test_run_check_nonexistent():
    """不存在的 checker → KeyError"""
    with pytest.raises(KeyError):
        run_check("__nonexistent_checker_xyz__")


# ══════════════════════════════════════════════════════════════════
# 4. run_check() 参数不匹配 → passed=False（不抛异常）
# ══════════════════════════════════════════════════════════════════
def test_run_check_type_error():
    """参数不匹配 → passed=False（不抛异常）"""

    @register_checker("_test_type_err")
    def _check_required(x: str):
        return {"name": "_test_type_err", "passed": True, "details": "ok", "extra": {}}

    # 缺少必须参数 x
    result = run_check("_test_type_err")
    assert result["passed"] is False
    assert "参数不匹配" in result["details"]


# ══════════════════════════════════════════════════════════════════
# 5. file_exists 字面路径存在
# ══════════════════════════════════════════════════════════════════
def test_file_exists_literal():
    """file_exists 字面路径存在"""
    result = run_check("file_exists", path=__file__)
    assert result["passed"] is True
    assert result["extra"]["count"] >= 1


# ══════════════════════════════════════════════════════════════════
# 6. file_exists 字面路径不存在
# ══════════════════════════════════════════════════════════════════
def test_file_exists_missing():
    """file_exists 字面路径不存在"""
    result = run_check("file_exists", path="/tmp/__definitely_not_exist_xyz__")
    assert result["passed"] is False
    assert "不存在" in result["details"]


# ══════════════════════════════════════════════════════════════════
# 7. file_exists glob pattern 匹配
# ══════════════════════════════════════════════════════════════════
def test_file_exists_glob():
    """file_exists glob pattern 匹配"""
    result = run_check("file_exists", path="scripts/*.py")
    assert result["passed"] is True
    assert result["extra"]["count"] >= 1


# ══════════════════════════════════════════════════════════════════
# 8. file_exists glob pattern 不匹配
# ══════════════════════════════════════════════════════════════════
def test_file_exists_glob_empty():
    """file_exists glob pattern 不匹配"""
    result = run_check("file_exists", path="__nonexistent_glob_xyz__/*.py")
    assert result["passed"] is False
    assert "未匹配" in result["details"]


# ══════════════════════════════════════════════════════════════════
# 9. file_exists min > matched_count → passed=False
# ══════════════════════════════════════════════════════════════════
def test_file_exists_min_constraint():
    """min > matched_count → passed=False"""
    result = run_check("file_exists", path="scripts/*.py", min=999999)
    assert result["passed"] is False
    assert "要求至少" in result["details"]


# ══════════════════════════════════════════════════════════════════
# 10. count_files 所有操作符
# ══════════════════════════════════════════════════════════════════
def test_count_files_ops():
    """count_files 所有操作符 (eq/ne/gt/gte/lt/lte)"""
    # 确保至少有一个 .py 文件
    script_count = len([f for f in os.listdir("scripts") if f.endswith(".py")])

    # eq
    r = run_check("count_files", glob_pattern="scripts/*.py", op="eq", val=script_count)
    assert r["passed"] is True, f"eq failed: {r}"

    # ne
    r = run_check("count_files", glob_pattern="scripts/*.py", op="ne", val=99999)
    assert r["passed"] is True, f"ne failed: {r}"

    # gt
    r = run_check("count_files", glob_pattern="scripts/*.py", op="gt", val=0)
    assert r["passed"] is True, f"gt failed: {r}"

    # gte
    r = run_check("count_files", glob_pattern="scripts/*.py", op="gte", val=1)
    assert r["passed"] is True, f"gte failed: {r}"

    # lt
    r = run_check("count_files", glob_pattern="scripts/*.py", op="lt", val=99999)
    assert r["passed"] is True, f"lt failed: {r}"

    # lte
    r = run_check("count_files", glob_pattern="scripts/*.py", op="lte", val=99999)
    assert r["passed"] is True, f"lte failed: {r}"


# ══════════════════════════════════════════════════════════════════
# 11. count_files 空目录 → count=0
# ══════════════════════════════════════════════════════════════════
def test_count_files_empty():
    """空目录 → count=0"""
    with tempfile.TemporaryDirectory() as tmpdir:
        r = run_check("count_files", glob_pattern=f"{tmpdir}/*.py", op="eq", val=0)
        assert r["passed"] is True, f"empty count failed: {r}"
        assert r["extra"]["matched_count"] == 0


# ══════════════════════════════════════════════════════════════════
# 12. true() 始终通过
# ══════════════════════════════════════════════════════════════════
def test_true_always_passes():
    """true() 始终通过"""
    result = run_check("true")
    assert result["passed"] is True
    assert "始终通过" in result["details"]


# ══════════════════════════════════════════════════════════════════
# 13. run_shell 正常命令 → 0 退出码
# ══════════════════════════════════════════════════════════════════
def test_run_shell_normal():
    """run_shell 正常命令 → 0 退出码"""
    result = run_shell("echo hello")
    assert result["passed"] is True
    assert result["name"] == "__shell__"
    assert "hello" in result["details"]


# ══════════════════════════════════════════════════════════════════
# 14. run_shell 异常命令 → 非 0 退出码
# ══════════════════════════════════════════════════════════════════
def test_run_shell_fail():
    """run_shell 异常命令 → 非 0 退出码"""
    result = run_shell("false")
    assert result["passed"] is False
    assert result["extra"]["exit_code"] != 0


# ══════════════════════════════════════════════════════════════════
# 15. run_shell 超时 → passed=False
# ══════════════════════════════════════════════════════════════════
def test_run_shell_timeout():
    """run_shell 超时 → passed=False"""
    result = run_shell("sleep 10", timeout=1)
    assert result["passed"] is False
    assert "timed out" in result["details"].lower() or "timed out" in result["details"]


# ══════════════════════════════════════════════════════════════════
# 16. list_checkers() 返回注册表快照
# ══════════════════════════════════════════════════════════════════
def test_list_checkers():
    """list_checkers() 返回注册表快照"""
    all_checkers = list_checkers()
    assert isinstance(all_checkers, list)
    names = [c["name"] for c in all_checkers]

    # 预置 checkers 都存在
    assert "file_exists" in names
    assert "count_files" in names
    assert "true" in names

    # 每个条目有 name, doc, params
    for c in all_checkers:
        assert "name" in c
        assert "doc" in c
        assert "params" in c
        assert isinstance(c["params"], dict)
