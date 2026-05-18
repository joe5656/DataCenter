"""
CTtest - 集成测试脚本
使用真实的 schemas/ 和 config.xml 测试 DataProcessor 写入功能

测试数据覆盖：
- 多级别：stock_5min, stock_30min, stock_60min, stock_1day
- 多天：2026-05-15, 2026-05-16, 2026-05-17
- 多市场：XHKG, XSHG, XSHE
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from app.config import Config
from app.schema_manager import SchemaManager
from app.storage_manager import StorageManager
from app.index_manager import IndexManager
from app.data_processor import DataProcessor


def generate_test_data(data_type: str, date: str, market: str) -> pd.DataFrame:
    """生成指定级别、日期、市场的测试数据"""
    
    # 根据 data_type 决定时间粒度
    if data_type == "stock_5min":
        times = [f"{h:02d}:{m:02d}" for h in range(9, 16) for m in range(0, 60, 5)
                 if not (h == 12 and m >= 0)]  # 午休 12:00-13:00
    elif data_type == "stock_30min":
        times = ["09:30", "10:00", "10:30", "11:00", "11:30", 
                 "13:00", "13:30", "14:00", "14:30", "15:00", "15:30"]
    elif data_type == "stock_60min":
        times = ["09:30", "10:30", "11:30", "13:00", "14:00", "15:00"]
    elif data_type == "stock_1day":
        times = ["00:00"]  # 日线只有一条
    
    # 解析 Year/Month
    dt = datetime.strptime(date, "%Y-%m-%d")
    year = str(dt.year)
    month = f"{dt.month:02d}"
    
    # 生成股票代码
    if market == "XHKG":
        codes = ["00700", "00941", "09988"]  # 腾讯、中国移动、阿里
        names = ["腾讯控股", "中国移动", "阿里巴巴"]
    elif market == "XSHG":
        codes = ["600519", "600036", "601318"]  # 贵州茅台、招商银行、中国平安
        names = ["贵州茅台", "招商银行", "中国平安"]
    elif market == "XSHE":
        codes = ["000001", "000002", "000858"]  # 平安银行、万科、五粮液
        names = ["平安银行", "万科A", "五粮液"]
    
    rows = []
    base_price = 100.0 if market == "XSHG" else 50.0 if market == "XHKG" else 30.0
    
    for i, (code, name) in enumerate(zip(codes, names)):
        for j, time in enumerate(times):
            # 随机波动生成价格
            np.random.seed(hash(date + code + time) % 2**32)
            open_p = base_price * (1 + i * 0.5) * (1 + np.random.uniform(-0.02, 0.02))
            close_p = open_p * (1 + np.random.uniform(-0.01, 0.01))
            high_p = max(open_p, close_p) * (1 + np.random.uniform(0, 0.005))
            low_p = min(open_p, close_p) * (1 - np.random.uniform(0, 0.005))
            volume = int(np.random.uniform(100000, 1000000))
            
            rows.append({
                "Year": year,
                "Month": month,
                "date": date,
                "time": time,
                "market": market,
                "stock_code": code,
                "stock_name": name,
                "open": round(open_p, 2),
                "close": round(close_p, 2),
                "high": round(high_p, 2),
                "low": round(low_p, 2),
                "volume": volume,
            })
    
    return pd.DataFrame(rows)


def main():
    # 配置
    base_dir = Path(__file__).parent
    data_dir = base_dir / "data"
    schemas_dir = Path(__file__).parent.parent / "schemas"
    config_file = Path(__file__).parent.parent / "config.xml"
    
    # 设置环境变量覆盖 DATA_DIR
    os.environ["DATACENTER_DATA_DIR"] = str(data_dir)
    
    print(f"数据目录: {data_dir}")
    print(f"Schema目录: {schemas_dir}")
    print(f"配置文件: {config_file}")
    
    # 初始化模块
    config = Config()
    print(f"DATA_DIR: {config.DATA_DIR}")
    
    schema_manager = SchemaManager(str(schemas_dir))
    print(f"已加载 schema: {list(schema_manager._schemas.keys())}")
    
    storage_manager = StorageManager(compression=config.COMPRESSION)
    index_manager = IndexManager(schema_manager)
    data_processor = DataProcessor(schema_manager, index_manager, storage_manager)
    
    # 测试参数
    data_types = ["stock_5min", "stock_30min", "stock_60min", "stock_1day"]
    dates = ["2026-05-15", "2026-05-16", "2026-05-17"]
    markets = ["XHKG", "XSHG", "XSHE"]
    
    # 生成并写入测试数据
    total_rows = 0
    written_files = []
    
    for data_type in data_types:
        for date in dates:
            for market in markets:
                print(f"\n生成数据: {data_type} / {date} / {market}")
                
                df = generate_test_data(data_type, date, market)
                print(f"  行数: {len(df)}")
                total_rows += len(df)
                
                # 写入
                result = data_processor.write_data(
                    data=df,
                    data_type=data_type,
                    version="v1",
                )
                
                print(f"  写入结果: {result}")
                
                # 记录生成的文件
                for path in result.get("written_files", []):
                    written_files.append(path)
    
    # 验证写入的文件
    print(f"\n=== 写入验证 ===")
    print(f"总写入行数: {total_rows}")
    print(f"生成文件数: {len(written_files)}")
    
    for path in sorted(written_files):
        abs_path = data_dir / path
        exists = abs_path.exists()
        size = abs_path.stat().st_size if exists else 0
        print(f"  {path}: {'✅' if exists else '❌'} ({size} bytes)")
    
    # 读取验证
    print(f"\n=== 读取验证 ===")
    for data_type in data_types:
        for date in dates:
            print(f"\n读取 {data_type} / {date}:")
            
            try:
                df_read = data_processor.read_data(
                    data_type=data_type,
                    version="v1",
                    date=date,
                )
                print(f"  行数: {len(df_read)}")
                if len(df_read) > 0:
                    print(f"  市场: {df_read['market'].unique().tolist()}")
                    print(f"  股票数: {len(df_read['stock_code'].unique())}")
            except Exception as e:
                print(f"  ❌ 错误: {e}")
    
    print(f"\n=== 测试完成 ===")


if __name__ == "__main__":
    main()