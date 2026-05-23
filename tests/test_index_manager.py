"""
Tests for IndexManager (§2.6)

测试覆盖：
1. get_write_paths（分组写入）
2. get_read_paths（单值/枚举/范围 filter，路径存在性检查）
3. to_absolute_path

REQ-003 设计：
- 接口面向所有 data_type，不依赖特定业务字段
- get_write_paths(data, data_type, version) -> {路径: 数据子集}
- get_read_paths(data_type, version, **filters) -> [实际存在路径]
  - filter: 单值/枚举/范围 {start, end}
  - 只返回有文件的路径
"""

import json
import os
import shutil
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture
def schema_dir(tmp_path):
    """创建测试 schema"""
    d = tmp_path / "schemas"
    d.mkdir()

    # stock_5min: 按 market + date 分组
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
        json.dumps(stock_5min, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # stock_1day: 只按 date 分组
    stock_1day = {
        "name": "stock_1day",
        "version": "v1",
        "data_schema": {
            "date": "string",
            "code": "string",
            "open": "double",
        },
        "storage_rule": "{schema.name}/{schema.date}.parquet",
    }
    (d / "stock_1day_v1.json").write_text(
        json.dumps(stock_1day, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return str(d)


@pytest.fixture
def index_manager(schema_dir, tmp_path, monkeypatch):
    """创建 IndexManager 实例"""
    from app.schema_manager import SchemaManager
    from app.index_manager import IndexManager
    from app.storage_manager import StorageManager

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("DATACENTER_DATA_DIR", str(data_dir))

    sm = SchemaManager(schema_dir)
    return IndexManager(sm)


@pytest.fixture
def storage_manager(tmp_path, monkeypatch):
    """创建 StorageManager 实例"""
    from app.storage_manager import StorageManager

    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("DATACENTER_DATA_DIR", str(data_dir))
    return StorageManager()


# ------------------------------------------------------------------ #
# 测试 get_write_paths
# ------------------------------------------------------------------ #


class TestGetWritePaths:
    def test_single_group(self, index_manager):
        """数据写入单个文件"""
        df = pd.DataFrame({
            "date": ["2026-05-17"] * 3,
            "code": ["00700", "00701", "00702"],
            "market": ["XHKG"] * 3,
            "time": ["09:30", "09:31", "09:32"],
            "open": [380.0, 381.0, 382.0],
        })

        result = index_manager.get_write_paths(df, "stock_5min", "v1")

        assert len(result) == 1
        assert "stock_5min/XHKG/2026-05-17.parquet" in result

    def test_multiple_groups_by_market(self, index_manager):
        """按 market 分组"""
        df = pd.DataFrame({
            "date": ["2026-05-17"] * 2,
            "code": ["00700", "600000"],
            "market": ["XHKG", "XSHG"],
            "time": ["09:30", "09:30"],
            "open": [380.0, 10.0],
        })

        result = index_manager.get_write_paths(df, "stock_5min", "v1")

        assert len(result) == 2


# ------------------------------------------------------------------ #
# 测试 get_read_paths
# ------------------------------------------------------------------ #


class TestGetReadPaths:
    def test_single_date(self, index_manager, storage_manager, tmp_path, monkeypatch):
        """单日读取（date=单值）"""
        # 先写入一个文件
        df = pd.DataFrame({
            "date": ["2026-05-17"],
            "code": ["00700"],
            "market": ["XHKG"],
            "time": ["09:30"],
            "open": [380.0],
        })

        paths = index_manager.get_write_paths(df, "stock_5min", "v1")
        for rel_path, sub_df in paths.items():
            abs_path = index_manager.to_absolute_path(rel_path)
            storage_manager.write_parquet(sub_df, abs_path)

        # 读取：date=单值
        result = index_manager.get_read_paths("stock_5min", "v1", date="2026-05-17")

        assert len(result) == 1
        assert "stock_5min/XHKG/2026-05-17.parquet" in result[0]

    def test_date_range(self, index_manager, storage_manager, tmp_path, monkeypatch):
        """日期范围（date={start, end}）"""
        # 写入 3 天数据
        for date in ["2026-05-17", "2026-05-18", "2026-05-19"]:
            df = pd.DataFrame({
                "date": [date],
                "code": ["00700"],
                "market": ["XHKG"],
                "time": ["09:30"],
                "open": [380.0],
            })
            paths = index_manager.get_write_paths(df, "stock_5min", "v1")
            for rel_path, sub_df in paths.items():
                abs_path = index_manager.to_absolute_path(rel_path)
                storage_manager.write_parquet(sub_df, abs_path)

        # 读取：date=范围
        result = index_manager.get_read_paths(
            "stock_5min", "v1",
            date={"start": "2026-05-17", "end": "2026-05-19"}
        )

        assert len(result) == 3

    def test_market_filter(self, index_manager, storage_manager, tmp_path, monkeypatch):
        """市场过滤（market=单值）"""
        # 写入两个市场数据
        for market in ["XHKG", "XSHG"]:
            df = pd.DataFrame({
                "date": ["2026-05-17"],
                "code": ["00700"],
                "market": [market],
                "time": ["09:30"],
                "open": [380.0],
            })
            paths = index_manager.get_write_paths(df, "stock_5min", "v1")
            for rel_path, sub_df in paths.items():
                abs_path = index_manager.to_absolute_path(rel_path)
                storage_manager.write_parquet(sub_df, abs_path)

        # 只读取 XHKG
        result = index_manager.get_read_paths("stock_5min", "v1", market="XHKG")

        assert len(result) == 1
        assert "XHKG" in result[0]

    def test_market_enum(self, index_manager, storage_manager, tmp_path, monkeypatch):
        """市场枚举（market=[list]）"""
        # 写入两个市场数据
        for market in ["XHKG", "XSHG", "XSHE"]:
            df = pd.DataFrame({
                "date": ["2026-05-17"],
                "code": ["00700"],
                "market": [market],
                "time": ["09:30"],
                "open": [380.0],
            })
            paths = index_manager.get_write_paths(df, "stock_5min", "v1")
            for rel_path, sub_df in paths.items():
                abs_path = index_manager.to_absolute_path(rel_path)
                storage_manager.write_parquet(sub_df, abs_path)

        # 枚举读取 XHKG 和 XSHG
        result = index_manager.get_read_paths(
            "stock_5min", "v1",
            market=["XHKG", "XSHG"]
        )

        assert len(result) == 2

    def test_no_matching_files(self, index_manager):
        """没有匹配文件时返回空列表"""
        result = index_manager.get_read_paths(
            "stock_5min", "v1",
            date="2099-01-01"
        )

        assert result == []

    def test_filter_key_not_in_storage_rule(self, index_manager):
        """对于不在 storage_rule 中的字段，当前会忽略（因为是 path filter）"""
        # nonexistent 会被忽略（不在 storage_rule 中也不在 builtin 中）
        # 当前实现：pathFilters 只筛选 storage_rule 中的字段，
        # nonexistent 不会触发错误，而是被静默忽略
        result = index_manager.get_read_paths("stock_5min", "v1", nonexistent="value")
        # 返回所有匹配 * 模式的文件
        assert isinstance(result, list)


# ------------------------------------------------------------------ #
# 边界情况
# ------------------------------------------------------------------ #


class TestEdgeCases:
    def test_invalid_data_type(self, index_manager):
        """无效 data_type 报错"""
        with pytest.raises(KeyError):
            index_manager.get_write_paths(
                pd.DataFrame({"date": ["2026-05-17"]}),
                "nonexistent", "v1"
            )

    def test_write_missing_required_column(self, index_manager):
        """缺少 storage_rule 所需字段报错"""
        df = pd.DataFrame({
            "date": ["2026-05-17"],
            "code": ["00700"],
            # 缺少 market
        })

        with pytest.raises(ValueError, match="missing required columns"):
            index_manager.get_write_paths(df, "stock_5min", "v1")

    def test_write_empty_dataframe(self, index_manager):
        """写入空 DataFrame 返回空字典"""
        df = pd.DataFrame()
        result = index_manager.get_write_paths(df, "stock_5min", "v1")
        assert result == {}

    def test_write_single_group(self, index_manager):
        """单值 groupby"""
        df = pd.DataFrame({
            "date": ["2026-05-17"],
            "code": ["00700"],
            "market": ["XHKG"],
            "time": ["09:30"],
            "open": [380.0],
        })
        result = index_manager.get_write_paths(df, "stock_5min", "v1")
        assert len(result) == 1

    def test_extract_path_refs(self, index_manager):
        """提取路径引用"""
        refs = index_manager._extract_path_refs(
            "{schema.name}/{schema.market}/{schema.date}.parquet"
        )
        assert "market" in refs
        assert "date" in refs

    def test_render_path_with_year_month(self, index_manager):
        """测试 year/month 从 date 提取"""
        path = index_manager._render_path(
            "{schema.name}/{schema.year}/{schema.month}/{schema.date}.parquet",
            {},
            "stock_5min",
            "v1",
            {"date": "2026-05-17"}
        )
        assert "2026" in path
        assert "05" in path

    def test_render_path_with_data_row(self, index_manager):
        """测试 data_row 参数"""
        path = index_manager._render_path(
            "{schema.name}/{schema.code}.parquet",
            {},
            "stock_5min",
            "v1",
            {"code": "00700"}
        )
        assert "00700" in path

    def test_generate_date_range(self, index_manager):
        """生成日期范围"""
        dates = index_manager._generate_date_range("2026-05-15", "2026-05-18")
        assert len(dates) == 4
        assert "2026-05-15" in dates
        assert "2026-05-18" in dates

    def test_generate_date_range_single(self, index_manager):
        """生成单日日期范围"""
        dates = index_manager._generate_date_range("2026-05-15", "2026-05-15")
        assert len(dates) == 1

    def test_generate_candidate_patterns_no_filters(self, index_manager):
        """无 filter 时生成通配符模式"""
        patterns = index_manager._generate_candidate_patterns(
            "{schema.name}/{schema.date}.parquet",
            "stock_1day",
            "v1",
            {}
        )
        assert len(patterns) == 1
        assert "*" in patterns[0]

    def test_render_glob_pattern(self, index_manager):
        """测试 glob 模式渲染"""
        pattern = index_manager._render_glob_pattern(
            "{schema.name}/{schema.date}.parquet",
            "stock_1day",
            "v1",
            {"date": "2026-05-17"}
        )
        assert "stock_1day" in pattern
        assert "2026-05-17" in pattern

    def test_to_absolute_path(self, tmp_path, monkeypatch):
        """测试绝对路径转换"""
        data_dir = tmp_path / "data"
        data_dir.mkdir(exist_ok=True)

        # 创建 schema
        import json
        d = tmp_path / "schemas"
        d.mkdir(exist_ok=True)
        stock_1day = {
            "name": "stock_1day",
            "version": "v1",
            "data_schema": {"date": "string"},
            "storage_rule": "{schema.name}/{schema.date}.parquet",
        }
        (d / "stock_1day_v1.json").write_text(json.dumps(stock_1day))

        monkeypatch.setenv("DATACENTER_DATA_DIR", str(data_dir))

        from app.schema_manager import SchemaManager
        from app.index_manager import IndexManager

        sm = SchemaManager(str(d))
        im = IndexManager(sm)

        rel_path = "stock_1day/2026-05-17.parquet"
        abs_path = im.to_absolute_path(rel_path)

        assert abs_path.startswith(str(data_dir))
        assert rel_path in abs_path