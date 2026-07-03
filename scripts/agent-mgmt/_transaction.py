"""
FileTransaction — 文件级事务回滚机制

在 _yaml_ops.backup_file / restore_file 的基础上封装事务语义：
批量备份 → 原子提交（删备份）／原子回滚（还原备份）。

事务使用模式：:

    tx = FileTransaction()
    try:
        tx.backup(file1)
        tx.backup(file2)
        modify(file1)
        modify(file2)
        verify()  # 校验通过
        tx.commit()
    except:
        tx.rollback()
        raise
"""

from __future__ import annotations

import itertools
import os
import shutil
import time
from pathlib import Path
from typing import List, Tuple

from _yaml_ops import _BACKUP_ROOT

_counter = itertools.count()


# ---------------------------------------------------------------------------
# FileTransaction
# ---------------------------------------------------------------------------

class FileTransaction:
    """文件级事务上下文，提供批量备份与原子提交／回滚。

    典型用法：:

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
        """创建新事务，在 ``/tmp/hermes-mgmt-rollback/<ts>/`` 下建立独立备份目录。

        时间戳基于 ``time.time()`` 的整数秒，确保同一进程内多次
        创建 ``FileTransaction`` 实例获得不同的目录名。
        """
        ts = f"{int(time.time())}_{os.getpid()}_{next(_counter)}"
        self.tx_dir: Path = _BACKUP_ROOT / ts
        self.tx_dir.mkdir(parents=True, exist_ok=True)
        # (原始路径, 备份路径) 记录，供 rollback 遍历还原
        self._files: List[Tuple[Path, Path]] = []

    # ------------------------------------------------------------------
    # 备份
    # ------------------------------------------------------------------

    def backup(self, path: str | os.PathLike[str]) -> Path:
        """备份单个文件到事务目录。

        备份路径保留原始文件的绝对路径结构。
        例如 ``/home/user/config.yaml`` →
        ``/tmp/hermes-mgmt-rollback/<ts>/home/user/config.yaml``。

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

        # 保留完整的路径结构（与 _yaml_ops.backup_file 一致）
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
        """提交事务。

        删除本事务的备份目录，确认修改成功。
        安全守卫：仅当 ``tx_dir`` 确实是 ``_BACKUP_ROOT`` 的子目录时
        才执行删除，避免误删系统目录。
        """
        if self.tx_dir.is_dir() and self._is_under_backup_root():
            shutil.rmtree(self.tx_dir)
        self._files.clear()

    # ------------------------------------------------------------------
    # 回滚（失败恢复 → 还原文件）
    # ------------------------------------------------------------------

    def rollback(self) -> None:
        """回滚事务。

        将 ``backup()`` 记录的所有备份文件按 **反序** 还原到原始路径。
        还原后备份文件**保留**在事务目录中（以备核查），不会自动删除。

        安全保证：
        - 只还原 ``backup()`` 明确记录过的文件
        - 每个还原操作独立，部分失败不影响其余文件
        """
        for src, backup_path in reversed(self._files):
            if backup_path.is_file():
                src.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_path, src)

    # ------------------------------------------------------------------
    # 全局清理（独立于单个事务）
    # ------------------------------------------------------------------

    @staticmethod
    def cleanup(age_hours: int = 24) -> int:
        """清理超过 *age_hours* 小时的旧备份目录。

        根据目录的 ``st_mtime``（最后修改时间）判定过期时间。
        可通过 crontab 或启动时调用此方法。

        Args:
            age_hours: 保留的小时数（默认 24）。

        Returns:
            已删除的备份目录数量。
        """
        if not _BACKUP_ROOT.is_dir():
            return 0

        cutoff = time.time() - (age_hours * 3600)
        removed = 0

        for entry in _BACKUP_ROOT.iterdir():
            if not entry.is_dir():
                continue
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
                if not entry.exists():
                    removed += 1

        return removed

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _is_under_backup_root(self) -> bool:
        """安全检查：确认 ``tx_dir`` 在 ``_BACKUP_ROOT`` 下。"""
        try:
            self.tx_dir.relative_to(_BACKUP_ROOT)
            return True
        except ValueError:
            return False
