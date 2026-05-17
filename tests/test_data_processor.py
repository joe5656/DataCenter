"""
Tests for DataProcessor (§2.7)

测试覆盖：
1. write_data（正常写入 / 重复检查 / schema 验证）
2. read_data（单文件 / 多文件 / 过滤）
3. validate_schema（有效 / 无效数据）
4. 内部方法（_read_existing / _find_duplicates / _remove_duplicates）
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import pytest


# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #


@pytest.fixture
def schema_dir(tmp_path):
    """创建一个临时 schemas/ 目录"""
    d = tmp_path / "schemas"
    d.mkdir()

    stock_5min = {
        "name": "stock_5min",
        "version": "v1",
        "description": "股票5分钟K线",
        "granularity": "5min",
        "fields": [
            {"name": "date", "type": "string"},
            {"name": "code", "type": "string"},
            {"name": "market", "type": "string"},
            {"name": "time", "type": "string"},
            {"name": "open", "type": "double"},
        ],
        "storage_rules": {
            "path_template": "{data_type}/{granularity}/{market}/{year}/{month}/{date}.parquet",
            "partition": {"by": "date", "max_rows": 1000000, "max_size_mb": 100},
        },
    }
    (d / "stock_5min_v1.json").write_text(
        json.dumps(stock_5min, ensure_ascii=False, indent=2)
    )
    return str(d)


@pytest.fixture
def data_processor(schema_dir, tmp_path, monkeypatch):
    """创建一个 DataProcessor 实例"""
    from app.schema_manager import SchemaManager
    from app.index_manager import IndexManager
    from app.storage_manager import StorageManager
    from app.data_processor import DataProcessor

    # 设置 DATA_DIR（使用 monkeypatch 设置环境变量，这样 Config() 能正确读取）
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATACENTER_DATA_DIR", str(data_dir))

    sm = SchemaManager(schema_dir)
    im = IndexManager(sm)
    st = StorageManager()
    dp = DataProcessor(sm, im, st)
    return dp


# ------------------------------------------------------------------ #
# 测试 write_data
# ------------------------------------------------------------------ #


class TestWriteData:
    def test_write_basic(self, data_processor, tmp_path):
        """基本写入功能"""
        df = pd.DataFrame(
            {
                "date": ["2026-05-17"],
                "code": ["00700"],
                "market": ["XHKG"],
                "time": ["09:30"],
                "open": [380.0],
            }
        )
        result = data_processor.write_data(
            data=df,
            data_type="stock_5min",
            date="2026-05-17",
            version="v1",
            market="XHKG",
        )
        assert result["success"] is True
        assert result["rows_written"] == 1
        assert os.path.exists(result["file_path"])

    def test_write_append_mode(self, data_processor):
        """append 模式（默认）"""
        df1 = pd.DataFrame(
            {
                "date": ["2026-05-17"],
                "code": ["00700"],
                "market": ["XHKG"],
                "time": ["09:30"],
                "open": [380.0],
            }
        )
        df2 = pd.DataFrame(
            {
                "date": ["2026-05-17"],
                "code": ["00700"],
                "market": ["XHKG"],
                "time": ["09:31"],
                "open": [381.0],
            }
        )
        # 第一次写入
        r1 = data_processor.write_data(
            data=df1, data_type="stock_5min", date="2026-05-17", version="v1", market="XHKG"
        )
        assert r1["success"] is True

        # 第二次 append
        r2 = data_processor.write_data(
            data=df2,
            data_type="stock_5min",
            date="2026-05-17",
            version="v1",
            market="XHKG",
            mode="append",
        )
        assert r2["success"] is True

        # 读取验证
        df = data_processor.read_data(
            data_type="stock_5min",
            start_date="2026-05-17",
            end_date="2026-05-17",
            version="v1",
            market="XHKG",
        )
        assert len(df) == 2

    def test_write_overwrite_mode(self, data_processor):
        """overwrite 模式"""
        df1 = pd.DataFrame(
            {
                "date": ["2026-05-17"],
                "code": ["00700"],
                "market": ["XHKG"],
                "time": ["09:30"],
                "open": [380.0],
            }
        )
        df2 = pd.DataFrame(
            {
                "date": ["2026-05-17"],
                "code": ["00700"],
                "market": ["XHKG"],
                "time": ["09:31"],
                "open": [381.0],
            }
        )
        # 第一次写入
        data_processor.write_data(
            data=df1, data_type="stock_5min", date="2026-05-17", version="v1", market="XHKG"
        )
        # 第二次 overwrite
        r = data_processor.write_data(
            data=df2,
            data_type="stock_5min",
            date="2026-05-17",
            version="v1",
            market="XHKG",
            mode="overwrite",
        )
        assert r["success"] is True

        # 读取验证（应该只有第二行）
        df = data_processor.read_data(
            data_type="stock_5min",
            start_date="2026-05-17",
            end_date="2026-05-17",
            version="v1",
            market="XHKG",
        )
        assert len(df) == 1

    def test_write_schema_validation_fails(self, data_processor):
        """Schema 验证失败"""
        # 缺少必需字段
        df = pd.DataFrame(
            {
                "date": ["2026-05-17"],
                # 缺少 code, market, time, open
            }
        )
        result = data_processor.write_data(
            data=df,
            data_type="stock_5min",
            date="2026-05-17",
            version="v1",
            market="XHKG",
        )
        assert result["success"] is False
        assert "errors" in result

    def test_write_duplicate_check(self, data_processor):
        """重复检查（append 模式）"""
        df = pd.DataFrame(
            {
                "date": ["2026-05-17"],
                "code": ["00700"],
                "market": ["XHKG"],
                "time": ["09:30"],
                "open": [380.0],
            }
        )
        # 第一次写入
        data_processor.write_data(
            data=df, data_type="stock_5min", date="2026-05-17", version="v1", market="XHKG"
        )
        # 第二次写入相同数据（重复）
        result = data_processor.write_data(
            data=df,
            data_type="stock_5min",
            date="2026-05-17",
            version="v1",
            market="XHKG",
            check_duplicates=True,
            remove_duplicates=False,  # 不自动去重，应该报错
        )
        assert result["success"] is False
        assert "duplicate" in str(result["errors"]).lower()


# ------------------------------------------------------------------ #
# 测试 read_data
# ------------------------------------------------------------------ #


class TestReadData:
    def test_read_empty(self, data_processor):
        """读取空范围"""
        df = data_processor.read_data(
            data_type="stock_5min",
            start_date="2026-05-17",
            end_date="2026-05-17",
            version="v1",
            market="XHKG",
        )
        assert len(df) == 0

    def test_read_after_write(self, data_processor):
        """写入后读取"""
        df_write = pd.DataFrame(
            {
                "date": ["2026-05-17"],
                "code": ["00700"],
                "market": ["XHKG"],
                "time": ["09:30"],
                "open": [380.0],
            }
        )
        data_processor.write_data(
            data=df_write,
            data_type="stock_5min",
            date="2026-05-17",
            version="v1",
            market="XHKG",
        )

        df_read = data_processor.read_data(
            data_type="stock_5min",
            start_date="2026-05-17",
            end_date="2026-05-17",
            version="v1",
            market="XHKG",
        )
        assert len(df_read) == 1
        assert df_read.iloc[0]["code"] == "00700"

    def test_read_filter_by_code(self, data_processor):
        """按股票代码过滤"""
        df = pd.DataFrame(
            {
                "date": ["2026-05-17"] * 2,
                "code": ["00700", "00701"],
                "market": ["XHKG", "XHKG"],
                "time": ["09:30", "09:31"],
                "open": [380.0, 381.0],
            }
        )
        data_processor.write_data(
            data=df, data_type="stock_5min", date="2026-05-17", version="v1", market="XHKG"
        )

        # 只读取 00700
        df_filtered = data_processor.read_data(
            data_type="stock_5min",
            start_date="2026-05-17",
            end_date="2026-05-17",
            version="v1",
            market="XHKG",
            codes=["00700"],
        )
        assert len(df_filtered) == 1
        assert df_filtered.iloc[0]["code"] == "00700"


# ------------------------------------------------------------------ #
# 测试 validate_schema
# ------------------------------------------------------------------ #


class TestValidateSchema:
    def test_valid_data(self, data_processor):
        """有效数据"""
        df = pd.DataFrame(
            {
                "date": ["2026-05-17"],
                "code": ["00700"],
                "market": ["XHKG"],
                "time": ["09:30"],
                "open": [380.0],
            }
        )
        is_valid, errors = data_processor.validate_schema(df, "stock_5min", "v1")
        assert is_valid is True
        assert len(errors) == 0

    def test_missing_column(self, data_processor):
        """缺少必需字段"""
        df = pd.DataFrame(
            {
                "date": ["2026-05-17"],
                # 缺少 code, market, time, open
            }
        )
        is_valid, errors = data_processor.validate_schema(df, "stock_5min", "v1")
        assert is_valid is False
        assert len(errors) > 0
        assert any("Missing" in e for e in errors)


# ------------------------------------------------------------------ #
# 测试内部方法
# ------------------------------------------------------------------ #


class TestInternalMethods:
    def test_read_existing_no_file(self, data_processor):
        """读取不存在的文件"""
        df = data_processor._read_existing(
            data_type="stock_5min",
            date="2026-05-17",
            version="v1",
            market="XHKG",
        )
        assert len(df) == 0

    def test_find_duplicates(self, data_processor):
        """找出重复数据"""
        existing = pd.DataFrame(
            {
                "date": ["2026-05-17"],
                "code": ["00700"],
                "time": ["09:30"],
                "open": [380.0],
            }
        )
        new = pd.DataFrame(
            {
                "date": ["2026-05-17", "2026-05-17"],
                "code": ["00700", "00701"],
                "time": ["09:30", "09:31"],
                "open": [380.0, 381.0],
            }
        )
        duplicates = data_processor._find_duplicates(new, existing, "stock_5min", "v1")
        assert len(duplicates) == 1  # 第一行重复

    def test_remove_duplicates(self, data_processor):
        """移除重复数据"""
        data = pd.DataFrame(
            {
                "date": ["2026-05-17", "2026-05-17"],
                "code": ["00700", "00701"],
                "time": ["09:30", "09:31"],
                "open": [380.0, 381.0],
            }
        )
        duplicates = data.iloc[[0]]  # 第一行是重复的
        result = data_processor._remove_duplicates(data, duplicates)
        assert len(result) == 1
        assert result.iloc[0]["code"] == "00701"
