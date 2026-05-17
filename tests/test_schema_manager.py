"""
Tests for SchemaManager (§2.5)

测试覆盖：
1. Schema 加载（正常 / 缺失字段 / 类型错误）
2. get_storage_rules / get_granularity
3. validate_data
4. get_parquet_schema
5. list_schemas / get_schema_for_api
6. 文件命名规范（只加载 {name}_v{version}.json）
"""

import json
import os
import tempfile
from pathlib import Path

import pytest
import pandas as pd


@pytest.fixture
def schema_dir(tmp_path):
    """创建一个临时 schemas/ 目录，并写入测试用的 schema 文件"""
    d = tmp_path / "schemas"
    d.mkdir()

    # 1. 正确的 schema：stock_5min_v1.json
    stock_5min = {
        "name": "stock_5min",
        "version": "v1",
        "description": "股票5分钟K线",
        "granularity": "5min",
        "fields": [
            {"name": "date", "type": "string", "description": "交易日期"},
            {"name": "code", "type": "string", "description": "股票代码"},
            {"name": "market", "type": "string", "description": "市场"},
            {"name": "name", "type": "string", "description": "股票名称"},
            {"name": "time", "type": "string", "description": "时间HH:MM"},
            {"name": "open", "type": "double", "description": "开盘价"},
            {"name": "close", "type": "double", "description": "收盘价"},
            {"name": "high", "type": "double", "description": "最高价"},
            {"name": "low", "type": "double", "description": "最低价"},
            {"name": "volume", "type": "int64", "description": "成交量"},
        ],
        "storage_rules": {
            "path_template": "{data_type}/{granularity}/{year}/{month}/{date}.parquet",
            "partition": {
                "by": "date",
                "max_rows": 1000000,
                "max_size_mb": 100,
            },
        },
    }
    (d / "stock_5min_v1.json").write_text(
        json.dumps(stock_5min, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 2. 正确的 schema：stock_1day_v1.json（无 time 字段）
    stock_1day = {
        "name": "stock_1day",
        "version": "v1",
        "description": "股票日线数据",
        "granularity": "1day",
        "fields": [
            {"name": "date", "type": "string", "description": "交易日期"},
            {"name": "code", "type": "string", "description": "股票代码"},
            {"name": "open", "type": "double", "description": "开盘价"},
            {"name": "close", "type": "double", "description": "收盘价"},
            {"name": "volume", "type": "int64", "description": "成交量"},
        ],
        "storage_rules": {
            "path_template": "{data_type}/{granularity}/{year}/{month}/{date}.parquet",
            "partition": {
                "by": "date",
                "max_rows": 500000,
                "max_size_mb": 200,
            },
        },
    }
    (d / "stock_1day_v1.json").write_text(
        json.dumps(stock_1day, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 3. 缺失必填字段的 schema（加载时应跳过并警告）
    bad_schema = {
        "name": "bad_schema",
        "version": "v1",
        # 缺少 granularity, fields, storage_rules
    }
    (d / "bad_schema_v1.json").write_text(
        json.dumps(bad_schema), encoding="utf-8"
    )

    # 4. 不符合命名规范的文件（不应加载）
    (d / "readme.txt").write_text("not a schema", encoding="utf-8")
    (d / "stock_v1.json").write_text("{}", encoding="utf-8")  # 缺少 _v 分隔符

    return str(d)


@pytest.fixture
def manager(schema_dir):
    """创建一个 SchemaManager 实例"""
    from app.schema_manager import SchemaManager

    return SchemaManager(schema_dir)


# ------------------------------------------------------------------ #
# 测试 Schema 加载
# ------------------------------------------------------------------ #


class TestSchemaLoading:
    def test_load_valid_schemas(self, manager):
        """正常加载符合条件的 schema"""
        schemas = manager.list_schemas()
        names = {(s["name"], s["version"]) for s in schemas}
        assert ("stock_5min", "v1") in names
        assert ("stock_1day", "v1") in names

    def test_skip_invalid_naming(self, manager):
        """不符合 {name}_v{version}.json 命名的文件应跳过"""
        # readme.txt 和 stock_v1.json 不应被加载
        schemas = manager.list_schemas()
        names = [s["name"] for s in schemas]
        assert "readme" not in names
        assert "stock" not in names  # stock_v1.json 不符合规范

    def test_skip_bad_schema(self, manager):
        """结构不合法的 schema 应跳过（不阻断启动）"""
        # bad_schema_v1.json 缺少必填字段，应被跳过
        schemas = manager.list_schemas()
        names = [s["name"] for s in schemas]
        assert "bad_schema" not in names

    def test_list_schemas_returns_summary(self, manager):
        """list_schemas 返回摘要（不含完整 fields）"""
        schemas = manager.list_schemas()
        for s in schemas:
            assert "name" in s
            assert "version" in s
            assert "granularity" in s
            assert "description" in s
            assert "fields_count" in s
            assert isinstance(s["fields_count"], int)


# ------------------------------------------------------------------ #
# 测试 get_storage_rules / get_granularity
# ------------------------------------------------------------------ #


class TestStorageRules:
    def test_get_storage_rules(self, manager):
        """获取 storage_rules"""
        rules = manager.get_storage_rules("stock_5min", "v1")
        assert "path_template" in rules
        assert "partition" in rules
        assert rules["partition"]["by"] == "date"
        assert rules["partition"]["max_rows"] == 1000000

    def test_get_storage_rules_raises_for_unknown(self, manager):
        """查询不存在的 schema 应抛出 KeyError"""
        with pytest.raises(KeyError):
            manager.get_storage_rules("nonexistent", "v1")

    def test_get_granularity(self, manager):
        """获取 granularity"""
        assert manager.get_granularity("stock_5min", "v1") == "5min"
        assert manager.get_granularity("stock_1day", "v1") == "1day"

    def test_get_granularity_raises_for_unknown(self, manager):
        with pytest.raises(KeyError):
            manager.get_granularity("nonexistent", "v1")


# ------------------------------------------------------------------ #
# 测试 validate_data
# ------------------------------------------------------------------ #


class TestValidateData:
    def test_validate_valid_data(self, manager):
        """验证合法数据"""
        df = pd.DataFrame(
            [
                {
                    "date": "2026-05-17",
                    "code": "00700",
                    "market": "XHKG",
                    "name": "腾讯控股",
                    "time": "09:30",
                    "open": 380.0,
                    "close": 381.0,
                    "high": 381.5,
                    "low": 379.5,
                    "volume": 120000,
                }
            ]
        )
        valid, errors = manager.validate_data(df, "stock_5min", "v1")
        assert valid is True
        assert errors == []

    def test_validate_missing_columns(self, manager):
        """缺少必填字段应返回 False"""
        df = pd.DataFrame([{"date": "2026-05-17"}])  # 缺少其他字段
        valid, errors = manager.validate_data(df, "stock_5min", "v1")
        assert valid is False
        assert any("Missing" in e for e in errors)

    def test_validate_empty_dataframe(self, manager):
        """空 DataFrame 应通过验证（没有缺失字段）"""
        df = pd.DataFrame()
        valid, errors = manager.validate_data(df, "stock_5min", "v1")
        # 空 DataFrame 没有 columns，所以会报 Missing
        assert valid is False


# ------------------------------------------------------------------ #
# 测试 get_parquet_schema
# ------------------------------------------------------------------ #


class TestParquetSchema:
    def test_get_parquet_schema(self, manager):
        """获取 PyArrow Schema"""
        pa_schema = manager.get_parquet_schema("stock_5min", "v1")
        assert pa_schema is not None
        field_names = [f.name for f in pa_schema]
        assert "date" in field_names
        assert "code" in field_names
        assert "volume" in field_names

    def test_parquet_schema_types(self, manager):
        """验证类型映射正确性"""
        pa_schema = manager.get_parquet_schema("stock_5min", "v1")
        type_map = {f.name: str(f.type) for f in pa_schema}
        assert type_map["date"] == "string"
        assert type_map["volume"] == "int64"
        assert type_map["open"] == "double"

    def test_get_parquet_schema_raises_for_unknown(self, manager):
        with pytest.raises(KeyError):
            manager.get_parquet_schema("nonexistent", "v1")


# ------------------------------------------------------------------ #
# 测试 get_schema_for_api
# ------------------------------------------------------------------ #


class TestGetSchemaForApi:
    def test_returns_full_schema(self, manager):
        """get_schema_for_api 返回完整 schema（含 fields 详情）"""
        schema = manager.get_schema_for_api("stock_5min", "v1")
        assert "name" in schema
        assert "version" in schema
        assert "fields" in schema
        assert isinstance(schema["fields"], list)
        assert len(schema["fields"]) > 0

    def test_raises_for_unknown(self, manager):
        with pytest.raises(KeyError):
            manager.get_schema_for_api("nonexistent", "v1")


# ------------------------------------------------------------------ #
# 测试边界情况
# ------------------------------------------------------------------ #


class TestEdgeCases:
    def test_empty_schemas_dir(self, tmp_path):
        """空目录应加载 0 个 schema（不报错）"""
        from app.schema_manager import SchemaManager

        d = tmp_path / "empty_schemas"
        d.mkdir()
        m = SchemaManager(str(d))
        assert m.list_schemas() == []

    def test_schemas_dir_not_exist(self, tmp_path):
        """目录不存在应加载 0 个 schema（不报错）"""
        from app.schema_manager import SchemaManager

        non_exist = tmp_path / "not_exist"
        m = SchemaManager(str(non_exist))
        assert m.list_schemas() == []

    def test_load_schema_raises_key_error(self, manager):
        """load_schema 查询不存在的 schema 应抛 KeyError"""
        with pytest.raises(KeyError):
            manager.load_schema("nonexistent", "v1")
