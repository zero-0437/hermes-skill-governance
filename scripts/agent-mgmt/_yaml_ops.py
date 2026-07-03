"""
YAML 操作核心库

基于 ruamel.yaml RoundTripLoader，保留 YAML 注释与格式。
提供文件的读写、修改、校验、备份与恢复功能。
"""

from __future__ import annotations

import itertools
import os
import shutil
import time
from pathlib import Path
from typing import Any, List, Sequence

import ruamel.yaml

_BACKUP_ROOT = Path("/tmp/hermes-mgmt-rollback")
_backup_counter = itertools.count()
_yaml = ruamel.yaml.YAML(typ="rt")
_yaml.indent(mapping=2, sequence=4, offset=2)

# ---------------------------------------------------------------------------
# 显式导出（含私有函数 _write_yaml，供 hermes-skill-add 使用）
# ---------------------------------------------------------------------------

__all__ = [
    "read_yaml",
    "append_to_list",
    "insert_into_dict",
    "validate_yaml",
    "backup_file",
    "restore_file",
    "_write_yaml",
    "_iter_skills",
]


# ---------------------------------------------------------------------------
# 读取
# ---------------------------------------------------------------------------

def read_yaml(path: str | os.PathLike[str]) -> Any:
    """读取 YAML 文件，返回 RoundTrip 保留注释的数据结构。

    Args:
        path: YAML 文件路径。

    Returns:
        解析后的 Python 对象（通常是 dict 或 list）。

    Raises:
        FileNotFoundError: 文件不存在。
        ruamel.yaml.YAMLError: YAML 格式非法。
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"YAML file not found: {p}")
    with open(p, encoding="utf-8") as f:
        return _yaml.load(f)


# ---------------------------------------------------------------------------
# 修改
# ---------------------------------------------------------------------------

def append_to_list(
    path: str | os.PathLike[str],
    key: str,
    item: Any,
) -> None:
    """向 YAML 文件的指定列表末尾追加一个元素。

    若 **key** 对应的值尚不存在，则创建一个空列表后再追加。

    Args:
        path: YAML 文件路径。
        key:  顶层键名。
        item: 待追加的元素。

    Raises:
        FileNotFoundError: 文件不存在。
        ruamel.yaml.YAMLError: YAML 格式非法或值类型不匹配。
        TypeError: key 对应的值不是列表且不为空。
    """
    data = read_yaml(path)

    if key not in data or data[key] is None:
        data[key] = []

    if not isinstance(data[key], list):
        raise TypeError(
            f"Key '{key}' is not a list (got {type(data[key]).__name__})"
        )

    data[key].append(item)
    _write_yaml(path, data)


def insert_into_dict(
    path: str | os.PathLike[str],
    key_parts: Sequence[str],
    value: Any,
) -> None:
    """按路径向 YAML 嵌套字典中插入值。

    路径中的中间键若不存在会被自动创建为空 dict。
    路径的最后一个键若已存在则会被覆盖。

    Args:
        path:      YAML 文件路径。
        key_parts: 键路径，例如 ``("a", "b", "c")`` 表示 ``data["a"]["b"]["c"]``。
        value:     待插入的值。

    Raises:
        FileNotFoundError: 文件不存在。
        ruamel.yaml.YAMLError: YAML 格式非法。
        TypeError: 路径中间的某个键对应的值不是 dict。
    """
    if not key_parts:
        raise ValueError("key_parts must be non-empty")

    data = read_yaml(path)
    current = data

    for part in key_parts[:-1]:
        if part not in current or current[part] is None:
            current[part] = {}
        if not isinstance(current[part], dict):
            raise TypeError(
                f"Key '{part}' is not a dict (got {type(current[part]).__name__})"
            )
        current = current[part]

    current[key_parts[-1]] = value
    _write_yaml(path, data)


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------

def validate_yaml(path: str | os.PathLike[str]) -> bool:
    """校验 YAML 文件是否合法。

    Args:
        path: YAML 文件路径。

    Returns:
        合法返回 ``True``，文件不存在或格式非法返回 ``False``。
    """
    p = Path(path)
    if not p.is_file():
        return False
    try:
        with open(p, encoding="utf-8") as f:
            _yaml.load(f)
        return True
    except ruamel.yaml.YAMLError:
        return False


# ---------------------------------------------------------------------------
# 备份 / 恢复
# ---------------------------------------------------------------------------

def backup_file(path: str | os.PathLike[str]) -> Path:
    """备份文件到 ``/tmp/hermes-mgmt-rollback/<timestamp>/``。

    备份路径保留原始文件的相对/绝对路径结构，
    例如 ``/home/user/config.yaml`` → ``/tmp/hermes-mgmt-rollback/<ts>/home/user/config.yaml``。

    Args:
        path: 待备份的文件路径。

    Returns:
        备份目标路径。

    Raises:
        FileNotFoundError: 源文件不存在。
    """
    src = Path(path)
    if not src.is_file():
        raise FileNotFoundError(f"File not found: {src}")

    ts = f"{int(time.time())}_{os.getpid()}_{next(_backup_counter)}"
    dest_dir = _BACKUP_ROOT / ts
    dest_dir.mkdir(parents=True, exist_ok=True)

    # 保留完整的绝对路径结构
    if src.is_absolute():
        # /a/b/c → /tmp/hermes-mgmt-rollback/<ts>/a/b/c
        rel = src.relative_to(src.anchor)
        dest = dest_dir / rel
    else:
        # relative → 使用当前工作目录作为前缀
        cwd = Path.cwd()
        dest = dest_dir / cwd.relative_to(cwd.anchor) / src

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def restore_file(path: str | os.PathLike[str]) -> bool:
    """从最近的备份恢复文件。

    遍历 ``/tmp/hermes-mgmt-rollback/`` 下按时间戳排序的目录，
    找到与给定路径匹配的最新备份，覆盖还原。

    Args:
        path: 待恢复的文件路径。

    Returns:
        恢复成功返回 ``True``，未找到任何可用备份返回 ``False``。

    Raises:
        FileNotFoundError: 路径指向的文件不存在且无备份可恢复时引发。
    """
    target = Path(path)
    if not _BACKUP_ROOT.is_dir():
        return False

    # 构造备份中的相对路径片段
    if target.is_absolute():
        rel = target.relative_to(target.anchor)
    else:
        rel = Path.cwd().relative_to(Path.cwd().anchor) / target

    # 按时间戳倒序查找
    ts_dirs: List[Path] = sorted(
        (d for d in _BACKUP_ROOT.iterdir() if d.is_dir()),
        key=lambda d: d.name,
        reverse=True,
    )

    for ts_dir in ts_dirs:
        backup_candidate = ts_dir / rel
        if backup_candidate.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_candidate, target)
            return True

    if not target.is_file():
        raise FileNotFoundError(
            f"No backup found for {target} and original file does not exist"
        )
    return False

# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


def _iter_skills(data: dict):
    """遍历 skill-map.yaml 数据结构，生成 (agent, category, skill_dict) 元组。

    同时处理 agents 段和 shared 段。

    Args:
        data: skill-map.yaml 解析后的 dict。

    Yields:
        (agent_name, category_name, skill_dict)
        其中 skill_dict 始终为 dict（若 YAML 中为字符串则包装为 {"name": str}）。
    """
    # agents 段
    for agent_name, agent_data in data.get("agents", {}).items():
        if not isinstance(agent_data, dict):
            continue
        for cat_name, skills in agent_data.get("categories", {}).items():
            if not isinstance(skills, list):
                continue
            for skill in skills:
                if isinstance(skill, dict):
                    yield (agent_name, cat_name, skill)
                elif isinstance(skill, str):
                    yield (agent_name, cat_name, {"name": skill})

    # shared 段
    shared_data = data.get("shared", {})
    if isinstance(shared_data, dict):
        for cat_name, skills in shared_data.get("categories", {}).items():
            if not isinstance(skills, list):
                continue
            for skill in skills:
                if isinstance(skill, dict):
                    yield ("shared", cat_name, skill)
                elif isinstance(skill, str):
                    yield ("shared", cat_name, {"name": skill})


def _write_yaml(path: str | os.PathLike[str], data: Any) -> None:
    """将 RoundTrip 数据写回 YAML 文件（UTF-8）。"""
    with open(path, "w", encoding="utf-8") as f:
        _yaml.dump(data, f)
