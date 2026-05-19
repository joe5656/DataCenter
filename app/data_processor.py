"""
Data Processor - 数据处理模块

职责（§2.7）：
1. 接收读写请求
2. 调用 SchemaManager 进行数据验证
3. 调用 IndexManager 获取路径（支持分组写入）
4. 调用 StorageManager 进行实际 I/O

设计原则：
- 协调者模式，不直接操作文件
- 支持数据按 storage_rule 自动分组写入
- 不依赖特定业务字段（如 market/code）

REQ-003 接口适配：
- write_data 接收 DataFrame，调用 index_manager.get_write_paths() 获取路径分组
- read_data 接收过滤条件，调用 index_manager.get_read_paths() 获取路径列表
"""

import pandas as pd
from typing import Any, Dict, List, Optional, Tuple

from DataCenter.app.config import Config
from DataCenter.app.index_manager import IndexManager
from DataCenter.app.schema_manager import SchemaManager
from DataCenter.app.storage_manager import StorageManager


class DataProcessor:
    """数据处理器"""

    def __init__(
        self,
        schema_manager: SchemaManager,
        index_manager: IndexManager,
        storage_manager: StorageManager,
    ):
        """
        初始化数据处理器

        Args:
            schema_manager: SchemaManager 实例
            index_manager: IndexManager 实例
            storage_manager: StorageManager 实例
        """
        self.schema_manager = schema_manager
        self.index_manager = index_manager
        self.storage_manager = storage_manager
        self.config = Config()

    def write_data(
        self,
        data: pd.DataFrame,
        data_type: str,
        version: str = "v1",
        mode: str = "append",
        validate_schema: bool = True,
        check_duplicates: bool = True,
        remove_duplicates: bool = False,
    ) -> Dict[str, Any]:
        """
        写入数据

        数据会按 storage_rule 自动分组写入多个文件（如果需要）。

        Args:
            data: 待写入的 DataFrame
            data_type: 数据类型（如 stock_5min）
            version: 版本号
            mode: 'append' 或 'overwrite'
            validate_schema: 是否进行 schema 验证
            check_duplicates: 是否检查重复
            remove_duplicates: True=自动去重，False=报错

        Returns:
            结果字典 {
                "success": bool,
                "total_rows": int,
                "files_written": int,
                "file_paths": List[str],
                "duplicates_found": int,
                "duplicates_removed": int,
            }
        """
        if data.empty:
            return {
                "success": True,
                "total_rows": 0,
                "files_written": 0,
                "file_paths": [],
                "duplicates_found": 0,
                "duplicates_removed": 0,
            }

        # 1. Schema 验证
        if validate_schema:
            is_valid, errors = self.schema_manager.validate_data(
                data, data_type, version
            )
            if not is_valid:
                return {
                    "success": False,
                    "errors": errors,
                }

        # 2. 获取写入路径分组
        path_groups = self.index_manager.get_write_paths(data, data_type, version)

        # 3. 逐组写入
        total_written = 0
        file_paths = []
        duplicates_found = 0
        duplicates_removed = 0

        for relative_path, subset in path_groups.items():
            absolute_path = self.index_manager.to_absolute_path(relative_path)

            # 重复检查（append 模式）
            subset_to_write = subset.copy()
            if mode == "append" and check_duplicates:
                existing = self._read_existing_file(absolute_path)
                if not existing.empty:
                    dup = self._find_duplicates(subset_to_write, existing, data_type, version)
                    if len(dup) > 0:
                        duplicates_found += len(dup)
                        if remove_duplicates:
                            subset_to_write = self._remove_duplicates(subset_to_write, dup)
                            duplicates_removed += len(dup)
                        else:
                            return {
                                "success": False,
                                "errors": [f"Found {len(dup)} duplicate rows in {relative_path}"],
                            }

            # 写入
            self.storage_manager.write_parquet(
                subset_to_write, absolute_path, mode=mode, schema=None
            )

            total_written += len(subset_to_write)
            file_paths.append(absolute_path)

        return {
            "success": True,
            "total_rows": total_written,
            "files_written": len(file_paths),
            "file_paths": file_paths,
            "duplicates_found": duplicates_found,
            "duplicates_removed": duplicates_removed,
        }

    def read_data(
        self,
        data_type: str,
        version: str = "v1",
        **filters: Any,
    ) -> pd.DataFrame:
        """
        读取数据

        Args:
            data_type: 数据类型
            version: 版本号
            **filters: 过滤条件
                - date: 单值/枚举/范围 {"start": "2026-01-01", "end": "2026-12-31"}
                - market: 单值/枚举
                - code: 单值/枚举

        Returns:
            合并后的 DataFrame
        """
        # 1. 获取读取路径列表（只返回实际存在文件的路径）
        relative_paths = self.index_manager.get_read_paths(
            data_type, version, **filters
        )

        # 2. 逐个读取 Parquet 文件
        dfs = []
        for rel_path in relative_paths:
            abs_path = self.index_manager.to_absolute_path(rel_path)
            if self.storage_manager.file_exists(abs_path):
                df = self.storage_manager.read_parquet([abs_path])
                dfs.append(df)

        if not dfs:
            return pd.DataFrame()

        # 3. 合并 DataFrame
        result = pd.concat(dfs, ignore_index=True)

        # 4. 应用 filters 过滤
        for key, value in filters.items():
            if key in result.columns:
                col_dtype = result[key].dtype
                if isinstance(value, dict) and ("start" in value or "end" in value):
                    # 范围过滤（支持开放式范围）
                    if "start" in value:
                        sv = self._coerce_filter_value(value["start"], col_dtype)
                        result = result[result[key] >= sv]
                    if "end" in value:
                        ev = self._coerce_filter_value(value["end"], col_dtype)
                        result = result[result[key] <= ev]
                elif isinstance(value, list):
                    # 枚举过滤
                    coerced = [self._coerce_filter_value(v, col_dtype) for v in value]
                    result = result[result[key].isin(coerced)]
                else:
                    # 单值过滤
                    cv = self._coerce_filter_value(value, col_dtype)
                    result = result[result[key] == cv]

        return result

    @staticmethod
    def _coerce_filter_value(value, col_dtype):
        """将 filter 值转换为与列 dtype 匹配的类型"""
        if pd.api.types.is_numeric_dtype(col_dtype):
            try:
                return float(value)
            except (ValueError, TypeError):
                return value
        return value

    def validate_schema(
        self, data: pd.DataFrame, data_type: str, version: str
    ) -> Tuple[bool, List[str]]:
        """
        验证数据是否符合 schema

        Args:
            data: 待验证的 DataFrame
            data_type: 数据类型
            version: 版本号

        Returns:
            (是否通过, 错误列表)
        """
        return self.schema_manager.validate_data(data, data_type, version)

    def _read_existing_file(self, file_path: str) -> pd.DataFrame:
        """
        读取已有数据文件（用于重复检查）

        Args:
            file_path: 文件绝对路径

        Returns:
            已有数据的 DataFrame（如果文件不存在返回空 DataFrame）
        """
        if not self.storage_manager.file_exists(file_path):
            return pd.DataFrame()
        return self.storage_manager.read_parquet([file_path])

    def _find_duplicates(
        self,
        new_data: pd.DataFrame,
        existing_data: pd.DataFrame,
        data_type: str,
        version: str,
    ) -> pd.DataFrame:
        """
        找出重复的行

        主键字段由 schema 的 data_schema 决定：
        - date + code（必须）
        - time（如果 data_schema 中有定义）

        Args:
            new_data: 新数据
            existing_data: 已有数据
            data_type: 数据类型
            version: 版本号

        Returns:
            重复数据 DataFrame
        """
        # 获取主键字段
        schema = self.schema_manager.load_schema(data_type, version)
        data_schema = schema["data_schema"]

        # 动态确定主键字段
        primary_keys = []

        # 查找 date 相关字段（date 或类似名称）
        date_fields = [k for k in data_schema.keys() if "date" in k.lower()]
        if date_fields:
            primary_keys.append(date_fields[0])

        # 查找 code 相关字段（stock_code、code 或类似名称）
        code_fields = [k for k in data_schema.keys() if "code" in k.lower()]
        if code_fields:
            primary_keys.append(code_fields[0])

        # 检查是否有 time 字段
        time_fields = [k for k in data_schema.keys() if "time" in k.lower()]
        if time_fields:
            primary_keys.append(time_fields[0])

        # 确保至少有主键
        if not primary_keys:
            primary_keys = list(data_schema.keys())[:2]  # 默认取前两个字段

        # 找出重复行（按主键匹配）
        duplicates = new_data.merge(
            existing_data[primary_keys].drop_duplicates(),
            on=primary_keys,
            how="inner",
        )
        return duplicates

    def _remove_duplicates(
        self, data: pd.DataFrame, duplicates: pd.DataFrame
    ) -> pd.DataFrame:
        """
        移除重复数据

        Args:
            data: 原始数据
            duplicates: 重复数据

        Returns:
            去重后的 DataFrame
        """
        # 获取 duplicates 的主键组合
        # 用 merge 的 indicator 找出非重复行
        primary_keys = list(duplicates.columns)
        merged = data.merge(
            duplicates[primary_keys].drop_duplicates(),
            how="left",
            indicator=True,
        )
        return merged[merged["_merge"] == "left_only"].drop(columns=["_merge"])
