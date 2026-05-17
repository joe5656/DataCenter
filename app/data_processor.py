"""
Data Processor - 数据处理模块

职责（§2.7）：
1. 接收读写请求
2. 调用 SchemaManager 进行数据验证
3. 调用 IndexManager 获取路径
4. 调用 StorageManager 进行实际 I/O

设计原则：协调者模式，不直接操作文件，委托给各专职模块。
"""

import pandas as pd
from typing import Any, Dict, List, Optional, Tuple

from app.config import Config
from app.index_manager import IndexManager
from app.schema_manager import SchemaManager
from app.storage_manager import StorageManager


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
        date: str,
        version: str = "v1",
        market: Optional[str] = None,
        code: Optional[str] = None,
        mode: str = "append",
        validate_schema: bool = True,
        check_duplicates: bool = True,
        remove_duplicates: bool = False,
    ) -> Dict[str, Any]:
        """
        写入数据

        Args:
            data: 待写入的 DataFrame
            data_type: 数据类型（如 stock_5min）
            date: 日期
            version: 版本号
            market: 市场（可选）
            code: 股票代码（可选）
            mode: 'append' 或 'overwrite'
            validate_schema: 是否进行 schema 验证
            check_duplicates: 是否检查重复
            remove_duplicates: True=自动去重，False=报错

        Returns:
            结果字典 {
                "success": bool,
                "rows_written": int,
                "file_path": str,
                "duplicates_found": int,
                "duplicates_removed": int,
            }
        """
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

        # 2. 重复验证（如果 mode='append'）
        duplicates_found = 0
        duplicates_removed = 0
        if mode == "append" and check_duplicates:
            existing = self._read_existing(data_type, date, version, market, code)
            if not existing.empty:
                duplicates = self._find_duplicates(data, existing, data_type, version)
                duplicates_found = len(duplicates)
                if duplicates_found > 0:
                    if remove_duplicates:
                        data = self._remove_duplicates(data, duplicates)
                        duplicates_removed = duplicates_found
                    else:
                        return {
                            "success": False,
                            "errors": [f"Found {duplicates_found} duplicate rows"],
                        }

        # 3. 调用 index_manager 获取写入路径
        file_path = self.index_manager.get_write_path(
            data_type, version, date, market, code
        )

        # 4. 写入 Parquet 文件
        self.storage_manager.write_parquet(
            data, file_path, mode=mode, schema=None
        )

        # 5. 返回写入结果
        metadata = self.storage_manager.get_file_metadata(file_path)
        return {
            "success": True,
            "rows_written": metadata.get("row_count", 0),
            "file_path": file_path,
            "duplicates_found": duplicates_found,
            "duplicates_removed": duplicates_removed,
        }

    def read_data(
        self,
        data_type: str,
        start_date: str,
        end_date: str,
        version: str = "v1",
        market: Optional[str] = None,
        codes: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        读取数据

        Args:
            data_type: 数据类型
            start_date: 开始日期
            end_date: 结束日期
            version: 版本号
            market: 市场（可选，过滤用）
            codes: 股票代码列表（可选，过滤用）

        Returns:
            合并后的 DataFrame
        """
        # 1. 调用 index_manager 获取读取路径列表
        paths = self.index_manager.get_read_paths(
            data_type, version, start_date, end_date, market
        )

        # 2. 逐个读取 Parquet 文件
        dfs = []
        for p in paths:
            if self.storage_manager.file_exists(p):
                df = self.storage_manager.read_parquet([p])
                dfs.append(df)

        if not dfs:
            return pd.DataFrame()

        # 3. 合并 DataFrame
        result = pd.concat(dfs, ignore_index=True)

        # 4. 过滤（market, codes）
        if market is not None and "market" in result.columns:
            result = result[result["market"] == market]
        if codes is not None and "code" in result.columns:
            result = result[result["code"].isin(codes)]

        return result

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

    def _read_existing(
        self,
        data_type: str,
        date: str,
        version: str,
        market: Optional[str] = None,
        code: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        读取已有数据（用于重复检查）

        Args:
            data_type: 数据类型
            date: 日期
            version: 版本号
            market: 市场
            code: 股票代码

        Returns:
            已有数据的 DataFrame（如果文件不存在返回空 DataFrame）
        """
        file_path = self.index_manager.get_write_path(
            data_type, version, date, market, code
        )
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
        找出重复的行（基于主键：date + code + time）

        Args:
            new_data: 新数据
            existing_data: 已有数据
            data_type: 数据类型
            version: 版本号

        Returns:
            重复数据 DataFrame
        """
        # 获取主键字段（从 schema）
        schema = self.schema_manager.load_schema(data_type, version)
        primary_keys = ["date", "code"]
        if "time" in [f["name"] for f in schema["fields"]]:
            primary_keys.append("time")

        # 找出重复行（按行匹配，不是按列）
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
        return data[~data.index.isin(duplicates.index)]
