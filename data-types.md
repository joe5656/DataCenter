# DataCenter 数据类型说明书

本文档定义 DataCenter 支持的所有数据类型，说明每个数据类型的 schema、存储路径、支持查询的 filter 类型及其实测结果。

---

## 通用约定

### Filter 类型说明

| Filter 类型 | 描述 | 示例 |
|------------|------|------|
| **Path Filter** | 用于 glob 路径扫描，减少文件 I/O | `date="2026-05-15"` |
| **Row Filter** | 在 DataFrame 读取后过滤内存数据 | `market="XHKG"` |

**Filter 值类型**:

| 类型 | 格式 | 说明 |
|------|------|------|
| 单值 | `key=value` | 精确匹配 |
| 枚举 | `key=[val1, val2]` | 匹配列表中任意值 |
| 范围 | `key={"start": "A", "end": "B"}` | 闭区间匹配 |

**注意**: `Year` 和 `Month` 是内置字段，从 `date` 字段自动解析，不作为独立查询字段传入。

---

## 一、stock_5min（五分钟 K 线）

### Schema 定义

**文件**: `schemas/stock_5min_v1.json`

```json
{
  "name": "stock_5min",
  "version": "v1",
  "data_schema": {
    "Year": "string",
    "Month": "string",
    "date": "string",
    "time": "string",
    "market": "string",
    "stock_code": "string",
    "stock_name": "string",
    "open": "float",
    "close": "float",
    "high": "float",
    "low": "float",
    "volume": "int"
  },
  "storage_rule": "{schema.name}/{schema.Year}/{schema.Month}/{schema.date}.parquet"
}
```

### 存储路径

```
{DATA_DIR}/stock_5min/{Year}/{Month}/{date}.parquet
```

每个 `.parquet` 文件对应**一天**的数据。文件名即日期（如 `2026-05-15.parquet`）。

### Filter 支持

#### Path Filter（路径级过滤）

| Filter 字段 | 类型 | 示例 | 说明 |
|------------|------|------|------|
| `date` | 单值 | `date="2026-05-15"` | 精确一天 |
| `date` | 枚举 | `date=["2026-05-15", "2026-05-16"]` | 多天 |
| `date` | 范围 | `date={"start": "2026-05-15", "end": "2026-05-17"}` | 日期区间 |
| `Year` | 单值 | `Year="2026"` | 年份（内置，从 date 解析） |
| `Year` | 枚举 | `Year=["2026"]` | 年份枚举 |
| `Year` | 范围 | `Year={"start": "2026", "end": "2026"}` | 年份区间 |
| `Month` | 单值 | `Month="05"` | 月份（内置，从 date 解析） |
| `Month` | 枚举 | `Month=["05", "06"]` | 多月 |
| `Month` | 范围 | `Month={"start": "05", "end": "06"}` | 月份区间 |

#### Row Filter（行级过滤）

| Filter 字段 | 类型 | 示例 | 说明 |
|------------|------|------|------|
| `market` | 单值 | `market="XHKG"` | 港股市场 |
| `market` | 枚举 | `market=["XHKG", "XSHG"]` | 多市场 |
| `stock_code` | 单值 | `stock_code="00700"` | 腾讯控股 |
| `stock_code` | 枚举 | `stock_code=["00700", "600519"]` | 多股票 |

#### 组合 Filter

| Filter 组合 | 示例 |
|------------|------|
| 日期范围 + 市场枚举 + 股票单值 | `date={"start": "2026-05-15", "end": "2026-05-17"}, market=["XHKG","XSHG"], stock_code="00700"` |

### 实测数据

- **测试数据**: 2026-05-15/16/17 × 3 市场（XHKG/XSHG/XSHE）× 3 股票
- **每日每市场数据量**: 216 行（72 条/股票 × 3 股票）
- **全量数据**: 648 行

---

## 二、stock_30min（三十分钟 K 线）

### Schema 定义

**文件**: `schemas/stock_30min_v1.json`

```json
{
  "name": "stock_30min",
  "version": "v1",
  "data_schema": {
    "Year": "string",
    "Month": "string",
    "date": "string",
    "time": "string",
    "market": "string",
    "stock_code": "string",
    "stock_name": "string",
    "open": "float",
    "close": "float",
    "high": "float",
    "low": "float",
    "volume": "int"
  },
  "storage_rule": "{schema.name}/{schema.Year}/{schema.Month}.parquet"
}
```

### 存储路径

```
{DATA_DIR}/stock_30min/{Year}/{Month}.parquet
```

每个 `.parquet` 文件对应**一个月**的数据。

### Filter 支持

#### Path Filter（路径级过滤）

| Filter 字段 | 类型 | 示例 | 说明 |
|------------|------|------|------|
| `Year` | 单值/枚举/范围 | `Year="2026"` | 年份 |
| `Month` | 单值/枚举/范围 | `Month="05"` | 月份 |

#### Row Filter（行级过滤）

| Filter 字段 | 类型 | 示例 | 说明 |
|------------|------|------|------|
| `date` | 单值/枚举/范围 | `date="2026-05-15"` | 日期 |
| `market` | 单值/枚举 | `market="XHKG"` | 市场 |
| `stock_code` | 单值/枚举 | `stock_code="00700"` | 股票代码 |

### 实测数据

- **测试数据**: 2026-05/06 × 3 市场 × 3 股票
- **每月每市场数据量**: 33 行（11 条/股票 × 3 股票）
- **全量数据**: 66 行

---

## 三、stock_60min（一小时 K 线）

### Schema 定义

**文件**: `schemas/stock_60min_v1.json`

```json
{
  "name": "stock_60min",
  "version": "v1",
  "data_schema": {
    "Year": "string",
    "Month": "string",
    "date": "string",
    "time": "string",
    "market": "string",
    "stock_code": "string",
    "stock_name": "string",
    "open": "float",
    "close": "float",
    "high": "float",
    "low": "float",
    "volume": "int"
  },
  "storage_rule": "{schema.name}/{schema.Year}/{schema.Month}.parquet"
}
```

### 存储路径

```
{DATA_DIR}/stock_60min/{Year}/{Month}.parquet
```

每个 `.parquet` 文件对应**一个月**的数据。

### Filter 支持

#### Path Filter（路径级过滤）

| Filter 字段 | 类型 | 示例 | 说明 |
|------------|------|------|------|
| `Year` | 单值/枚举/范围 | `Year="2026"` | 年份 |
| `Month` | 单值/枚举/范围 | `Month="05"` | 月份 |

#### Row Filter（行级过滤）

| Filter 字段 | 类型 | 示例 | 说明 |
|------------|------|------|------|
| `date` | 单值/枚举/范围 | `date="2026-05-15"` | 日期 |
| `market` | 单值/枚举 | `market="XHKG"` | 市场 |
| `stock_code` | 单值/枚举 | `stock_code="00700"` | 股票代码 |

### 实测数据

- **测试数据**: 2026-05/06 × 3 市场 × 3 股票
- **每月每市场数据量**: 18 行（6 条/股票 × 3 股票）
- **全量数据**: 36 行

---

## 四、stock_1day（日 K 线）

### Schema 定义

**文件**: `schemas/stock_1day_v1.json`

```json
{
  "name": "stock_1day",
  "version": "v1",
  "data_schema": {
    "Year": "string",
    "Month": "string",
    "date": "string",
    "time": "string",
    "market": "string",
    "stock_code": "string",
    "stock_name": "string",
    "open": "float",
    "close": "float",
    "high": "float",
    "low": "float",
    "volume": "int"
  },
  "storage_rule": "{schema.name}/{schema.Year}/{schema.Month}.parquet"
}
```

### 存储路径

```
{DATA_DIR}/stock_1day/{Year}/{Month}.parquet
```

每个 `.parquet` 文件对应**一个月**的数据。

### Filter 支持

#### Path Filter（路径级过滤）

| Filter 字段 | 类型 | 示例 | 说明 |
|------------|------|------|------|
| `Year` | 单值/枚举/范围 | `Year="2026"` | 年份 |
| `Month` | 单值/枚举/范围 | `Month="05"` | 月份 |

#### Row Filter（行级过滤）

| Filter 字段 | 类型 | 示例 | 说明 |
|------------|------|------|------|
| `date` | 单值/枚举/范围 | `date="2026-05-15"` | 日期 |
| `market` | 单值/枚举 | `market="XHKG"` | 市场 |
| `stock_code` | 单值/枚举 | `stock_code="00700"` | 股票代码 |

### 实测数据

- **测试数据**: 2026-05/06 × 3 市场 × 3 股票
- **每月每市场数据量**: 3 行（1 条/股票 × 3 股票）
- **全量数据**: 6 行

---

## 五、Filter 对比总表

| 数据类型 | Path Filter | Row Filter | 存储粒度 | 说明 |
|---------|------------|-----------|---------|------|
| stock_5min | date / Year / Month | market / stock_code | 一天/文件 | 日内高频数据，路径含日期 |
| stock_30min | Year / Month | date / market / stock_code | 一月/文件 | 日内中频数据，路径仅月 |
| stock_60min | Year / Month | date / market / stock_code | 一月/文件 | 日内低频数据，路径仅月 |
| stock_1day | Year / Month | date / market / stock_code | 一月/文件 | 日线数据，路径仅月 |

---

## 六、Filter 规则说明

### 路径设计决定 Filter 类型

storage_rule 中出现的 `{schema.xxx}` 字段决定该字段是否作为 Path Filter：

| storage_rule 包含 | Filter 类型 | 原因 |
|-----------------|------------|------|
| `{schema.date}` | **Path Filter** | date 在路径中，可 glob 扫描 |
| `{schema.Year}` / `{schema.Month}` | **Path Filter** | 内置字段，从 date 解析，也作为 Path Filter |
| `{schema.market}` / `{schema.stock_code}` | **Row Filter** | 不在路径中，无法路径级过滤 |

### Year / Month 内置机制

`Year` 和 `Month` 字段无需用户传入：
- 写入时：从 `date` 字段自动解析（如 `date="2026-05-15"` → `Year="2026"`, `Month="05"`）
- 读取时：同样可作为 Path Filter 传入，与 `date` 的路径渲染共享解析逻辑

### Filter 优先级

Path Filter 优于 Row Filter：
1. 先用 Path Filter 缩小文件范围（glob 扫描）
2. 再用 Row Filter 在内存中精确过滤（DataFrame.filter）

这样可以减少 I/O 开销，适合大数据量场景。

---

## 七、测试验证结果

### 57 个 Filter 测试全部通过 ✅

| 数据类型 | Path Filter 测试 | Row Filter 测试 | 组合测试 | 状态 |
|---------|-----------------|----------------|---------|------|
| stock_5min | 9 项（date/Year/Month 各3种类型） | 4 项（market/stock_code 单值+枚举） | 1 项 | ✅ 全部通过 |
| stock_30min | 6 项（Year/Month 各3种类型） | 6 项（date/market/stock_code 各单值+枚举） | 1 项 | ✅ 全部通过 |
| stock_60min | 6 项（Year/Month 各3种类型） | 6 项（date/market/stock_code 各单值+枚举） | 1 项 | ✅ 全部通过 |
| stock_1day | 6 项（Year/Month 各3种类型） | 6 项（date/market/stock_code 各单值+枚举） | 1 项 | ✅ 全部通过 |

**测试覆盖**: 单值 / 枚举 / 范围 三种 Filter 值类型 × 每个可用字段

---

## 八、扩展新数据类型

### 8.1 开发流程

```
定义 Schema JSON
    → 放置到 schemas/ 目录
    → SchemaManager 自动加载
    → IndexManager 自动识别 Path Filter
    → 定义单元测试（fixtures）
    → 运行单元测试
    → 编写集成测试（写入/读取/Filter 验证）
    → 运行集成测试
    → 更新文档（data-types.md / README.md）
```

### 8.2 定义 Schema

在 `schemas/` 目录下创建 `{data_type}_v1.json`：

```json
{
  "name": "{data_type}",
  "version": "v1",
  "data_schema": {
    "Year": "string",
    "Month": "string",
    "date": "string",
    "time": "string",
    "market": "string",
    "stock_code": "string",
    "stock_name": "string",
    "open": "float",
    "close": "float",
    "high": "float",
    "low": "float",
    "volume": "int"
  },
  "storage_rule": "{schema.name}/{schema.Year}/{schema.Month}.parquet"
}
```

**storage_rule 设计原则**:
- 需要路径级过滤（减少 I/O）的字段放入路径
- 只需查询但不需要路径分组的字段放在 Row Filter
- 必须以 `.parquet` 结尾

### 8.3 自动识别 Path Filter

`IndexManager._extract_path_refs()` 从 storage_rule 自动提取 Path Filter 字段：

```
storage_rule = "{schema.name}/{schema.Year}/{schema.Month}/{schema.date}.parquet"
                        ↓
Path Filter = ['Year', 'Month', 'date']（内置 + 自定义路径字段）
Row Filter  = [data_schema 中的其他字段]
```

### 8.4 单元测试 Fixture 模板

```python
import pytest
from app.schema_manager import SchemaManager
from app.index_manager import IndexManager
from app.data_processor import DataProcessor

@pytest.fixture
def new_type_schema(tmp_path):
    schema_file = tmp_path / "new_type_v1.json"
    schema_file.write_text(json.dumps({
        "name": "new_type",
        "version": "v1",
        "data_schema": {
            "Year": "string", "Month": "string", "date": "string",
            "time": "string", "market": "string", "stock_code": "string",
            "stock_name": "string", "open": "float", "close": "float",
            "high": "float", "low": "float", "volume": "int"
        },
        "storage_rule": "{schema.name}/{schema.Year}/{schema.Month}/{schema.date}.parquet"
    }))
    return tmp_path

def test_new_type_get_write_paths(new_type_schema):
    sm = SchemaManager(str(new_type_schema))
    im = IndexManager(sm)
    # ... 测试代码
```

### 8.5 集成测试模板

```python
def test_new_type_filter(new_type_schema):
    sm = SchemaManager(str(new_type_schema))
    # 写入测试数据
    # 测试 date 单值/枚举/范围
    # 测试 market 单值/枚举
    # 测试组合 Filter
    # 验证数据完整性
```

### 8.6 必需测试场景

| 场景 | 说明 |
|------|------|
| 写入新数据类型 | 多行 DataFrame 正确写入 |
| 按 Path Filter 读取 | date/Year/Month 单值、枚举、范围 |
| 按 Row Filter 读取 | market/stock_code 单值、枚举 |
| 无 Filter 全量读取 | 返回全部数据 |
| 数据完整性 | 写入行数 = 读取行数 |
| 数值精度 | open/close/high/low/volume 总和一致 |
| 空结果 | 无匹配数据时返回空 DataFrame |

---

**最后更新**: 2026-05-18