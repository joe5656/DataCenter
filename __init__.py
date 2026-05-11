"""
DataCenter - 股票数据存储微服务

提供：
  - DataManager: Schema 驱动的紧凑格式 K 线数据存储
  - DataSchema: XML schema 解析器
  - DataRecord: 数据记录结构
"""

from .data_manager import DataManager, DataSchema, DataRecord

__all__ = ["DataManager", "DataSchema", "DataRecord"]
__version__ = "0.1.0"