"""
FileTransaction — 文件级事务回滚机制

封装文件备份的事务语义：批量备份 → 原子提交／原子回滚。

从原有 ``scripts/agent-mgmt/_transaction.py`` 迁移。
"""

from __future__ import annotations

import itertools
import os
import shutil
import time
from pathlib import Path
from typing import List, Tuple

from hermes_mgmt.core.paths import BACKUP_ROOT

_counter = itertools.count()


class FileTransaction:
    """文件级事务上下文，提供批量备份与原子提交／回滚。

    典型用法::

        tx = FileTransaction()
        try:
            tx.backup("/path/to/file1.yaml")
            tx.backup("/path/to/file2.yaml")
            modify(file1)
            modify(file2)
            verify()
            tx.commit()
        except:
            tx.rollback()
            raise

    Attributes:
        tx_dir: 本事务使用的备份目录（``/tmp/hermes-mgmt-rollback/<ts>/``）。
    """

    def __init__(self) -> None:
        """创建新事务，在 ``/tmp/hermes-mgmt-rollback/<ts>/`` 下建立独立备份目录。"""
        ts = f"{int(time.time())}_{os.getpid()}_{next(_counter)}"
        self.tx_dir: Path = BACKUP_ROOT / ts
        self.tx_dir.mkdir(parents=True, exist_ok=True)
        self._files: List[Tuple[Path, Path]] = []

    # ------------------------------------------------------------------
    # 备份
    # ------------------------------------------------------------------

    def backup(self, path: str | os.PathLike[str]) -> Path:
        """备份单个文件到事务目录。

        Args:
            path: 待备份的文件路径（绝对或相对均可）。

        Returns:
            备份目标路径。

        Raises:
            FileNotFoundError: 源文件不存在。
        """
        src = Path(path)
        if not src.is_file():
            raise FileNotFoundError(f"File not found: {src}")

        if src.is_absolute():
            rel = src.relative_to(src.anchor)
            dest = self.tx_dir / rel
        else:
            cwd = Path.cwd()
            dest = self.tx_dir / cwd.relative_to(cwd.anchor) / src

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        self._files.append((src.resolve(), dest))
        return dest

    # ------------------------------------------------------------------
    # 提交（确认成功 → 删除备份）
    # ------------------------------------------------------------------

    def commit(self) -> None:
        """提交事务，删除本事务的备份目录。"""
        if self.tx_dir.is_dir() and self._is_under_backup_root():
            shutil.rmtree(self.tx_dir)
        self._files.clear()

    # ------------------------------------------------------------------
    # 回滚（失败恢复 → 还原文件）
    # ------------------------------------------------------------------

    def rollback(self) -> None:
        """回滚事务，将所有备份文件按反序还原到原始路径。"""
        for src, backup_path in reversed(self._files):
            if backup_path.is_file():
                src.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_path, src)

    # ------------------------------------------------------------------
    # 全局清理（独立于单个事务）
    # ------------------------------------------------------------------

    @staticmethod
    def cleanup(keep_count: int = 5) -> int:
        """清理旧备份目录，仅保留最近 *keep_count* 个。

        Args:
            keep_count: 保留的备份数量（默认 5）。

        Returns:
            已删除的备份目录数量。
        """
        if not BACKUP_ROOT.is_dir():
            return 0

        dirs: List[Path] = sorted(
            (d for d in BACKUP_ROOT.iterdir() if d.is_dir()),
            key=lambda d: d.name,
            reverse=True,
        )

        removed = 0
        for d in dirs[keep_count:]:
            shutil.rmtree(d, ignore_errors=True)
            if not d.exists():
                removed += 1
        return removed

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _is_under_backup_root(self) -> bool:
        """安全检查：确认 ``tx_dir`` 在 ``BACKUP_ROOT`` 下。"""
        try:
            self.tx_dir.relative_to(BACKUP_ROOT)
            return True
        except ValueError:
            return False
