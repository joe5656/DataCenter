"""
Index Manager - 索引管理模块（路径计算）

职责：
1. 根据 schema 的 storage_rules.path_template 计算读写路径
2. 支持按日期范围列出文件路径（读路径）
3. 【暂不实现】分片（partition）逻辑 — 由 DataProcessor 处理
4. 无状态，纯路径计算（不读写文件）

设计原则：路径计算逻辑与 I/O 分离，便于测试和扩展。
"""

import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.config import Config
from app.schema_manager import SchemaManager


class IndexManager:
    """索引管理器（路径计算）"""

    def __init__(self, schema_manager: SchemaManager):
        """
        初始化索引管理器

        Args:
            schema_manager: SchemaManager 实例（用于获取 storage_rules）
        """
        self.schema_manager = schema_manager
        self.config = Config()

    def get_write_path(
        self,
        data_type: str,
        version: str,
        date: str,
        market: Optional[str] = None,
        code: Optional[str] = None,
    ) -> str:
        """
        计算写入路径（单文件）

        Args:
            data_type: 数据类型（如 stock_5min）
            version: 版本号（如 v1）
            date: 日期（如 2026-05-17）
            market: 市场（可选，如 XHKG）
            code: 股票代码（可选，如 00700）

        Returns:
            完整文件路径（含 DATA_DIR 前缀）
        """
        storage_rules = self.schema_manager.get_storage_rules(data_type, version)
        path_template = storage_rules["path_template"]
        rendered = self._render_path(path_template, data_type, version, date, market, code)
        return os.path.join(self.config.DATA_DIR, rendered)

    def get_read_paths(
        self,
        data_type: str,
        version: str,
        start_date: str,
        end_date: str,
        market: Optional[str] = None,
    ) -> List[str]:
        """
        计算读取路径（日期范围内所有文件）

        Args:
            data_type: 数据类型
            version: 版本号
            start_date: 开始日期（含，YYYY-MM-DD）
            end_date: 结束日期（含，YYYY-MM-DD）
            market: 市场（可选）

        Returns:
            完整文件路径列表（按日期排序）
        """
        storage_rules = self.schema_manager.get_storage_rules(data_type, version)
        path_template = storage_rules["path_template"]

        dates = self._generate_dates(start_date, end_date)
        paths = []
        for date in dates:
            rendered = self._render_path(path_template, data_type, version, date, market)
            full_path = os.path.join(self.config.DATA_DIR, rendered)
            paths.append(full_path)

        return paths

    # ------------------------------------------------------------------ #
    # get_partition_paths —— 暂未实现
    # 分区逻辑由 DataProcessor 根据业务需求处理
    # ------------------------------------------------------------------ #

    def _render_path(
        self,
        path_template: str,
        data_type: str,
        version: str,
        date: str,
        market: Optional[str] = None,
        code: Optional[str] = None,
        partition_num: Optional[int] = None,
    ) -> str:
        """
        渲染 path_template

        支持的变量：
        - {data_type}: schema name
        - {granularity}: schema granularity
        - {year}: date[:4]
        - {month}: date[5:7]
        - {date}: date
        - {market}: market (optional)
        - {code}: code (optional)
        - {size}: partition number（不含格式说明符，调用方负责格式化）

        Args:
            path_template: 路径模板
            data_type: 数据类型
            version: 版本号
            date: 日期
            market: 市场（可选）
            code: 代码（可选）
            partition_num: 分片编号（可选，整数）

        Returns:
            渲染后的相对路径

        Raises:
            ValueError: 必填变量未填充（可选变量可以留在模板中）
        """
        granularity = self.schema_manager.get_granularity(data_type, version)

        variables = {
            "data_type": data_type,
            "granularity": granularity,
            "year": date[:4],
            "month": date[5:7],
            "date": date,
        }
        if market is not None:
            variables["market"] = market
        if code is not None:
            variables["code"] = code
        if partition_num is not None:
            # 注意：模板中应使用 {size}，调用方负责格式化（如 _part{size:03d}）
            variables["size"] = str(partition_num)  # 字符串，调用方自行格式化

        # 渲染模板（简单 replace，不支持复杂表达式）
        result = path_template
        for key, value in variables.items():
            placeholder = "{" + key + "}"
            result = result.replace(placeholder, value)

        # 检查是否还有未渲染的 {xxx}（可选变量允许存在，必填变量应报错）
        import re
        remaining = re.findall(r"\{([^}]+)\}", result)
        if remaining:
            # 有未渲染的变量，可能是可选变量，暂不允许（让调用方显式处理）
            raise ValueError(f"Unrendered variables in path_template: {remaining}")

        return result

    def _generate_dates(self, start_date: str, end_date: str) -> List[str]:
        """
        生成日期范围内所有日期（含起止）

        Args:
            start_date: 开始日期（YYYY-MM-DD）
            end_date: 结束日期（YYYY-MM-DD）

        Returns:
            日期字符串列表（YYYY-MM-DD）
        """
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")

        dates = []
        current = start
        while current <= end:
            dates.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)

        return dates
