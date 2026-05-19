"""
Index Manager - 索引管理模块（路径计算）

职责：
1. 根据 schema 的 storage_rule 和数据计算写入路径
2. 支持按过滤条件计算读取路径（枚举/范围/单值）
3. 扫描实际存储，返回存在文件的路径

REQ-003 设计原则（续）：
- get_write_paths(data, data_type, version) -> Dict[str, DataFrame]
- get_read_paths(data_type, version, **filters) -> List[str]
  - filter 的 key 必须是 storage_rule 中的字段
  - filter 值类型：枚举 [a,b] / 单值 a / 范围 {start, end}
  - 返回实际存在文件的路径
"""

import glob
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import pandas as pd

from DataCenter.app.config import Config
from DataCenter.app.schema_manager import SchemaManager


# Filter 值类型
FilterValue = Union[str, List[str], Dict[str, str]]  # 单值、枚举、范围


class IndexManager:
    """索引管理器（路径计算）"""

    def __init__(self, schema_manager: SchemaManager):
        self.schema_manager = schema_manager
        self.config = Config()

    # ------------------------------------------------------------------ #
    # 写入路径计算
    # ------------------------------------------------------------------ #

    def get_write_paths(
        self,
        data: pd.DataFrame,
        data_type: str,
        version: str = "v1",
    ) -> Dict[str, pd.DataFrame]:
        """
        根据 storage_rule 计算写入路径，并按路径分组数据。

        Args:
            data: 待写入的 DataFrame
            data_type: 数据类型
            version: 版本号

        Returns:
            {相对路径: 数据子集} 映射
        """
        if data.empty:
            return {}

        storage_rule = self.schema_manager.get_storage_rule(data_type, version)
        refs = self._extract_path_refs(storage_rule)

        # 检查数据是否包含所需字段
        missing = [ref for ref in refs if ref not in data.columns]
        if missing:
            raise ValueError(f"Data missing required columns for storage_rule: {missing}")

        # 按路径字段分组
        group_cols = [ref for ref in refs if ref in data.columns]
        if not group_cols:
            rendered = self._render_path(storage_rule, {}, data_type, version, {})
            return {rendered: data}

        result = {}
        for group_values, group_df in data.groupby(group_cols, dropna=False):
            if not isinstance(group_values, tuple):
                group_values = (group_values,)
            row_data = dict(zip(group_cols, group_values))
            rendered = self._render_path(storage_rule, row_data, data_type, version, row_data)
            result[rendered] = group_df

        return result

    def _extract_path_refs(self, storage_rule: str) -> List[str]:
        """提取 storage_rule 中的字段引用（不含内置）"""
        refs = []
        builtin = {"name", "version", "year", "month"}
        for match in re.finditer(r"\{schema\.(\w+)\}", storage_rule):
            ref = match.group(1)
            if ref not in builtin and ref not in refs:
                refs.append(ref)
        return refs

    def _render_path(
        self,
        storage_rule: str,
        row_or_filter: Dict[str, Any],
        data_type: str,
        version: str,
        data_row: Optional[Dict[str, Any]] = None,
    ) -> str:
        """渲染路径"""
        result = storage_rule
        result = result.replace("{schema.name}", data_type)
        result = result.replace("{schema.version}", version)

        if data_row is None:
            data_row = {}

        # year/month 从 date 提取
        if "date" in data_row and data_row["date"]:
            date_str = str(data_row["date"])
            if len(date_str) >= 10:
                result = result.replace("{schema.year}", date_str[:4])
                result = result.replace("{schema.month}", date_str[5:7])

        # 数据引用
        for key, value in data_row.items():
            placeholder = "{schema." + key + "}"
            result = result.replace(placeholder, str(value) if value is not None else "")

        return result

    # ------------------------------------------------------------------ #
    # 读取路径计算
    # ------------------------------------------------------------------ #

    def get_read_paths(
        self,
        data_type: str,
        version: str = "v1",
        **filters: FilterValue,
    ) -> List[str]:
        """
        根据过滤条件计算读取路径。

        filter 的 key 必须是 storage_rule 中定义的字段。
        - 路径过滤字段（storage_rule 包含）：market, date 等
        - 行级过滤字段（不含）：code 等 → 在 read_data 中读取后过滤

        filter 值类型：
        - 单值/枚举/范围
        """
        storage_rule = self.schema_manager.get_storage_rule(data_type, version)

        # 提取 storage_rule 中真正需要用户提供的字段（不含 builtin）
        rule_fields = set(self._extract_path_refs(storage_rule))

        # 只保留在 storage_rule 中的 filter（路径过滤）
        path_filters = {k: v for k, v in filters.items() if k in rule_fields}

        # 生成候选路径（使用 path_filters）
        candidate_patterns = self._generate_candidate_patterns(storage_rule, data_type, version, path_filters)

        # 扫描并检查存在性
        existing_paths = []
        for pattern in candidate_patterns:
            abs_pattern = self.to_absolute_path(pattern)
            matched = glob.glob(abs_pattern)
            for abs_path in matched:
                rel_path = os.path.relpath(abs_path, self.config.DATA_DIR)
                existing_paths.append(rel_path)

        return existing_paths

    def _generate_candidate_patterns(
        self,
        storage_rule: str,
        data_type: str,
        version: str,
        filters: Dict[str, FilterValue],
    ) -> List[str]:
        """
        生成候选路径模式（glob 风格）。

        处理逻辑：
        - date 范围：展开为具体日期列表
        - date 枚举：直接用枚举值
        - date 单值：直接用值
        - 其他字段（market/code等）：支持枚举/单值
        - 无 filter 的字段：用 * 通配符
        """
        patterns = []

        # 处理 date
        if "date" in filters:
            date_filter = filters["date"]
            if isinstance(date_filter, dict) and ("start" in date_filter or "end" in date_filter):
                start = date_filter.get("start")
                end = date_filter.get("end")
                if start and end:
                    dates = self._generate_date_range(start, end)
                elif start:
                    from datetime import date as date_mod
                    dates = self._generate_date_range(start, date_mod.today().strftime("%Y-%m-%d"))
                elif end:
                    dates = [None]
                else:
                    dates = []
            elif isinstance(date_filter, list):
                dates = date_filter
            elif isinstance(date_filter, str):
                dates = [date_filter]
            else:
                dates = []
        else:
            dates = [None]  # 无 date filter，用通配符

        # 处理其他 filters
        other = {k: v for k, v in filters.items() if k != "date"}

        # 对于 other 中的每个字段，展开为值列表
        other_expanded = []
        if not other:
            other_expanded = [{}]
        else:
            for key, value in other.items():
                if value is None:
                    values = [None]
                elif isinstance(value, list):
                    values = value
                else:
                    values = [value]

                if not other_expanded:
                    other_expanded = [{key: v} for v in values]
                else:
                    new_expanded = []
                    for existing in other_expanded:
                        for v in values:
                            new_expanded.append({**existing, key: v})
                    other_expanded = new_expanded

        # 构建笛卡尔积
        for date in dates:
            for o in other_expanded:
                combo = dict(o)
                if date:
                    combo["date"] = date
                pattern = self._render_glob_pattern(storage_rule, data_type, version, combo)
                if pattern:
                    patterns.append(pattern)

        # 如果没有任何 filter，用 * 扫描
        if not patterns:
            patterns = [self._render_glob_pattern(storage_rule, data_type, version, {})]

        return patterns

    def _render_glob_pattern(
        self,
        storage_rule: str,
        data_type: str,
        version: str,
        filter_: Dict[str, Any],
    ) -> Optional[str]:
        """渲染为 glob 模式（未提供的字段用 *）

        动态处理所有 {schema.xxx} placeholder，不硬编码字段名。
        """
        result = storage_rule
        result = result.replace("{schema.name}", data_type)
        result = result.replace("{schema.version}", version)

        # 提取所有 {schema.xxx} placeholder
        import re
        placeholders = re.findall(r'\{schema\.([\w]+)\}', result)

        for field_name in placeholders:
            placeholder = "{schema." + field_name + "}"

            # 特殊处理：date 字段用于提取 Year/Month
            if field_name.lower() == "date":
                if "date" in filter_ and filter_["date"]:
                    date_str = str(filter_["date"])
                    result = result.replace(placeholder, date_str)
                else:
                    result = result.replace(placeholder, "*")
            elif field_name.lower() == "year":
                # Year 从 date 提取
                if "date" in filter_ and filter_["date"] and len(str(filter_["date"])) >= 4:
                    result = result.replace(placeholder, str(filter_["date"])[:4])
                else:
                    result = result.replace(placeholder, "*")
            elif field_name.lower() == "month":
                # Month 从 date 提取
                if "date" in filter_ and filter_["date"] and len(str(filter_["date"])) >= 7:
                    result = result.replace(placeholder, str(filter_["date"])[:7][5:7])
                else:
                    result = result.replace(placeholder, "*")
            else:
                # 其他字段：从 filter_ 获取值，否则用 *
                if field_name in filter_ and filter_[field_name]:
                    result = result.replace(placeholder, str(filter_[field_name]))
                else:
                    result = result.replace(placeholder, "*")

        return result

    def _generate_date_range(self, start: str, end: str) -> List[str]:
        """生成日期范围内的所有日期"""
        s = datetime.strptime(start, "%Y-%m-%d")
        e = datetime.strptime(end, "%Y-%m-%d")

        dates = []
        current = s
        while current <= e:
            dates.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)
        return dates

    # ------------------------------------------------------------------ #
    # 辅助方法
    # ------------------------------------------------------------------ #

    def to_absolute_path(self, relative_path: str) -> str:
        """相对路径转绝对路径"""
        return os.path.join(self.config.DATA_DIR, relative_path)

    @property
    def storage_manager(self):
        """懒加载 StorageManager"""
        if not hasattr(self, "_storage_manager"):
            from app.storage_manager import StorageManager
            self._storage_manager = StorageManager()
        return self._storage_manager