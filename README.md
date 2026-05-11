# DataCenter - 数据管理模块

数据存储层，负责 K 线数据的持久化、读取和格式转换。

## 目录结构

```
DataCenter/
├── data_manager.py    # 核心模块：DataManager / DataSchema / DataRecord
├── data_schema.xml    # 数据格式定义（紧凑存储规范）
└── README.md          # 本文件
```

> **说明**：`data/` 目录（存放实际 JSON 数据文件）位于项目根目录，由 DataManager 实例化时通过 `data_dir` 参数指定。结构为 `data/{exchange}/{name}_{code}/{yearMM}.json`。

## 核心类

### DataSchema

从 `data_schema.xml` 读取字段定义，管理数据文件的格式规范。

```python
schema = DataSchema("DataCenter/data_schema.xml")
```

**属性：**

| 属性 | 类型 | 说明 |
|------|------|------|
| `root_fields` | `Dict[int, Dict]` | 根节点字段，key 为索引（0-8），value 含 name/type/description |
| `date_record_fields` | `Dict[int, Dict]` | 日期记录字段（date + day_data） |
| `minute_record_fields` | `Dict[int, Dict]` | 分钟级 K 线字段（time/open/high/low/close/volume） |

**方法：**

| 方法 | 说明 |
|------|------|
| `get_dedup_key()` | 返回去重 key（当前为 "date"） |
| `get_storage_pattern()` | 返回存储路径模板 |

### DataRecord

DOM 模式管理内存中的数据，支持紧凑格式 ↔ 完整格式双向转换。

```python
record = DataRecord(schema)
record.set_metadata("code", "0700")
record.set_metadata("exchange", "XHKG")
record.add_record({"date": "2025-04-30", "data": [...]})
```

**方法：**

| 方法 | 说明 |
|------|------|
| `set_metadata(key, value)` | 设置元数据字段 |
| `add_record(record)` | 添加一条数据记录（按 date 去重） |
| `to_compact()` | 导出为紧凑格式（只存 value 的嵌套数组） |
| `to_full()` | 导出为完整格式（带 fieldName 的 dict） |
| `from_compact(cls, schema, data)` | 从紧凑格式构造 DataRecord（类方法） |

### DataManager

数据管理器，负责数据的写入、读取和 record.xml 维护。

```python
dm = DataManager(str(cfg.data_dir), "DataCenter/data_schema.xml")
dm.write_data("XHKG", "0700", "腾讯控股", df, period="5min")
df_loaded = dm.load_data("XHKG", "0700", "腾讯控股", 2025, 4)
```

**主要方法：**

| 方法 | 说明 |
|------|------|
| `write_data(exchange, code, name, df, period, preprocessor)` | 数据写入入口（带预处理器回调） |
| `save_data(exchange, code, name, df, period)` | 实际写入逻辑（按月分组、自动合并已有数据） |
| `load_data(exchange, code, name, year, month)` | 加载指定月份的 JSON，自动识别紧凑/完整格式 |
| `export_to_full(exchange, code, name, year, month)` | 导出完整格式（含字段名） |
| `list_available_data()` | 扫描 data 目录，返回所有可用数据文件信息 |
| `get_stats()` | 返回统计摘要（文件数、总行数等） |

## 数据流程

### 写入管线

```
Collector.get_5min_range()
    → DataManager.write_data()
        → _write_data_with_validation() [检查周期/数据合法性]
            → save_data() [核心写入]
                1. 按 (year, month) 分组
                2. 加载已有 JSON（若存在）
                3. 按 date 去重合并
                4. 写入 {data_dir}/{exchange}/{name}_{code}/{yearMM}.json
                5. 更新 record.xml
```

### 读取管线

```
DataManager.load_data(exchange, code, name, year, month)
    → 自动检测 JSON 格式（紧凑 / 完整）
    → 解析为 DataFrame 返回
```

## 存储格式

### 紧凑格式（默认）

JSON 数组，只存 value，按 `data_schema.xml` 定义的 index 顺序排列：

```json
[
  "0700",        // [0] code
  "XHKG",        // [1] exchange
  "腾讯控股",     // [2] name
  "5min",        // [3] period
  2025,          // [4] year
  4,             // [5] month
  12345,         // [6] total_entry（总条数）
  20,            // [7] total_date（总天数）
  [             // [8] data
    ["2025-04-30", [[093000, 350.0, 352.5, 349.8, 351.2, 12345678], ...]],
    ["2025-04-29", [[093000, 348.0, ...], ...]]
  ]
]
```

### 完整格式

带字段名的嵌套 dict，由 `to_full()` / `export_to_full()` 导出：

```json
{
  "code": "0700",
  "exchange": "XHKG",
  "name": "腾讯控股",
  "period": "5min",
  "year": 2025,
  "month": 4,
  "total_entry": 12345,
  "total_date": 20,
  "data": [
    {
      "date": "2025-04-30",
      "data": [
        {"time": "09:30", "open": 350.0, "high": 352.5, "low": 349.8, "close": 351.2, "volume": 12345678},
        ...
      ]
    },
    ...
  ]
}
```

## record.xml

`data/record.xml` 记录所有已写入的数据文件元数据：

```xml
<?xml version="1.0" encoding="utf-8"?>
<record version="1.0" createdAt="2025-05-03 18:23:00">
  <files>
    <file path="XHKG/腾讯控股_0700/202504.json"
          exchange="XHKG" code="0700" year="2025" month="4"
          createdAt="2025-05-03 18:23:00"/>
  </files>
</record>
```

## 外部调用示例

```python
from DataCenter.data_manager import DataManager
from config import Config

cfg = Config("config.xml")
dm = DataManager(str(cfg.data_dir), "DataCenter/data_schema.xml")

# 写入
dm.write_data("XHKG", "0700", "腾讯控股", df, period="5min")

# 读取
df = dm.load_data("XHKG", "0700", "腾讯控股", 2025, 4)

# 导出完整格式
full_data = dm.export_to_full("XHKG", "0700", "腾讯控股", 2025, 4)

# 查看统计
stats = dm.get_stats()
print(stats)
```

## 注意事项

- `save_data()` 按 date 去重，重复日期的数据不会覆盖已有记录
- `load_data()` 自动检测文件格式（紧凑 dict 或完整 list），无需手动判断
- 存储路径中的 `{name}` 部分直接使用传入的 name 参数，建议使用纯英文或下划线避免路径问题
- record.xml 由 DataManager 自动维护，外部不应手动修改