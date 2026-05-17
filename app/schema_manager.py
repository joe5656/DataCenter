"""
Schema Manager - Schema 加载、验证、管理模块

职责：
1. 加载和验证 schema 定义文件（JSON）
2. 根据数据类型和版本获取 schema
3. 验证数据是否符合 schema
4. 将 JSON schema 转换为 PyArrow Schema
5. 提供 storage_rules 给 IndexManager 使用

设计原则：启动时一次性加载所有 schema，运行时不可变。
新增数据类型 = 新 JSON 文件 + 新版本 Docker 镜像。
"""

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import pyarrow as pa


# JSON 类型 → PyArrow 类型映射
_TYPE_MAP = {
    "string": pa.string(),
    "int64": pa.int64(),
    "int32": pa.int32(),
    "int16": pa.int16(),
    "int8": pa.int8(),
    "uint64": pa.uint64(),
    "float": pa.float32(),
    "double": pa.float64(),
    "bool": pa.bool_(),
    "date": pa.string(),  # 日期保持字符串，调用方自行转换
    "datetime": pa.string(),  # 时间保持字符串
    "timestamp": pa.int64(),  # Unix timestamp (ms)
}


class SchemaManager:
    """Schema 管理器（启动时加载，运行时不可变）"""

    def __init__(self, schemas_dir: str):
        """
        初始化 Schema 管理器，加载 schemas_dir 下所有 JSON 文件。

        Args:
            schemas_dir: schema 文件目录（如 ./schemas）
        """
        self.schemas_dir = schemas_dir
        self._schemas: Dict[Tuple[str, str], Dict[str, Any]] = {}  # (name, version) -> schema dict
        self._pyarrow_schemas: Dict[Tuple[str, str], pa.Schema] = {}  # (name, version) -> PyArrow Schema
        self._load_all_schemas()

    def _load_all_schemas(self) -> None:
        """
        加载 schemas_dir 下所有 {name}_v{version}.json 文件。

        文件命名规范：{name}_v{version}.json（如 stock_5min_v1.json）
        加载失败会打印警告并跳过（不阻断启动）。
        """
        if not os.path.isdir(self.schemas_dir):
            return

        for filename in os.listdir(self.schemas_dir):
            if not filename.endswith(".json"):
                continue
            # 只加载符合 {name}_v{version}.json 命名规范的文件
            if not re.match(r"^.+\_v[a-zA-Z0-9]+\.json$", filename):
                continue

            filepath = os.path.join(self.schemas_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    schema = json.load(f)
                self._validate_schema_structure(schema, filename)
                key = (schema["name"], schema["version"])
                self._schemas[key] = schema
                self._pyarrow_schemas[key] = self._build_pyarrow_schema(schema, filename)
            except Exception as e:
                import warnings
                warnings.warn(f"Failed to load schema {filename}: {e}")
                continue

    def _validate_schema_structure(self, schema: Dict[str, Any], filename: str) -> None:
        """
        验证 schema JSON 结构是否合法。

        Raises:
            ValueError: 缺少必填字段或字段定义不合法
        """
        required = ["name", "version", "granularity", "fields", "storage_rules"]
        for field in required:
            if field not in schema:
                raise ValueError(f"{filename}: missing required field '{field}'")

        if not isinstance(schema["fields"], list):
            raise ValueError(f"{filename}: 'fields' must be a list")

        for i, f in enumerate(schema["fields"]):
            if "name" not in f or "type" not in f:
                raise ValueError(f"{filename}: fields[{i}] missing 'name' or 'type'")
            if f["type"] not in _TYPE_MAP:
                raise ValueError(f"{filename}: fields[{i}] unsupported type '{f['type']}'")

        # 验证 storage_rules
        sr = schema["storage_rules"]
        if "path_template" not in sr or "partition" not in sr:
            raise ValueError(f"{filename}: storage_rules missing 'path_template' or 'partition'")
        if "by" not in sr["partition"] or "max_rows" not in sr["partition"] or "max_size_mb" not in sr["partition"]:
            raise ValueError(f"{filename}: storage_rules.partition missing required fields")

    def _build_pyarrow_schema(self, schema: Dict[str, Any], filename: str) -> pa.Schema:
        """
        将 JSON schema 转换为 PyArrow Schema。

        Args:
            schema: 已验证的 schema 字典
            filename: 文件名（用于错误信息）

        Returns:
            PyArrow Schema 对象
        """
        fields = []
        for f in schema["fields"]:
            pa_type = _TYPE_MAP[f["type"]]
            fields.append(pa.field(f["name"], pa_type))
        return pa.schema(fields)

    # ------------------------------------------------------------------ #
    # 公开接口
    # ------------------------------------------------------------------ #

    def load_schema(self, data_type: str, version: str) -> Dict[str, Any]:
        """
        加载指定数据类型和版本的 schema。

        Args:
            data_type: 数据类型名称（如 stock_5min）
            version: 版本号（如 v1）

        Returns:
            schema 字典

        Raises:
            KeyError: schema 未找到
        """
        key = (data_type, version)
        if key not in self._schemas:
            raise KeyError(f"Schema not found: {data_type}_{version}")
        return self._schemas[key]

    def get_storage_rules(self, data_type: str, version: str) -> Dict[str, Any]:
        """
        获取 storage_rules（供 IndexManager 使用）。

        Args:
            data_type: 数据类型名称
            version: 版本号

        Returns:
            storage_rules 字典（含 path_template 和 partition）
        """
        schema = self.load_schema(data_type, version)
        return schema["storage_rules"]

    def get_granularity(self, data_type: str, version: str) -> str:
        """
        获取 schema 的 granularity（供 IndexManager 渲染 path_template 使用）。

        Args:
            data_type: 数据类型名称
            version: 版本号

        Returns:
            颗粒度字符串（如 5min、1day）
        """
        schema = self.load_schema(data_type, version)
        return schema["granularity"]

    def validate_data(self, data: pd.DataFrame, data_type: str, version: str) -> Tuple[bool, List[str]]:
        """
        验证 DataFrame 是否符合 schema。

        Args:
            data: 待验证的 DataFrame
            data_type: 数据类型名称
            version: 版本号

        Returns:
            (is_valid, errors) 元组
        """
        schema = self.load_schema(data_type, version)
        errors = []

        # 1. 检查必需字段是否存在
        required_fields = [f["name"] for f in schema["fields"]]
        missing = [f for f in required_fields if f not in data.columns]
        if missing:
            errors.append(f"Missing columns: {missing}")

        if errors:
            return (False, errors)

        # 2. 类型检查（可选，PyArrow 写入时会自动转换）
        # 这里只做警告，不阻断写入
        for f in schema["fields"]:
            col = f["name"]
            expected_type = f["type"]
            if col in data.columns:
                actual_dtype = str(data[col].dtype)
                # 这里可以添加更严格的类型检查
                pass

        return (True, [])

    def get_parquet_schema(self, data_type: str, version: str) -> pa.Schema:
        """
        获取 PyArrow Schema 对象（用于 Parquet 写入时强制类型）。

        Args:
            data_type: 数据类型名称
            version: 版本号

        Returns:
            PyArrow Schema 对象
        """
        key = (data_type, version)
        if key not in self._pyarrow_schemas:
            raise KeyError(f"PyArrow schema not found: {data_type}_{version}")
        return self._pyarrow_schemas[key]

    def list_schemas(self) -> List[Dict[str, Any]]:
        """
        列出所有已加载的 schema（摘要信息）。

        Returns:
            schema 摘要列表 [{"name":, "version":, "granularity":, "description":}, ...]
        """
        result = []
        for (name, version), schema in self._schemas.items():
            result.append({
                "name": name,
                "version": version,
                "granularity": schema.get("granularity"),
                "description": schema.get("description", ""),
                "fields_count": len(schema.get("fields", [])),
            })
        return result

    def get_schema_for_api(self, data_type: str, version: str) -> Dict[str, Any]:
        """
        获取 schema 详情（供 API /schemas 端点使用）。

        Args:
            data_type: 数据类型名称
            version: 版本号

        Returns:
            完整 schema 字典（含 fields 详情）
        """
        return self.load_schema(data_type, version)
