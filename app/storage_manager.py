"""
Storage Manager - Parquet 底层 I/O 模块

职责：
1. 封装 Parquet 读写操作（底层 I/O）
2. 不负责路径计算（由 IndexManager 负责）
3. 不负责数据验证（由 DataProcessor 负责）
4. 进程安全：使用 fcntl.flock 实现文件级读写锁

设计原则：纯 I/O 模块，只做文件读写，不做业务逻辑。
进程安全由 fcntl.flock 保证（Linux/macOS 通用）。
"""

import fcntl
import os
import warnings
from pathlib import Path
from typing import List, Optional, Dict, Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


class StorageManager:
    """Parquet 存储管理器（底层 I/O，含进程安全锁）"""

    def __init__(self, compression: str = "SNAPPY"):
        """
        初始化存储管理器

        Args:
            compression: Parquet 压缩算法，可选 SNAPPY、GZIP、NONE 等
        """
        self.compression = compression

    # ------------------------------------------------------------------ #
    # 文件锁机制（进程安全，REQ-001）
    # ------------------------------------------------------------------ #

    def _get_lock_path(self, file_path: str) -> str:
        """
        返回对应的锁文件路径（与数据文件同目录，.lock 后缀）

        Args:
            file_path: 数据文件路径

        Returns:
            锁文件路径（如 /data/stock_5min.parquet.lock）
        """
        return file_path + ".lock"

    def _acquire_write_lock(self, file_path: str):
        """
        获取写锁（排他锁 LOCK_EX），阻塞直到获取成功

        写锁排他：获取期间其他进程的读/写都会被阻塞。
        返回锁文件 fd，调用方必须在 finally 中调用 _release_lock(fd)。

        Args:
            file_path: 数据文件路径

        Returns:
            锁文件 fd（文件描述符）
        """
        lock_path = self._get_lock_path(file_path)
        # 确保锁文件的父目录存在（数据文件的父目录可能刚被创建）
        lock_parent = os.path.dirname(lock_path)
        if lock_parent:
            os.makedirs(lock_parent, exist_ok=True)
        lock_fd = open(lock_path, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)  # 阻塞直到获取写锁
        return lock_fd

    def _acquire_read_lock(self, file_path: str):
        """
        获取读锁（共享锁 LOCK_SH），如有写锁则阻塞等待

        读锁共享：多个进程可同时持有读锁。
        但若数据文件正被写锁保护，读锁会阻塞直到写锁释放。
        返回锁文件 fd，调用方必须在 finally 中调用 _release_lock(fd)。

        Args:
            file_path: 数据文件路径

        Returns:
            锁文件 fd（文件描述符），如果文件不存在则返回 None
        """
        if not os.path.exists(file_path):
            return None  # 文件不存在，无需加锁

        lock_path = self._get_lock_path(file_path)
        # 确保锁文件存在
        if not os.path.exists(lock_path):
            open(lock_path, "w").close()
        lock_fd = open(lock_path, "r")
        fcntl.flock(lock_fd, fcntl.LOCK_SH)  # 阻塞直到获取读锁（写锁释放后）
        return lock_fd

    def _release_lock(self, lock_fd) -> None:
        """
        释放锁（LOCK_UN）并关闭 fd

        Args:
            lock_fd: 锁文件 fd（由 _acquire_write_lock / _acquire_read_lock 返回）
        """
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()

    # ------------------------------------------------------------------ #
    # 公开接口（含锁）
    # ------------------------------------------------------------------ #

    def write_parquet(
        self,
        data: pd.DataFrame,
        file_path: str,
        schema: Optional[pa.Schema] = None,
        mode: str = "append",
    ) -> str:
        """
        写入 Parquet 文件（内含写锁，排他访问）

        写锁期间，其他进程的读或写都会被阻塞。

        Args:
            data: 要写入的 DataFrame
            file_path: 目标文件路径
            schema: PyArrow Schema（可选，用于强制类型）
            mode: 写入模式，'append' 或 'overwrite'

        Returns:
            实际写入的文件路径

        Raises:
            ValueError: mode 不在允许范围内
            OSError: 文件写入失败
        """
        if mode not in ("append", "overwrite"):
            raise ValueError(f"Unsupported mode: {mode}, expected 'append' or 'overwrite'")

        lock_fd = None
        try:
            lock_fd = self._acquire_write_lock(file_path)  # 获取写锁（阻塞）

            # 确保父目录存在
            parent_dir = os.path.dirname(file_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            # overwrite 模式：直接写入
            if mode == "overwrite" or not os.path.exists(file_path):
                return self._write_single(data, file_path, schema)

            # append 模式：读取已有数据 → 合并 → 写回
            existing = self._read_parquet_without_lock([file_path])
            merged = pd.concat([existing, data], ignore_index=True)
            return self._write_single(merged, file_path, schema)
        finally:
            self._release_lock(lock_fd)  # 释放写锁

    def read_parquet(
        self,
        file_paths: List[str],
        columns: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        读取 Parquet 文件（内含读锁，共享访问）

        如果目标文件正被写锁保护，读锁会阻塞直到写锁释放。
        多个并发读可同时进行（共享锁）。

        Args:
            file_paths: 文件路径列表
            columns: 只读指定列（可选，用于性能优化）

        Returns:
            合并后的 DataFrame

        Raises:
            FileNotFoundError: 文件不存在
        """
        if not file_paths:
            return pd.DataFrame()

        # 获取所有文件的读锁
        lock_fds = []
        try:
            for fp in file_paths:
                fd = self._acquire_read_lock(fp)
                if fd is not None:
                    lock_fds.append(fd)

            # 执行读取（无锁版本，锁已由上方获取）
            return self._read_parquet_without_lock(file_paths, columns)
        finally:
            for fd in lock_fds:
                self._release_lock(fd)

    def delete_parquet(self, file_path: str) -> bool:
        """
        删除 Parquet 文件（内含写锁）

        删除时获取写锁，防止删除时其他进程正在读写。
        同时删除对应的 .lock 文件（如果存在）。

        Args:
            file_path: 目标文件路径

        Returns:
            True 表示成功删除，False 表示文件不存在
        """
        lock_fd = None
        try:
            lock_fd = self._acquire_write_lock(file_path)  # 获取写锁
            try:
                os.remove(file_path)
            except FileNotFoundError:
                return False
            # 同时删除锁文件（如果存在）
            lock_path = self._get_lock_path(file_path)
            if os.path.exists(lock_path):
                try:
                    os.remove(lock_path)
                except OSError:
                    pass  # 锁文件删除失败不影响主流程
            return True
        finally:
            self._release_lock(lock_fd)

    def file_exists(self, file_path: str) -> bool:
        """
        检查文件是否存在（无需加锁，只检查路径）

        注意：此操作只检查路径，不读取文件内容，无需加锁。
        如果需要在文件存在性基础上做后续操作，调用方应自行加锁。

        Args:
            file_path: 目标文件路径

        Returns:
            True 表示存在
        """
        return os.path.exists(file_path)

    def get_file_metadata(self, file_path: str) -> Dict[str, Any]:
        """
        获取文件元数据（内含读锁）

        Args:
            file_path: 目标文件路径

        Returns:
            包含 row_count、file_size、columns 等信息的字典

        Raises:
            FileNotFoundError: 文件不存在
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        lock_fd = None
        try:
            lock_fd = self._acquire_read_lock(file_path)
            # 用 pyarrow 读取元数据（不加载数据本身，很高效）
            pf = pq.ParquetFile(file_path)
            md = pf.metadata
            return {
                "file_path": file_path,
                "row_count": md.num_rows,
                "column_count": md.num_columns,
                "file_size": os.path.getsize(file_path),
                "created": md.format_version,
                "columns": list(pf.schema_arrow.names),
                "schema": pf.schema_arrow,
            }
        finally:
            self._release_lock(lock_fd)

    # ------------------------------------------------------------------ #
    # 内部方法
    # ------------------------------------------------------------------ #

    def _read_parquet_without_lock(
        self,
        file_paths: List[str],
        columns: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        读取 Parquet 文件（无锁版本，供 read_parquet 内部调用）

        此方法假设调用方已经获取了相应的读锁。

        Args:
            file_paths: 文件路径列表
            columns: 只读指定列（可选）

        Returns:
            合并后的 DataFrame

        Raises:
            FileNotFoundError: 文件不存在
        """
        # 校验文件存在性
        missing = [p for p in file_paths if not os.path.exists(p)]
        if missing:
            raise FileNotFoundError(f"Files not found: {missing}")

        # 多文件读取并合并
        dfs = []
        for fp in file_paths:
            df = pd.read_parquet(fp, columns=columns, engine="pyarrow")
            dfs.append(df)

        return pd.concat(dfs, ignore_index=True) if len(dfs) > 1 else dfs[0]

    def _write_single(
        self,
        data: pd.DataFrame,
        file_path: str,
        schema: Optional[pa.Schema] = None,
    ) -> str:
        """
        实际写入单个 Parquet 文件（无锁版本，供 write_parquet 内部调用）

        此方法假设调用方已经获取了相应的写锁。

        Args:
            data: 要写入的 DataFrame
            file_path: 目标文件路径
            schema: PyArrow Schema（可选）

        Returns:
            实际写入的文件路径
        """
        if schema is not None:
            # 用 PyArrow 强制 schema 后写入
            table = pa.Table.from_pandas(data, schema=schema, preserve_index=False)
            pq.write_table(table, file_path, compression=self.compression)
        else:
            data.to_parquet(
                file_path,
                engine="pyarrow",
                compression=self.compression,
                index=False,
            )
        return file_path
