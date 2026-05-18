"""
Schema Manager - Schema 加载、验证、管理模块

职责：
1. 加载和验证 schema 定义文件（JSON）
2. 根据数据类型和版本获取 schema
3. 验证数据是否符合 schema
4. 将 JSON schema 转换为 PyArrow Schema
5. 提供 storage_rule 给 IndexManager 使用

REQ-003 schema 格式规范：
{
    "name": "stock_5min",
    "version": "v1",
    "data_schema": {
        "date": "string",
        "code": "string",
        ...
    },
    "storage_rule": "{schema.name}/{schema.date}.parquet"
}

合法性检查：
- 必须包含 name / version / data_schema / storage_rule 四个标准字段
- data_schema 必须是 key-value 键值对，不允许更深嵌套
- storage_rule 中 {schema.xxx} 引用的 xxx 必须在 data_schema 里有定义
- storage_rule 必须以 .parquet 结尾

设计原则：启动时一次性加载所有 schema，运行时不可变。
新增数据类型 = 新 JSON 文件 + 新版本 Docker 镜像。
"""

import json
import os
import re
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

        for filename in sorted(os.listdir(self.schemas_dir)):
            if not filename.endswith(".json"):
                continue
            if not re.match(r"^.+_v[a-zA-Z0-9]+\.json$", filename):
                continue

            filepath = os.path.join(self.schemas_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    schema = json.load(f)
                self._validate_schema(schema, filename)
                key = (schema["name"], schema["version"])
                self._schemas[key] = schema
                self._pyarrow_schemas[key] = self._build_pyarrow_schema(schema, filename)
            except Exception as e:
                import warnings
                warnings.warn(f"Failed to load schema {filename}: {e}")
                continue

    # ------------------------------------------------------------------ #
    # 验证逻辑
    # ------------------------------------------------------------------ #

    def _validate_schema(self, schema: Dict[str, Any], filename: str) -> None:
        """
        验证 schema 是否符合 REQ-003 规范。

        检查项：
        1. 必须包含 name / version / data_schema / storage_rule
        2. data_schema 必须是 key-value 键值对（str -> str），不允许嵌套
        3. data_schema 的 value 必须是合法类型
        4. storage_rule 必须是字符串且以 .parquet 结尾
        5. storage_rule 中 {schema.xxx} 引用的 xxx 必须在 data_schema 里有定义

        Raises:
            ValueError: 任一检查不通过
        """
        # 1. 必填字段检查
        required = ["name", "version", "data_schema", "storage_rule"]
        for field in required:
            if field not in schema:
                raise ValueError(f"{filename}: missing required field '{field}'")

        # 2. data_schema 必须是 dict，且 key-value 均为字符串
        ds = schema["data_schema"]
        if not isinstance(ds, dict):
            raise ValueError(f"{filename}: 'data_schema' must be a key-value dict, got {type(ds).__name__}")
        if len(ds) == 0:
            raise ValueError(f"{filename}: 'data_schema' must not be empty")

        for key, value in ds.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError(
                    f"{filename}: data_schema entries must be str->str, "
                    f"got {type(key).__name__}->{type(value).__name__} for '{key}'"
                )
            # 嵌套检查：value 不能是 dict/list（虽然 isinstance 已排除，但显式检查）
            if value.startswith("{") or value.startswith("["):
                raise ValueError(f"{filename}: data_schema['{key}'] must be a flat type string, not nested")

        # 3. data_schema 的 value 必须是合法类型
        for key, value in ds.items():
            if value not in _TYPE_MAP:
                raise ValueError(f"{filename}: data_schema['{key}'] has unsupported type '{value}'")

        # 4. storage_rule 必须是字符串且以 .parquet 结尾
        sr = schema["storage_rule"]
        if not isinstance(sr, str):
            raise ValueError(f"{filename}: 'storage_rule' must be a string, got {type(sr).__name__}")
        if not sr.endswith(".parquet"):
            raise ValueError(f"{filename}: 'storage_rule' must end with '.parquet', got '{sr}'")

        # 5. storage_rule 中 {schema.xxx} 引用的 xxx 必须在 data_schema 里有定义
        #    例外：
        #    - name 和 version 是 schema 元数据
        #    - year 和 month 是从 date 动态提取的
        builtin_refs = {"name", "version", "year", "month"}
        schema_refs = self._extract_schema_refs(sr)
        for ref in schema_refs:
            if ref in builtin_refs:
                continue
            if ref not in ds:
                raise ValueError(
                    f"{filename}: storage_rule references '{{schema.{ref}}}' "
                    f"but '{ref}' is not defined in data_schema"
                )

    @staticmethod
    def _extract_schema_refs(path_template: str) -> List[str]:
        """
        从路径模板中提取所有 {schema.xxx} 引用的 xxx。

        例如: "{schema.name}/{schema.date}.parquet" -> ["name", "date"]

        Args:
            path_template: 存储路径模板

        Returns:
            引用字段名列表
        """
        return re.findall(r"\{schema\.(\w+)\}", path_template)

    # ------------------------------------------------------------------ #
    # PyArrow Schema 构建
    # ------------------------------------------------------------------ #

    def _build_pyarrow_schema(self, schema: Dict[str, Any], filename: str) -> pa.Schema:
        """
        将 JSON schema 的 data_schema 转换为 PyArrow Schema。

        Args:
            schema: 已验证的 schema 字典
            filename: 文件名（用于错误信息）

        Returns:
            PyArrow Schema 对象
        """
        fields = []
        for name, type_str in schema["data_schema"].items():
            pa_type = _TYPE_MAP[type_str]
            fields.append(pa.field(name, pa_type))
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

    def get_storage_rule(self, data_type: str, version: str) -> str:
        """
        获取 storage_rule 路径模板（供 IndexManager 使用）。

        Args:
            data_type: 数据类型名称
            version: 版本号

        Returns:
            storage_rule 字符串（如 "{schema.name}/{schema.date}.parquet"）
        """
        schema = self.load_schema(data_type, version)
        return schema["storage_rule"]

    def get_data_schema(self, data_type: str, version: str) -> Dict[str, str]:
        """
        获取 data_schema（字段名 -> 类型映射）。

        Args:
            data_type: 数据类型名称
            version: 版本号

        Returns:
            data_schema 字典（如 {"date": "string", "code": "string", ...}）
        """
        schema = self.load_schema(data_type, version)
        return schema["data_schema"]

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

        # 检查必需字段是否存在
        required_fields = list(schema["data_schema"].keys())
        missing = [f for f in required_fields if f not in data.columns]
        if missing:
            errors.append(f"Missing columns: {missing}")

        if errors:
            return (False, errors)

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
            schema 摘要列表
        """
        result = []
        for (name, version), schema in self._schemas.items():
            result.append({
                "name": name,
                "version": version,
                "storage_rule": schema.get("storage_rule", ""),
                "fields_count": len(schema.get("data_schema", {})),
            })
        return result

    def get_schema_for_api(self, data_type: str, version: str) -> Dict[str, Any]:
        """
        获取 schema 详情（供 API 端点使用）。

        Args:
            data_type: 数据类型名称
            version: 版本号

        Returns:
            完整 schema 字典
        """
        return self.load_schema(data_type, version)
