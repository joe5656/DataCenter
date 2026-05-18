"""
Tests for DataProcessor (§2.7)

测试覆盖：
1. write_data（分组写入 / 重复检查 / schema 验证）
2. read_data（日期范围 / 过滤）
3. validate_schema（有效 / 无效数据）

REQ-003 设计：
- write_data 接收 DataFrame，自动按 storage_rule 分组写入
- 不依赖特定业务字段（如 market/code）
- 过滤通过 **filters 传递
"""

import json
from pathlib import Path

import pandas as pd
import pytest


# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #


@pytest.fixture
def schema_dir(tmp_path):
    """创建测试 schema（REQ-003 格式）"""
    d = tmp_path / "schemas"
    d.mkdir()

    stock_5min = {
        "name": "stock_5min",
        "version": "v1",
        "data_schema": {
            "date": "string",
            "code": "string",
            "market": "string",
            "time": "string",
            "open": "double",
        },
        "storage_rule": "{schema.name}/{schema.market}/{schema.date}.parquet",
    }
    (d / "stock_5min_v1.json").write_text(
        json.dumps(stock_5min, ensure_ascii=False, indent=2)
    )
    return str(d)


@pytest.fixture
def data_processor(schema_dir, tmp_path, monkeypatch):
    """创建 DataProcessor 实例"""
    from app.schema_manager import SchemaManager
    from app.index_manager import IndexManager
    from app.storage_manager import StorageManager
    from app.data_processor import DataProcessor

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATACENTER_DATA_DIR", str(data_dir))

    sm = SchemaManager(schema_dir)
    im = IndexManager(sm)
    st = StorageManager()
    return DataProcessor(sm, im, st)


# ------------------------------------------------------------------ #
# 测试 write_data
# ------------------------------------------------------------------ #


class TestWriteData:
    def test_write_single_group(self, data_processor):
        """写入单个文件"""
        df = pd.DataFrame({
            "date": ["2026-05-17"],
            "code": ["00700"],
            "market": ["XHKG"],
            "time": ["09:30"],
            "open": [380.0],
        })

        result = data_processor.write_data(
            data=df,
            data_type="stock_5min",
            version="v1",
        )

        assert result["success"] is True
        assert result["total_rows"] == 1
        assert result["files_written"] == 1
        assert len(result["file_paths"]) == 1

    def test_write_multiple_groups(self, data_processor):
        """按 market 分组写入多个文件"""
        df = pd.DataFrame({
            "date": ["2026-05-17"] * 2,
            "code": ["00700", "600000"],
            "market": ["XHKG", "XSHG"],
            "time": ["09:30", "09:30"],
            "open": [380.0, 10.0],
        })

        result = data_processor.write_data(
            data=df,
            data_type="stock_5min",
            version="v1",
        )

        assert result["success"] is True
        assert result["total_rows"] == 2
        assert result["files_written"] == 2

    def test_write_append_mode(self, data_processor):
        """append 模式追加数据"""
        df1 = pd.DataFrame({
            "date": ["2026-05-17"],
            "code": ["00700"],
            "market": ["XHKG"],
            "time": ["09:30"],
            "open": [380.0],
        })
        df2 = pd.DataFrame({
            "date": ["2026-05-17"],
            "code": ["00700"],
            "market": ["XHKG"],
            "time": ["09:31"],
            "open": [381.0],
        })

        r1 = data_processor.write_data(df1, "stock_5min", "v1")
        assert r1["success"] is True

        r2 = data_processor.write_data(df2, "stock_5min", "v1", mode="append")
        assert r2["success"] is True

    def test_write_overwrite_mode(self, data_processor):
        """overwrite 模式覆盖数据"""
        df1 = pd.DataFrame({
            "date": ["2026-05-17"],
            "code": ["00700"],
            "market": ["XHKG"],
            "time": ["09:30"],
            "open": [380.0],
        })
        df2 = pd.DataFrame({
            "date": ["2026-05-17"],
            "code": ["00700"],
            "market": ["XHKG"],
            "time": ["09:31"],
            "open": [381.0],
        })

        data_processor.write_data(df1, "stock_5min", "v1")
        r = data_processor.write_data(df2, "stock_5min", "v1", mode="overwrite")

        assert r["success"] is True

    def test_write_schema_validation_fails(self, data_processor):
        """Schema 验证失败"""
        df = pd.DataFrame({
            "date": ["2026-05-17"],
            # 缺少 code, market, time, open
        })

        result = data_processor.write_data(df, "stock_5min", "v1")

        assert result["success"] is False
        assert "errors" in result

    def test_write_duplicate_check(self, data_processor):
        """重复检查（append 模式）"""
        df = pd.DataFrame({
            "date": ["2026-05-17"],
            "code": ["00700"],
            "market": ["XHKG"],
            "time": ["09:30"],
            "open": [380.0],
        })

        # 第一次写入
        data_processor.write_data(df, "stock_5min", "v1")

        # 第二次写入相同数据（重复）
        result = data_processor.write_data(
            df, "stock_5min", "v1",
            check_duplicates=True,
            remove_duplicates=False,
        )

        assert result["success"] is False
        assert "duplicate" in str(result["errors"]).lower()

    def test_write_duplicate_auto_remove(self, data_processor):
        """自动去重"""
        df = pd.DataFrame({
            "date": ["2026-05-17"],
            "code": ["00700"],
            "market": ["XHKG"],
            "time": ["09:30"],
            "open": [380.0],
        })

        data_processor.write_data(df, "stock_5min", "v1")

        result = data_processor.write_data(
            df, "stock_5min", "v1",
            check_duplicates=True,
            remove_duplicates=True,
        )

        assert result["success"] is True
        assert result["duplicates_found"] == 1
        assert result["duplicates_removed"] == 1


# ------------------------------------------------------------------ #
# 测试 read_data
# ------------------------------------------------------------------ #


class TestReadData:
    def test_read_empty(self, data_processor):
        """读取空范围"""
        df = data_processor.read_data(
            data_type="stock_5min",
            version="v1",
            date="2026-05-17",
            market="XHKG",
        )

        assert df.empty

    def test_read_after_write(self, data_processor):
        """写入后读取"""
        df_write = pd.DataFrame({
            "date": ["2026-05-17"],
            "code": ["00700"],
            "market": ["XHKG"],
            "time": ["09:30"],
            "open": [380.0],
        })

        data_processor.write_data(df_write, "stock_5min", "v1")

        df_read = data_processor.read_data(
            data_type="stock_5min",
            version="v1",
            date="2026-05-17",
        )


        assert len(df_read) == 1
        assert df_read.iloc[0]["code"] == "00700"

    def test_read_filter_by_code(self, data_processor):
        """按股票代码过滤"""
        df = pd.DataFrame({
            "date": ["2026-05-17"] * 2,
            "code": ["00700", "00701"],
            "market": ["XHKG", "XHKG"],
            "time": ["09:30", "09:31"],
            "open": [380.0, 381.0],
        })

        data_processor.write_data(df, "stock_5min", "v1")

        # 只读取 00700
        df_filtered = data_processor.read_data(
            data_type="stock_5min",
            version="v1",
            date="2026-05-17",
            market="XHKG",
            code="00700",
        )

        assert len(df_filtered) == 1
        assert df_filtered.iloc[0]["code"] == "00700"


# ------------------------------------------------------------------ #
# 测试 validate_schema
# ------------------------------------------------------------------ #


class TestValidateSchema:
    def test_valid_data(self, data_processor):
        """有效数据"""
        df = pd.DataFrame({
            "date": ["2026-05-17"],
            "code": ["00700"],
            "market": ["XHKG"],
            "time": ["09:30"],
            "open": [380.0],
        })

        is_valid, errors = data_processor.validate_schema(df, "stock_5min", "v1")
        assert is_valid is True
        assert errors == []

    def test_missing_column(self, data_processor):
        """缺少必需字段"""
        df = pd.DataFrame({
            "date": ["2026-05-17"],
            # 缺少 code, market, time, open
        })

        is_valid, errors = data_processor.validate_schema(df, "stock_5min", "v1")
        assert is_valid is False
        assert len(errors) > 0
