"""
Tests for SchemaManager (REQ-003)

测试覆盖：
1. Schema 加载（正常 / 缺失字段 / 类型错误）
2. data_schema 验证（非 dict / 嵌套 / 空 / 非法类型）
3. storage_rule 验证（不以 .parquet 结尾 / 引用未定义字段）
4. {schema.xxx} 引用提取
5. get_storage_rule / get_data_schema
6. validate_data
7. get_parquet_schema
8. list_schemas / get_schema_for_api
9. 边界情况
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
        "data_schema": {
            "date": "string",
            "code": "string",
            "market": "string",
            "name": "string",
            "time": "string",
            "open": "double",
            "close": "double",
            "high": "double",
            "low": "double",
            "volume": "int64",
        },
        "storage_rule": "{schema.name}/{schema.date}.parquet",
    }
    (d / "stock_5min_v1.json").write_text(
        json.dumps(stock_5min, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 2. 正确的 schema：stock_1day_v1.json（日线，用年月分目录）
    stock_1day = {
        "name": "stock_1day",
        "version": "v1",
        "data_schema": {
            "date": "string",
            "code": "string",
            "open": "double",
            "close": "double",
            "volume": "int64",
        },
        "storage_rule": "{schema.name}/{schema.date}.parquet",
    }
    (d / "stock_1day_v1.json").write_text(
        json.dumps(stock_1day, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 3. 缺失必填字段的 schema（加载时应跳过并警告）
    bad_missing = {
        "name": "bad_missing",
        "version": "v1",
        # 缺少 data_schema 和 storage_rule
    }
    (d / "bad_missing_v1.json").write_text(
        json.dumps(bad_missing), encoding="utf-8"
    )

    # 4. data_schema 不是 key-value 的（嵌套）
    bad_nested = {
        "name": "bad_nested",
        "version": "v1",
        "data_schema": {
            "date": "string",
            "extra": {"nested": "value"},
        },
        "storage_rule": "{schema.name}/{schema.date}.parquet",
    }
    (d / "bad_nested_v1.json").write_text(
        json.dumps(bad_nested), encoding="utf-8"
    )

    # 5. storage_rule 不以 .parquet 结尾
    bad_no_parquet = {
        "name": "bad_no_parquet",
        "version": "v1",
        "data_schema": {
            "date": "string",
        },
        "storage_rule": "{schema.name}/{schema.date}",
    }
    (d / "bad_no_parquet_v1.json").write_text(
        json.dumps(bad_no_parquet), encoding="utf-8"
    )

    # 6. storage_rule 引用了 data_schema 中不存在的字段
    bad_undefined_ref = {
        "name": "bad_undef_ref",
        "version": "v1",
        "data_schema": {
            "date": "string",
        },
        "storage_rule": "{schema.name}/{schema.undefined_field}.parquet",
    }
    (d / "bad_undef_ref_v1.json").write_text(
        json.dumps(bad_undefined_ref), encoding="utf-8"
    )

    # 7. data_schema 包含非法类型
    bad_type = {
        "name": "bad_type",
        "version": "v1",
        "data_schema": {
            "date": "string",
            "price": "decimal",  # 不在 _TYPE_MAP 中
        },
        "storage_rule": "{schema.name}/{schema.date}.parquet",
    }
    (d / "bad_type_v1.json").write_text(
        json.dumps(bad_type), encoding="utf-8"
    )

    # 8. 空 data_schema
    bad_empty_ds = {
        "name": "bad_empty_ds",
        "version": "v1",
        "data_schema": {},
        "storage_rule": "{schema.name}.parquet",
    }
    (d / "bad_empty_ds_v1.json").write_text(
        json.dumps(bad_empty_ds), encoding="utf-8"
    )

    # 9. 不符合命名规范的文件（不应加载）
    (d / "readme.txt").write_text("not a schema", encoding="utf-8")
    (d / "stock_v1.json").write_text("{}", encoding="utf-8")

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
        schemas = manager.list_schemas()
        names = [s["name"] for s in schemas]
        assert "readme" not in names
        assert "stock" not in names

    def test_skip_missing_fields(self, manager):
        """缺少必填字段的 schema 应跳过"""
        schemas = manager.list_schemas()
        names = [s["name"] for s in schemas]
        assert "bad_missing" not in names

    def test_skip_nested_data_schema(self, manager):
        """data_schema 嵌套的 schema 应跳过"""
        schemas = manager.list_schemas()
        names = [s["name"] for s in schemas]
        assert "bad_nested" not in names

    def test_skip_no_parquet_suffix(self, manager):
        """storage_rule 不以 .parquet 结尾的 schema 应跳过"""
        schemas = manager.list_schemas()
        names = [s["name"] for s in schemas]
        assert "bad_no_parquet" not in names

    def test_skip_undefined_ref(self, manager):
        """storage_rule 引用未定义字段的 schema 应跳过"""
        schemas = manager.list_schemas()
        names = [s["name"] for s in schemas]
        assert "bad_undef_ref" not in names

    def test_skip_bad_type(self, manager):
        """data_schema 包含非法类型的 schema 应跳过"""
        schemas = manager.list_schemas()
        names = [s["name"] for s in schemas]
        assert "bad_type" not in names

    def test_skip_empty_data_schema(self, manager):
        """空 data_schema 的 schema 应跳过"""
        schemas = manager.list_schemas()
        names = [s["name"] for s in schemas]
        assert "bad_empty_ds" not in names

    def test_list_schemas_returns_summary(self, manager):
        """list_schemas 返回摘要"""
        schemas = manager.list_schemas()
        for s in schemas:
            assert "name" in s
            assert "version" in s
            assert "storage_rule" in s
            assert "fields_count" in s
            assert isinstance(s["fields_count"], int)


# ------------------------------------------------------------------ #
# 测试 _extract_schema_refs
# ------------------------------------------------------------------ #


class TestExtractSchemaRefs:
    def test_single_ref(self):
        """提取单个 {schema.xxx}"""
        from app.schema_manager import SchemaManager
        refs = SchemaManager._extract_schema_refs("{schema.name}/{schema.date}.parquet")
        assert refs == ["name", "date"]

    def test_no_refs(self):
        """无 {schema.xxx} 引用"""
        from app.schema_manager import SchemaManager
        refs = SchemaManager._extract_schema_refs("static/path.parquet")
        assert refs == []

    def test_duplicate_refs(self):
        """同一字段引用多次"""
        from app.schema_manager import SchemaManager
        refs = SchemaManager._extract_schema_refs("{schema.name}/{schema.name}.parquet")
        assert refs == ["name", "name"]

    def test_mixed_braces(self):
        """混合 {schema.xxx} 和普通文本"""
        from app.schema_manager import SchemaManager
        refs = SchemaManager._extract_schema_refs("data/{schema.name}/year={schema.date}/file.parquet")
        assert refs == ["name", "date"]


# ------------------------------------------------------------------ #
# 直接测试 _validate_schema（精准验证逻辑，不依赖加载流程）
# ------------------------------------------------------------------ #


class TestValidateSchema:
    """直接调用 _validate_schema，精准测试每条检查规则"""

    def _make_mgr(self):
        from app.schema_manager import SchemaManager
        # 创建一个空目录的 manager，只用其 _validate_schema 方法
        import tempfile
        d = tempfile.mkdtemp()
        return SchemaManager(d)

    # --- 必填字段检查 ---

    def test_missing_name(self):
        m = self._make_mgr()
        with pytest.raises(ValueError, match="missing required field 'name'"):
            m._validate_schema({"version": "v1", "data_schema": {"x": "string"}, "storage_rule": "{schema.name}.parquet"}, "f.json")

    def test_missing_version(self):
        m = self._make_mgr()
        with pytest.raises(ValueError, match="missing required field 'version'"):
            m._validate_schema({"name": "t", "data_schema": {"x": "string"}, "storage_rule": "{schema.name}.parquet"}, "f.json")

    def test_missing_data_schema(self):
        m = self._make_mgr()
        with pytest.raises(ValueError, match="missing required field 'data_schema'"):
            m._validate_schema({"name": "t", "version": "v1", "storage_rule": "{schema.name}.parquet"}, "f.json")

    def test_missing_storage_rule(self):
        m = self._make_mgr()
        with pytest.raises(ValueError, match="missing required field 'storage_rule'"):
            m._validate_schema({"name": "t", "version": "v1", "data_schema": {"x": "string"}}, "f.json")

    # --- data_schema 检查 ---

    def test_data_schema_not_dict(self):
        m = self._make_mgr()
        with pytest.raises(ValueError, match="must be a key-value dict"):
            m._validate_schema({"name": "t", "version": "v1", "data_schema": "not a dict", "storage_rule": "{schema.name}.parquet"}, "f.json")

    def test_data_schema_list(self):
        m = self._make_mgr()
        with pytest.raises(ValueError, match="must be a key-value dict"):
            m._validate_schema({"name": "t", "version": "v1", "data_schema": [{"name": "x"}], "storage_rule": "{schema.name}.parquet"}, "f.json")

    def test_data_schema_empty(self):
        m = self._make_mgr()
        with pytest.raises(ValueError, match="must not be empty"):
            m._validate_schema({"name": "t", "version": "v1", "data_schema": {}, "storage_rule": "{schema.name}.parquet"}, "f.json")

    def test_data_schema_value_is_list(self):
        m = self._make_mgr()
        with pytest.raises(ValueError, match="str->str"):
            m._validate_schema({"name": "t", "version": "v1", "data_schema": {"x": [1, 2]}, "storage_rule": "{schema.name}.parquet"}, "f.json")

    def test_data_schema_value_is_dict(self):
        m = self._make_mgr()
        with pytest.raises(ValueError, match="str->str"):
            m._validate_schema({"name": "t", "version": "v1", "data_schema": {"x": {"nested": True}}, "storage_rule": "{schema.name}.parquet"}, "f.json")

    def test_data_schema_value_is_int(self):
        m = self._make_mgr()
        with pytest.raises(ValueError, match="str->str"):
            m._validate_schema({"name": "t", "version": "v1", "data_schema": {"x": 42}, "storage_rule": "{schema.name}.parquet"}, "f.json")

    def test_data_schema_unsupported_type(self):
        m = self._make_mgr()
        with pytest.raises(ValueError, match="unsupported type 'decimal'"):
            m._validate_schema({"name": "t", "version": "v1", "data_schema": {"x": "decimal"}, "storage_rule": "{schema.name}.parquet"}, "f.json")

    def test_data_schema_unsupported_type_varchar(self):
        m = self._make_mgr()
        with pytest.raises(ValueError, match="unsupported type 'varchar'"):
            m._validate_schema({"name": "t", "version": "v1", "data_schema": {"x": "varchar"}, "storage_rule": "{schema.name}.parquet"}, "f.json")

    def test_data_schema_all_supported_types(self):
        """所有 _TYPE_MAP 中的类型都应通过"""
        m = self._make_mgr()
        schema = {
            "name": "t", "version": "v1",
            "data_schema": {
                "f_string": "string", "f_int64": "int64", "f_int32": "int32",
                "f_int16": "int16", "f_int8": "int8", "f_uint64": "uint64",
                "f_float": "float", "f_double": "double", "f_bool": "bool",
                "f_date": "date", "f_datetime": "datetime", "f_timestamp": "timestamp",
            },
            "storage_rule": "{schema.name}/{schema.f_string}.parquet",
        }
        m._validate_schema(schema, "all_types.json")  # 不抛异常即通过

    # --- storage_rule 检查 ---

    def test_storage_rule_not_string(self):
        m = self._make_mgr()
        with pytest.raises(ValueError, match="must be a string"):
            m._validate_schema({"name": "t", "version": "v1", "data_schema": {"x": "string"}, "storage_rule": 123}, "f.json")

    def test_storage_rule_is_list(self):
        m = self._make_mgr()
        with pytest.raises(ValueError, match="must be a string"):
            m._validate_schema({"name": "t", "version": "v1", "data_schema": {"x": "string"}, "storage_rule": ["a"]}, "f.json")

    def test_storage_rule_no_parquet_suffix(self):
        m = self._make_mgr()
        with pytest.raises(ValueError, match="must end with '.parquet'"):
            m._validate_schema({"name": "t", "version": "v1", "data_schema": {"x": "string"}, "storage_rule": "{schema.name}/{schema.x}.csv"}, "f.json")

    def test_storage_rule_no_suffix_at_all(self):
        m = self._make_mgr()
        with pytest.raises(ValueError, match="must end with '.parquet'"):
            m._validate_schema({"name": "t", "version": "v1", "data_schema": {"x": "string"}, "storage_rule": "{schema.name}"}, "f.json")

    def test_storage_rule_dot_parquet_in_middle(self):
        """仅含 .parquet 但不在末尾应失败"""
        m = self._make_mgr()
        with pytest.raises(ValueError, match="must end with '.parquet'"):
            m._validate_schema({"name": "t", "version": "v1", "data_schema": {"x": "string"}, "storage_rule": "{schema.name}.parquet/{schema.x}"}, "f.json")

    # --- {schema.xxx} 引用检查 ---

    def test_ref_builtin_name_ok(self):
        """{schema.name} 是内置引用，即使 data_schema 没有 name 字段也应通过"""
        m = self._make_mgr()
        schema = {"name": "t", "version": "v1", "data_schema": {"x": "string"}, "storage_rule": "{schema.name}/{schema.x}.parquet"}
        m._validate_schema(schema, "ok.json")  # 不抛异常

    def test_ref_builtin_version_ok(self):
        """{schema.version} 是内置引用"""
        m = self._make_mgr()
        schema = {"name": "t", "version": "v1", "data_schema": {"x": "string"}, "storage_rule": "{schema.version}/{schema.x}.parquet"}
        m._validate_schema(schema, "ok.json")  # 不抛异常

    def test_ref_undefined_field(self):
        m = self._make_mgr()
        with pytest.raises(ValueError, match="'undefined_field' is not defined in data_schema"):
            m._validate_schema({"name": "t", "version": "v1", "data_schema": {"x": "string"}, "storage_rule": "{schema.undefined_field}.parquet"}, "f.json")

    def test_ref_multiple_undefined(self):
        m = self._make_mgr()
        # 报第一个未定义的
        with pytest.raises(ValueError, match="'missing_a' is not defined in data_schema"):
            m._validate_schema({"name": "t", "version": "v1", "data_schema": {"x": "string"}, "storage_rule": "{schema.missing_a}/{schema.missing_b}.parquet"}, "f.json")

    def test_ref_no_schema_refs(self):
        """没有 {schema.xxx} 的静态路径也应通过"""
        m = self._make_mgr()
        schema = {"name": "t", "version": "v1", "data_schema": {"x": "string"}, "storage_rule": "static/path/data.parquet"}
        m._validate_schema(schema, "ok.json")  # 不抛异常

    def test_ref_field_defined_in_data_schema(self):
        """{schema.xxx} 引用 data_schema 中已有的字段"""
        m = self._make_mgr()
        schema = {"name": "t", "version": "v1", "data_schema": {"market": "string", "date": "string"}, "storage_rule": "{schema.name}/{schema.market}/{schema.date}.parquet"}
        m._validate_schema(schema, "ok.json")  # 不抛异常

    # --- 正常 schema 完整验证 ---

    def test_valid_schema_passes(self):
        m = self._make_mgr()
        schema = {
            "name": "test_type",
            "version": "v2",
            "data_schema": {"date": "string", "value": "double"},
            "storage_rule": "{schema.name}/{schema.date}.parquet",
        }
        m._validate_schema(schema, "valid.json")  # 不抛异常即通过

    def test_valid_schema_with_extra_top_level_fields(self):
        """schema 可以有额外顶层字段（如 description）"""
        m = self._make_mgr()
        schema = {
            "name": "test_type", "version": "v1",
            "description": "测试 schema",
            "author": "someone",
            "data_schema": {"date": "string"},
            "storage_rule": "{schema.name}.parquet",
        }
        m._validate_schema(schema, "ok.json")  # 不抛异常


# ------------------------------------------------------------------ #
# 测试 get_storage_rule / get_data_schema
# ------------------------------------------------------------------ #


class TestSchemaAccessors:
    def test_get_storage_rule(self, manager):
        """获取 storage_rule 路径模板"""
        rule = manager.get_storage_rule("stock_5min", "v1")
        assert rule == "{schema.name}/{schema.date}.parquet"

    def test_get_storage_rule_raises_for_unknown(self, manager):
        with pytest.raises(KeyError):
            manager.get_storage_rule("nonexistent", "v1")

    def test_get_data_schema(self, manager):
        """获取 data_schema 字典"""
        ds = manager.get_data_schema("stock_5min", "v1")
        assert isinstance(ds, dict)
        assert ds["date"] == "string"
        assert ds["code"] == "string"
        assert ds["volume"] == "int64"
        assert len(ds) == 10

    def test_get_data_schema_raises_for_unknown(self, manager):
        with pytest.raises(KeyError):
            manager.get_data_schema("nonexistent", "v1")


# ------------------------------------------------------------------ #
# 测试 validate_data
# ------------------------------------------------------------------ #


class TestValidateData:
    def test_validate_valid_data(self, manager):
        """验证合法数据"""
        df = pd.DataFrame([
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
        ])
        valid, errors = manager.validate_data(df, "stock_5min", "v1")
        assert valid is True
        assert errors == []

    def test_validate_missing_columns(self, manager):
        """缺少必填字段应返回 False"""
        df = pd.DataFrame([{"date": "2026-05-17"}])
        valid, errors = manager.validate_data(df, "stock_5min", "v1")
        assert valid is False
        assert any("Missing" in e for e in errors)

    def test_validate_empty_dataframe(self, manager):
        """空 DataFrame 应返回 False"""
        df = pd.DataFrame()
        valid, errors = manager.validate_data(df, "stock_5min", "v1")
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
        """get_schema_for_api 返回完整 schema"""
        schema = manager.get_schema_for_api("stock_5min", "v1")
        assert "name" in schema
        assert "version" in schema
        assert "data_schema" in schema
        assert "storage_rule" in schema
        assert isinstance(schema["data_schema"], dict)

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
