"""
CTtest - Filter 测试脚本
测试 read_data 的各种 filter 组合

Filter 类型：
- 单值：date="2026-05-15"
- 枚举：date=["2026-05-15", "2026-05-16"]
- 范围：date={"start": "2026-05-15", "end": "2026-05-17"}
- 组合：多个 filter 同时使用
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
import pandas as pd

from app.config import Config
from app.schema_manager import SchemaManager
from app.storage_manager import StorageManager
from app.index_manager import IndexManager
from app.data_processor import DataProcessor


def main():
    # 配置
    base_dir = Path(__file__).parent
    data_dir = base_dir / "data"
    schemas_dir = Path(__file__).parent.parent / "schemas"
    
    os.environ["DATACENTER_DATA_DIR"] = str(data_dir)
    
    # 初始化
    config = Config()
    schema_manager = SchemaManager(str(schemas_dir))
    storage_manager = StorageManager(compression=config.COMPRESSION)
    index_manager = IndexManager(schema_manager)
    data_processor = DataProcessor(schema_manager, index_manager, storage_manager)
    
    print("=" * 60)
    print("Filter 测试")
    print("=" * 60)
    
    # 1. date 单值
    print("\n1. date 单值 '2026-05-15':")
    df = data_processor.read_data(
        data_type="stock_5min",
        version="v1",
        date="2026-05-15",
    )
    print(f"   行数: {len(df)}")
    print(f"   日期: {sorted(df['date'].unique())}")
    print(f"   市场: {df['market'].unique().tolist()}")
    
    # 2. date 枚举
    print("\n2. date 枚举 ['2026-05-15', '2026-05-16']:")
    df = data_processor.read_data(
        data_type="stock_5min",
        version="v1",
        date=["2026-05-15", "2026-05-16"],
    )
    print(f"   行数: {len(df)}")
    print(f"   日期: {sorted(df['date'].unique())}")
    
    # 3. date 范围
    print("\n3. date 范围 {'start': '2026-05-15', 'end': '2026-05-17'}:")
    df = data_processor.read_data(
        data_type="stock_5min",
        version="v1",
        date={"start": "2026-05-15", "end": "2026-05-17"},
    )
    print(f"   行数: {len(df)}")
    print(f"   日期: {sorted(df['date'].unique())}")
    
    # 4. market 单值（row filter）
    print("\n4. market 单值 'XHKG'（row filter）:")
    df = data_processor.read_data(
        data_type="stock_5min",
        version="v1",
        date="2026-05-15",
        market="XHKG",
    )
    print(f"   行数: {len(df)}")
    print(f"   市场: {df['market'].unique().tolist()}")
    print(f"   股票: {df['stock_code'].unique().tolist()}")
    
    # 5. market 枚举
    print("\n5. market 枚举 ['XHKG', 'XSHG']:")
    df = data_processor.read_data(
        data_type="stock_5min",
        version="v1",
        date="2026-05-15",
        market=["XHKG", "XSHG"],
    )
    print(f"   行数: {len(df)}")
    print(f"   市场: {df['market'].unique().tolist()}")
    
    # 6. stock_code 单值（row filter）
    print("\n6. stock_code 单值 '00700'（row filter）:")
    df = data_processor.read_data(
        data_type="stock_5min",
        version="v1",
        date="2026-05-15",
        stock_code="00700",
    )
    print(f"   行数: {len(df)}")
    print(f"   股票: {df['stock_code'].unique().tolist()}")
    print(f"   股票名: {df['stock_name'].unique().tolist()}")
    
    # 7. stock_code 枚举
    print("\n7. stock_code 枚举 ['00700', '00941']:")
    df = data_processor.read_data(
        data_type="stock_5min",
        version="v1",
        date="2026-05-15",
        stock_code=["00700", "00941"],
    )
    print(f"   行数: {len(df)}")
    print(f"   股票: {df['stock_code'].unique().tolist()}")
    
    # 8. 组合 filter：date范围 + market枚举
    print("\n8. 组合 filter：date范围 + market枚举:")
    df = data_processor.read_data(
        data_type="stock_5min",
        version="v1",
        date={"start": "2026-05-15", "end": "2026-05-17"},
        market=["XHKG", "XSHG"],
    )
    print(f"   行数: {len(df)}")
    print(f"   日期: {sorted(df['date'].unique())}")
    print(f"   市场: {df['market'].unique().tolist()}")
    
    # 9. 组合 filter：date + market + stock_code
    print("\n9. 组合 filter：date + market + stock_code:")
    df = data_processor.read_data(
        data_type="stock_5min",
        version="v1",
        date="2026-05-15",
        market="XHKG",
        stock_code="00700",
    )
    print(f"   行数: {len(df)}")
    print(f"   股票: {df['stock_code'].unique().tolist()}")
    print(f"   股票名: {df['stock_name'].unique().tolist()}")
    
    # 10. 无 date filter（全月数据）
    print("\n10. 无 date filter（stock_30min 全月）:")
    df = data_processor.read_data(
        data_type="stock_30min",
        version="v1",
    )
    print(f"   行数: {len(df)}")
    print(f"   日期: {sorted(df['date'].unique())}")
    print(f"   市场: {df['market'].unique().tolist()}")
    
    # 11. 无任何 filter（全量数据）
    print("\n11. 无任何 filter（stock_1day 全量）:")
    df = data_processor.read_data(
        data_type="stock_1day",
        version="v1",
    )
    print(f"   行数: {len(df)}")
    print(f"   日期: {sorted(df['date'].unique())}")
    print(f"   市场: {df['market'].unique().tolist()}")
    
    print("\n" + "=" * 60)
    print("Filter 测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
