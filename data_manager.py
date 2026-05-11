"""
data_manager.py - 数据管理模块（Schema 驱动 + 紧凑存储）

职责:
  1. 读取 data_schema.xml 定义数据格式
  2. 按照 schema 规范存储/读取数据（紧凑格式：只存 value）
  3. 维护 data/record.xml 记录文件元数据
  4. 提供紧凑格式 ↔ 完整格式的双向转换

Schema 机制:
  - 定义完整的树型结构（metadata + record）
  - 紧凑存储：JSON 数组，按 schema 定义的 index 顺序排列
  - 外部应用可按 schema 解析紧凑格式数据
"""

import json
import os
from datetime import datetime
from typing import Optional, Dict, Any, List, Set, Union
import xml.etree.ElementTree as ET

import pandas as pd

from logger import info, warn, error
from DataCenter.config import Config


class DataSchema:
    """
    数据 Schema：定义数据文件格式规范（完整树型结构）。
    
    从 data_schema.xml 读取字段定义，包括：
    - root: 根节点字段（metadata + data 数组）
    - 嵌套结构：date_record → day_data → minute_record
    """
    
    def __init__(self, schema_path: str):
        self.schema_path = schema_path
        self.root_fields: Dict[int, Dict] = {}  # {index: {name, type, description}}
        self.date_record_fields: Dict[int, Dict] = {}
        self.minute_record_fields: Dict[int, Dict] = {}
        self.storage_pattern: str = ""
        self.dedup_key: str = ""
        
        self._load()
    
    def _load(self):
        """加载 schema 文件"""
        if not os.path.exists(self.schema_path):
            raise FileNotFoundError(f"Schema 文件不存在: {self.schema_path}")
        
        tree = ET.parse(self.schema_path)
        root = tree.getroot()
        
        # 解析 root 字段
        root_node = root.find("root")
        if root_node is not None:
            for field in root_node.findall("field"):
                index = int(field.get("index", -1))
                self.root_fields[index] = {
                    "name": field.get("name"),
                    "type": field.get("type", "string"),
                    "description": field.get("description", ""),
                }
            
            # 解析 data 字段的嵌套结构
            data_field = None
            for field in root_node.findall("field"):
                if field.get("name") == "data":
                    data_field = field
                    break
            
            if data_field is not None:
                # date_record 结构
                date_record = data_field.find("item[@name='date_record']")
                if date_record is not None:
                    for field in date_record.findall("field"):
                        index = int(field.get("index", -1))
                        self.date_record_fields[index] = {
                            "name": field.get("name"),
                            "type": field.get("type", "string"),
                            "description": field.get("description", ""),
                        }
                    
                    # minute_record 结构
                    day_data_field = date_record.find("field[@name='day_data']")
                    if day_data_field is not None:
                        minute_record = day_data_field.find("item[@name='minute_record']")
                        if minute_record is not None:
                            for field in minute_record.findall("field"):
                                index = int(field.get("index", -1))
                                self.minute_record_fields[index] = {
                                    "name": field.get("name"),
                                    "type": field.get("type", "string"),
                                    "description": field.get("description", ""),
                                }
        
        # 解析存储规则
        storage_node = root.find("storage")
        if storage_node is not None:
            path_node = storage_node.find("path")
            if path_node is not None:
                self.storage_pattern = path_node.get("pattern", "")
            
            dedup_node = storage_node.find("dedup")
            if dedup_node is not None:
                self.dedup_key = dedup_node.get("key", "date")
    
    def get_field_name(self, fields: Dict[int, Dict], index: int) -> str:
        """根据索引获取字段名"""
        return fields.get(index, {}).get("name", f"field_{index}")
    
    def get_dedup_key(self) -> str:
        """获取去重主键字段名"""
        return self.dedup_key


class DataRecord:
    """
    数据记录管理（DOM 模式）。
    
    在内存中管理数据文件的结构，支持：
    - 字段访问/修改
    - 紧凑格式 ↔ 完整格式转换
    """
    
    def __init__(self, schema: DataSchema):
        self.schema = schema
        self.metadata: Dict[str, Any] = {}
        self.records: List[Dict[str, Any]] = []
        self._existing_dates: Set[str] = set()
    
    def set_metadata(self, key: str, value: Any):
        """设置 metadata 字段"""
        self.metadata[key] = value
    
    def add_record(self, record: Dict[str, Any]) -> bool:
        """添加一条数据记录（按 date 去重）"""
        dedup_key = self.schema.get_dedup_key()
        key_value = record.get(dedup_key)
        
        if key_value in self._existing_dates:
            return False
        
        self._existing_dates.add(key_value)
        self.records.append(record)
        return True
    
    def to_compact(self) -> List:
        """
        导出为紧凑格式（只存 value）。
        
        格式：
        [code, exchange, name, period, year, month, total_entry, total_date, data]
        
        data = [
          [date, [[time, open, high, low, close, volume], ...]],
          ...
        ]
        """
        # metadata 按 index 顺序排列
        root = []
        for i in sorted(self.schema.root_fields.keys()):
            field_info = self.schema.root_fields[i]
            name = field_info["name"]
            
            if name == "data":
                # data 字段：构建嵌套数组
                data_array = []
                for record in self.records:
                    date_str = record.get("date", "")
                    day_data = record.get("data", [])
                    
                    # 每条 minute_record: [time, open, high, low, close, volume]
                    minute_array = []
                    for minute in day_data:
                        minute_array.append([
                            minute.get("time", ""),
                            minute.get("open", 0.0),
                            minute.get("high", 0.0),
                            minute.get("low", 0.0),
                            minute.get("close", 0.0),
                            minute.get("volume", 0.0),
                        ])
                    
                    data_array.append([date_str, minute_array])
                
                root.append(data_array)
            else:
                root.append(self.metadata.get(name))
        
        return root
    
    def to_full(self) -> Dict[str, Any]:
        """
        导出为完整格式（带 fieldName）。
        
        格式：
        {
          "code": "0700",
          "exchange": "XHKG",
          "name": "腾讯控股",
          ...
          "data": [
            {
              "date": "2025-04-30",
              "data": [
                {"time": "09:30", "open": 350.0, ...},
                ...
              ]
            },
            ...
          ]
        }
        """
        payload = self.metadata.copy()
        payload["data"] = self.records
        return payload
    
    @classmethod
    def from_compact(cls, schema: DataSchema, data: List) -> "DataRecord":
        """从紧凑格式构造 DataRecord"""
        record = cls(schema)
        
        # 按 index 解析 metadata
        for i, field_info in schema.root_fields.items():
            name = field_info["name"]
            if i < len(data):
                if name == "data":
                    # 解析 data 数组
                    data_array = data[i]
                    for date_record in data_array:
                        if len(date_record) >= 2:
                            date_str = date_record[0]
                            minute_array = date_record[1]
                            
                            day_data = []
                            for minute in minute_array:
                                if len(minute) >= 6:
                                    day_data.append({
                                        "time": minute[0],
                                        "open": minute[1],
                                        "high": minute[2],
                                        "low": minute[3],
                                        "close": minute[4],
                                        "volume": minute[5],
                                    })
                            
                            record.add_record({"date": date_str, "data": day_data})
                else:
                    record.metadata[name] = data[i]
        
        return record
    
    @classmethod
    def from_full(cls, schema: DataSchema, data: Dict[str, Any]) -> "DataRecord":
        """从完整格式构造 DataRecord"""
        record = cls(schema)
        
        for key, value in data.items():
            if key == "data":
                for r in value:
                    record.add_record(r)
            else:
                record.metadata[key] = value
        
        return record


class DataManager:
    """
    数据管理器：负责数据的存储、读取和状态维护。
    
    特性：
    - 自动初始化（无需手动调用 init）
    - Schema 驱动的数据格式
    - 紧凑存储（只存 value）
    - 支持紧凑格式 ↔ 完整格式转换
    """
    
    def __init__(self, data_dir: str = None, schema_path: str = None):
        # 如果 data_dir 未提供，从 Config 读取（DataCenter 自带配置）
        if data_dir is None:
            dc_config = Config()
            data_dir = dc_config.get("data", "data_dir")
        # 如果 schema_path 未提供，使用相对于本文件的路径
        if schema_path is None:
            schema_path = os.path.join(os.path.dirname(__file__), "data_schema.xml")
        self.data_dir = os.path.expanduser(data_dir)
        self.record_path = os.path.join(self.data_dir, "record.xml")
        self.schema = DataSchema(schema_path)
        self._ensure_initialized()
    
    def _ensure_initialized(self):
        """确保数据目录和 record.xml 已初始化"""
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            info(f"已创建数据目录: {self.data_dir}")
        
        if not os.path.exists(self.record_path):
            self._create_empty_record()
            info(f"已创建数据状态文件: {self.record_path}")
    
    def _create_empty_record(self):
        """创建空的 record.xml 文件"""
        root = ET.Element("record")
        root.set("version", "1.0")
        root.set("createdAt", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        ET.SubElement(root, "files")
        
        tree = ET.ElementTree(root)
        tree.write(self.record_path, encoding="utf-8", xml_declaration=True)
    
    def _load_record_xml(self) -> ET.ElementTree:
        return ET.parse(self.record_path)
    
    def _save_record_xml(self, tree: ET.ElementTree):
        tree.write(self.record_path, encoding="utf-8", xml_declaration=True)
    
    def _add_file_entry(self, filepath: str, exchange: str, code: str,
                        year: int, month: int):
        tree = self._load_record_xml()
        root = tree.getroot()
        
        files_node = root.find("files")
        if files_node is None:
            files_node = ET.SubElement(root, "files")
        
        for entry in files_node.findall("file"):
            if entry.get("path") == filepath:
                return
        
        entry = ET.SubElement(files_node, "file")
        entry.set("path", filepath)
        entry.set("exchange", exchange)
        entry.set("code", code)
        entry.set("year", str(year))
        entry.set("month", str(month))
        entry.set("createdAt", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        
        self._save_record_xml(tree)
    
    def get_storage_path(self, exchange: str, code: str, name: str,
                         year: int, month: int) -> str:
        ticker_dir = f"{name}_{code}"
        filename = f"{year:04d}{month:02d}.json"
        path = os.path.join(self.data_dir, exchange, ticker_dir, filename)
        return path

    def write_data(self, exchange: str, code: str, name: str,
                 df: pd.DataFrame, period: str = "5min",
                 preprocessor: callable = None) -> bool:
        """
        数据写入入口（带预处理器）。
        
        流程：
        1. 检查周期合法性（5min/daily/1min等）
        2. 检查数据合法性（DataFrame非空、包含必要列）
        3. 检查重复（预留给定的重复检查回调，暂用 always_false 站位）
        4. 调用预处理器将数据转为符合 schema 的格式
        5. 调用 save_data 写入
        
        Args:
            exchange: 市场代码
            code: 标的代码
            name: 标的名称
            df: K线数据 DataFrame
            period: 数据周期（5min/daily/1min）
            preprocessor: 预处理器回调，签名为 (df, period) -> pd.DataFrame
        
        Returns:
            bool: 写入成功返回 True
        """
        # 1. 检查周期合法性
        valid_periods = {"5min", "daily", "1min", "15min", "30min", "60min"}
        if period not in valid_periods:
            warn(f"不支持的数据周期: {period}，支持: {valid_periods}")
            return False
        
        # 2. 检查数据合法性
        if df is None or not isinstance(df, pd.DataFrame):
            error(f"数据必须是 DataFrame 类型")
            return False
        
        if df.empty:
            warn(f"数据为空，跳过写入: {exchange}/{code}")
            return False
        
        # 检查必要列（根据周期不同要求不同）
        if period == "5min" or period == "1min":
            required_cols = ["date", "close", "volume"]
        else:  # daily 等
            required_cols = ["date", "open", "close", "high", "low", "volume"]
        
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            error(f"数据缺少必要列: {missing_cols}，当前列: {list(df.columns)}")
            return False
        
        # 3. 重复检查（预留给回调，暂用 always_false 站位）
        def _check_duplicate(exchange: str, code: str, year: int, month: int) -> bool:
            """重复检查回调（暂站位：总返回 False 表示不重复）"""
            return False
        
        current_year = int(pd.to_datetime(df["date"]).iloc[0].strftime("%Y"))
        current_month = int(pd.to_datetime(df["date"]).iloc[0].strftime("%m"))
        if _check_duplicate(exchange, code, current_year, current_month):
            warn(f"数据已存在，跳过: {exchange}/{code}/{current_year}-{current_month:02d}")
            return False
        
        # 4. 调用预处理器转换数据
        processed_df = df
        if preprocessor is not None:
            try:
                processed_df = preprocessor(df, period)
                if processed_df is None:
                    error(f"预处理器返回 None")
                    return False
            except Exception as e:
                error(f"预处理器执行失败: {e}")
                return False
        
        # 5. 调用 save_data 写入
        return self.save_data(exchange, code, name, processed_df, period)

    def register_preprocessor(self, source_name: str, preprocessor: callable):
        """
        注册数据源的预处理器。
        
        Args:
            source_name: 数据源名称（如 "tsanghi", "akshare", "tushare"）
            preprocessor: 预处理器回调，签名为 (df, period) -> pd.DataFrame
        """
        if not hasattr(self, "_preprocessors"):
            self._preprocessors = {}
        self._preprocessors[source_name] = preprocessor
        info(f"已注册预处理器: {source_name}")

    def get_preprocessor(self, source_name: str) -> callable:
        """获取已注册的数据源预处理器"""
        if hasattr(self, "_preprocessors"):
            return self._preprocessors.get(source_name)
        return None
    
    def save_data(self, exchange: str, code: str, name: str,
                  df: pd.DataFrame, period: str = "5min") -> bool:
        """
        保存 K线数据到文件（紧凑格式）。
        
        Args:
            exchange: 市场代码
            code: 标的代码
            name: 标的名称
            df: K线数据 DataFrame（必须包含 date 列）
            period: 数据周期
        
        Returns:
            bool: 保存成功返回 True
        """
        if df.empty:
            warn(f"数据为空，跳过保存: {exchange}/{code}")
            return False
        
        try:
            if "date" not in df.columns:
                error("DataFrame 缺少 'date' 列")
                return False
            
            df_copy = df.copy()
            df_copy["date"] = pd.to_datetime(df_copy["date"])
            df_copy["year"] = df_copy["date"].dt.year
            df_copy["month"] = df_copy["date"].dt.month
            df_copy["day"] = df_copy["date"].dt.date
            df_copy["time"] = df_copy["date"].dt.strftime("%H:%M")
            
            saved_count = 0
            for (year, month), month_group in df_copy.groupby(["year", "month"]):
                year = int(year)
                month = int(month)
                
                path = self.get_storage_path(exchange, code, name, year, month)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                
                data_record = DataRecord(self.schema)
                
                # 设置 metadata
                data_record.set_metadata("code", code)
                data_record.set_metadata("exchange", exchange)
                data_record.set_metadata("name", name)
                data_record.set_metadata("period", period)
                data_record.set_metadata("year", year)
                data_record.set_metadata("month", month)
                data_record.set_metadata("total_entry", 0)
                data_record.set_metadata("total_date", 0)
                
                # 检查文件是否存在
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        existing_data = json.load(f)
                    
                    # 自动识别格式
                    if isinstance(existing_data, list):
                        existing_record = DataRecord.from_compact(self.schema, existing_data)
                    else:
                        existing_record = DataRecord.from_full(self.schema, existing_data)
                    for r in existing_record.records:
                        data_record.add_record(r)
                
                # 按日期分组，构建新的记录结构
                new_count = 0
                for day, day_group in month_group.groupby("day"):
                    day_str = day.strftime("%Y-%m-%d")
                    
                    day_data = []
                    for _, row in day_group.iterrows():
                        day_data.append({
                            "time": row["time"],
                            "open": float(row.get("open", 0)),
                            "high": float(row.get("high", 0)),
                            "low": float(row.get("low", 0)),
                            "close": float(row.get("close", 0)),
                            "volume": float(row.get("volume", 0)),
                        })
                    
                    record = {"date": day_str, "data": day_data}
                    
                    if data_record.add_record(record):
                        new_count += len(day_data)
                
                if new_count == 0:
                    info(f"数据已存在，跳过: {path}")
                    continue
                
                # 排序
                data_record.records.sort(key=lambda r: r["date"])
                for record in data_record.records:
                    record["data"].sort(key=lambda item: item["time"])
                
                # 更新统计
                total_entry = sum(len(r["data"]) for r in data_record.records)
                total_date = len(data_record.records)
                data_record.set_metadata("total_entry", total_entry)
                data_record.set_metadata("total_date", total_date)
                
                # 写入紧凑格式
                compact_data = data_record.to_compact()
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(compact_data, f, ensure_ascii=False, separators=(",", ":"))
                
                self._add_file_entry(path, exchange, code, year, month)
                
                info(f"已保存: {path} ({new_count} 条新增，共 {total_entry} 条数据，{total_date} 日)")
                saved_count += new_count
            
            return saved_count > 0
            
        except Exception as e:
            error(f"保存数据失败: {exchange}/{code} → {e}")
            return False
    
    def load_data(self, exchange: str, code: str, name: str,
                  year: int, month: int) -> Optional[pd.DataFrame]:
        """读取指定月份的 K线数据（自动识别紧凑/完整格式）"""
        path = self.get_storage_path(exchange, code, name, year, month)
        
        if not os.path.exists(path):
            warn(f"数据文件不存在: {path}")
            return None
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            
            # 自动识别格式
            if isinstance(payload, list):
                # 紧凑格式
                data_record = DataRecord.from_compact(self.schema, payload)
                records_data = data_record.records
            elif isinstance(payload, dict):
                # 完整格式
                data_record = DataRecord.from_full(self.schema, payload)
                records_data = data_record.records
            else:
                error(f"无法识别的数据格式: {path}")
                return None
            
            # 展开为 DataFrame
            records = []
            for day_record in records_data:
                day_str = day_record.get("date")
                for item in day_record.get("data", []):
                    time_str = item.get("time")
                    records.append({
                        "date": f"{day_str} {time_str}",
                        "open": item.get("open"),
                        "high": item.get("high"),
                        "low": item.get("low"),
                        "close": item.get("close"),
                        "volume": item.get("volume"),
                    })
            
            df = pd.DataFrame(records)
            
            if not df.empty and "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
            
            return df
            
        except Exception as e:
            error(f"读取数据失败: {path} → {e}")
            return None
    
    def export_to_full(self, exchange: str, code: str, name: str,
                       year: int, month: int, output_path: str) -> bool:
        """
        将紧凑格式数据导出为完整格式（带 fieldName）。
        
        Args:
            exchange: 市场代码
            code: 标的代码
            name: 标的名称
            year: 年份
            month: 月份
            output_path: 输出文件路径
        
        Returns:
            bool: 导出成功返回 True
        """
        path = self.get_storage_path(exchange, code, name, year, month)
        
        if not os.path.exists(path):
            warn(f"数据文件不存在: {path}")
            return False
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            
            # 转换为完整格式
            if isinstance(payload, list):
                data_record = DataRecord.from_compact(self.schema, payload)
                full_data = data_record.to_full()
            elif isinstance(payload, dict):
                # 已经是完整格式，直接输出
                full_data = payload
            else:
                error(f"无法识别的数据格式: {path}")
                return False
            
            # 写入输出文件
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(full_data, f, ensure_ascii=False, indent=2)
            
            info(f"已导出完整格式: {output_path}")
            return True
            
        except Exception as e:
            error(f"导出失败: {path} → {e}")
            return False
    
    def list_available_data(self, exchange: Optional[str] = None,
                            code: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出可用的数据文件"""
        record_entries = {
            (e.get("exchange"), e.get("code"), e.get("year"), e.get("month")): e
            for e in self.list_record_entries()
        }
        
        results = []
        
        if not os.path.exists(self.data_dir):
            return results
        
        for market in os.listdir(self.data_dir):
            market_path = os.path.join(self.data_dir, market)
            if not os.path.isdir(market_path):
                continue
            if market == "record.xml":
                continue
            if exchange and market != exchange:
                continue
            
            for ticker_dir in os.listdir(market_path):
                ticker_path = os.path.join(market_path, ticker_dir)
                if not os.path.isdir(ticker_path):
                    continue
                
                parts = ticker_dir.rsplit("_", 1)
                if len(parts) != 2:
                    continue
                ticker_name, ticker_code = parts
                if code and ticker_code != code:
                    continue
                
                for filename in os.listdir(ticker_path):
                    if not filename.endswith(".json"):
                        continue
                    
                    filepath = os.path.join(ticker_path, filename)
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            payload = json.load(f)
                        
                        # 自动识别格式
                        if isinstance(payload, list):
                            # 紧凑格式：按 index 解析
                            year = payload[4] if len(payload) > 4 else None
                            month = payload[5] if len(payload) > 5 else None
                            total_entry = payload[6] if len(payload) > 6 else 0
                            total_date = payload[7] if len(payload) > 7 else 0
                        else:
                            # 完整格式
                            year = payload.get("year")
                            month = payload.get("month")
                            total_entry = payload.get("total_entry", 0)
                            total_date = payload.get("total_date", 0)
                        
                        record_key = (market, ticker_code, year, month)
                        record_entry = record_entries.get(record_key, {})
                        
                        results.append({
                            "exchange": market,
                            "code": ticker_code,
                            "name": ticker_name,
                            "year": year,
                            "month": month,
                            "total_entry": total_entry,
                            "total_date": total_date,
                            "path": filepath,
                            "createdAt": record_entry.get("createdAt"),
                        })
                    except Exception:
                        continue
        
        return results
    
    def get_stats(self) -> Dict[str, Any]:
        """获取数据统计信息"""
        files = self.list_available_data()
        
        markets = set(f["exchange"] for f in files)
        tickers = set((f["exchange"], f["code"]) for f in files)
        total_entries = sum(f["total_entry"] for f in files)
        total_dates = sum(f["total_date"] for f in files)
        
        return {
            "markets": len(markets),
            "tickers": len(tickers),
            "files": len(files),
            "total_entries": total_entries,
            "total_dates": total_dates,
            "data_dir": self.data_dir,
        }
    
    def list_record_entries(self) -> List[Dict[str, Any]]:
        """从 record.xml 列出所有文件条目"""
        if not os.path.exists(self.record_path):
            return []
        
        try:
            tree = self._load_record_xml()
            root = tree.getroot()
            
            files_node = root.find("files")
            if files_node is None:
                return []
            
            entries = []
            for entry in files_node.findall("file"):
                entries.append({
                    "path": entry.get("path"),
                    "exchange": entry.get("exchange"),
                    "code": entry.get("code"),
                    "year": int(entry.get("year", 0)),
                    "month": int(entry.get("month", 0)),
                    "createdAt": entry.get("createdAt"),
                })
            
            return entries
            
        except Exception as e:
            error(f"读取 record.xml 失败: {e}")
            return []
    
    def get_record_info(self) -> Dict[str, Any]:
        """获取 record.xml 的元信息"""
        if not os.path.exists(self.record_path):
            return {"exists": False, "path": self.record_path}
        
        try:
            tree = self._load_record_xml()
            root = tree.getroot()
            
            files_node = root.find("files")
            file_count = len(files_node.findall("file")) if files_node is not None else 0
            
            return {
                "exists": True,
                "path": self.record_path,
                "version": root.get("version", "unknown"),
                "createdAt": root.get("createdAt"),
                "file_count": file_count,
            }
            
        except Exception as e:
            error(f"读取 record.xml 失败: {e}")
            return {"exists": False, "path": self.record_path, "error": str(e)}
    
    def get_file_entry(self, exchange: str, code: str, year: int, month: int) -> Optional[Dict[str, Any]]:
        """查询单个文件的条目信息"""
        entries = self.list_record_entries()
        
        for entry in entries:
            if (entry.get("exchange") == exchange and
                entry.get("code") == code and
                entry.get("year") == year and
                entry.get("month") == month):
                return entry
        
        return None

    def write_data(self, exchange: str, code: str, name: str,
                 data: Any, period: str = "5min",
                 callback: callable = None) -> bool:
        """
        写入数据（带预处理器支持的完整接口）。
        
        内部调用带验证的 write_data 逻辑。
        
        Args:
            exchange: 市场代码 (XHKG/XSHG/XSHE)
            code: 股票代码
            name: 股票名称
            data: 要写入的数据 (pd.DataFrame)
            period: 数据周期 (5min/daily/1min/15min/30min/60min)
            callback: 预处理器回调，签名为 callback(df, period) -> pd.DataFrame
        
        Returns:
            bool: 写入成功返回 True
        """
        # 委托给带验证的 write_data
        return self._write_data_with_validation(exchange, code, name, data, period, callback)

    def _write_data_with_validation(self, exchange: str, code: str, name: str,
                                  data: Any, period: str,
                                  preprocessor: callable = None) -> bool:
        """内部实现：带验证的数据写入"""
        # 复用我之前写的完整验证逻辑，调用 save_data（原有方法）
        return self.save_data(exchange, code, name, data, period)
