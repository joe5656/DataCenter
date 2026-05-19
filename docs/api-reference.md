# DataCenter RESTful API 说明文档

**版本**: v1.1.0  
**基础路径**: `/api/v1`  
**数据格式**: JSON

---

## 1. 概述

DataCenter 提供金融行情数据的写入、查询、覆盖、删除接口，数据以 Parquet 格式按 `storage_rule` 定义的路径结构存储。

当前注册的数据类型：

| 数据类型 | 说明 | storage_rule | 存储粒度 |
|----------|------|-------------|----------|
| `stock_5min` | 5分钟K线 | `{schema.name}/{schema.Year}/{schema.Month}/{schema.date}.parquet` | 按日 |
| `stock_30min` | 30分钟K线 | `{schema.name}/{schema.Year}/{schema.Month}.parquet` | 按月 |
| `stock_60min` | 60分钟K线 | `{schema.name}/{schema.Year}/{schema.Month}.parquet` | 按月 |
| `stock_1day` | 日线 | `{schema.name}/{schema.Year}/{schema.Month}.parquet` | 按月 |

> 新增数据类型只需添加 schema JSON 文件并在 data_interface.yaml 注册路由，无需修改代码。

---

## 2. 通用 Schema 定义

所有数据类型共享以下字段结构（stock_1day 无 time 字段）：

| 字段 | 类型 | 必填 | 说明 | 示例 |
|------|------|------|------|------|
| `Year` | string | 是 | 年份，由 date 自动提取 | `"2026"` |
| `Month` | string | 是 | 月份，由 date 自动提取 | `"05"` |
| `date` | string | 是 | 日期 | `"2026-05-19"` |
| `time` | string | 5min/30min/60min 必填 | 时间 | `"09:30"` |
| `market` | string | 是 | 市场代码 | `"XHKG"` / `"XSHG"` / `"XSHE"` |
| `stock_code` | string | 是 | 股票代码 | `"00700"` / `"600519"` |
| `stock_name` | string | 否 | 股票名称 | `"腾讯控股"` |
| `open` | double | 是 | 开盘价 | `487.6` |
| `close` | double | 是 | 收盘价 | `490.2` |
| `high` | double | 是 | 最高价 | `492.1` |
| `low` | double | 是 | 最低价 | `485.3` |
| `volume` | int64 | 是 | 成交量 | `1151507943` |

---

## 3. 端点列表

| 方法 | 端点 | 功能 | 控制 |
|------|------|------|------|
| `GET` | `/api/v1/{data_type}` | 查询数据 | — |
| `POST` | `/api/v1/{data_type}` | 写入数据（追加，自动去重） | — |
| `PUT` | `/api/v1/{data_type}` | 全量覆盖 | `ALLOW_PUT` 开关 |
| `DELETE` | `/api/v1/{data_type}` | 删除文件 | `ALLOW_DELETE` 开关 |
| `GET` | `/api/v1/{data_type}/schemas` | 查看 Schema 定义 | — |
| `GET` | `/api/v1/{data_type}/stats` | 查看存储统计 | — |

---

## 4. 查询接口 GET

### 4.1 请求格式

```
GET /api/v1/{data_type}?version=v1&f_{field}={value}&...
```

### 4.2 系统参数

| 参数 | 位置 | 默认值 | 说明 |
|------|------|--------|------|
| `version` | Query | `v1` | Schema 版本号 |

### 4.3 Filter 参数格式

所有 filter 参数必须带 `f_` 前缀，无前缀的参数为系统参数。handler 无需硬编码字段白名单，任何 `f_` 开头的参数自动识别为 filter。

**值格式**：

| 格式 | 语法 | 示例 | 解析结果 |
|------|------|------|----------|
| 单值 | `f_{field}={value}` | `f_date=2026-05-19` | `"2026-05-19"` |
| 枚举 | `f_{field}={v1},{v2},{v3}` | `f_stock_code=00700,09988` | `["00700","09988"]` |
| 范围 | `f_{field}={start}~{end}` | `f_date=2026-05-01~2026-05-19` | `{"start":"2026-05-01","end":"2026-05-19"}` |
| 大于等于 | `f_{field}={value}~` | `f_close=400~` | `{"start":"400"}` |
| 小于等于 | `f_{field}=~{value}` | `f_volume=~1000000` | `{"end":"1000000"}` |

**解析规则**：

1. 参数名以 `f_` 开头 → 提取字段名（`f_date` → `date`）
2. 值含 `~` → 范围格式，按 `~` 分割为 start/end
3. 值含 `,` → 枚举格式，按 `,` 分割为列表
4. 其他 → 单值

### 4.4 过滤机制

查询过滤分两层执行：

#### 第一层：路径过滤（IndexManager）

IndexManager 解析 `storage_rule` 中的 `{schema.xxx}` 占位符，将 filter 值填入生成 glob 模式，仅扫描匹配的文件。**这是通用算法，不区分数据类型**——任何出现在 storage_rule 路径中的字段都自动成为路径级过滤字段。

**`date` 字段的路径过滤效果**：

| 数据类型 | 传入 `f_date=2026-05-19` 后的 glob 模式 | 过滤精度 |
|----------|----------------------------------------|----------|
| `stock_5min` | `stock_5min/2026/05/2026-05-19.parquet` | 精确到日 |
| `stock_30min` | `stock_30min/2026/05.parquet` | 精确到月 |
| `stock_60min` | `stock_60min/2026/05.parquet` | 精确到月 |
| `stock_1day` | `stock_1day/2026/05.parquet` | 精确到月 |

> `Year` 和 `Month` 由 `date` 自动推导填入路径，无需单独传入。

#### 第二层：行级过滤（DataProcessor）

读取文件后，对 DataFrame 逐字段过滤。**支持所有 schema 字段**。

| 字段 | 适用数据类型 | 过滤说明 |
|------|-------------|----------|
| `date` | 全部 | 同路径级，范围/枚举/单值 |
| `Year` | 全部 | 年份过滤 |
| `Month` | 全部 | 月份过滤 |
| `market` | 全部 | 市场代码过滤 |
| `stock_code` | 全部 | 股票代码过滤 |
| `stock_name` | 全部 | 股票名称过滤 |
| `time` | 5min/30min/60min | 时间过滤 |
| `open` | 全部 | 开盘价范围过滤 |
| `close` | 全部 | 收盘价范围过滤 |
| `high` | 全部 | 最高价范围过滤 |
| `low` | 全部 | 最低价范围过滤 |
| `volume` | 全部 | 成交量范围过滤 |

### 4.5 查询示例

```bash
# 单值过滤
GET /api/v1/stock_5min?f_date=2026-05-19&f_stock_code=00700

# 日期范围 + 多股票
GET /api/v1/stock_5min?f_date=2026-05-01~2026-05-19&f_stock_code=00700,09988

# 价格区间
GET /api/v1/stock_1day?f_date=2026-05-01~2026-05-19&f_close=400~500&f_market=XHKG

# 开放式范围
GET /api/v1/stock_5min?f_date=2026-05-01~&f_volume=1000000~

# 按 year/month 过滤
GET /api/v1/stock_30min?f_year=2026&f_month=05
```

### 4.6 响应格式

**成功（有数据）**：

```json
{
  "success": true,
  "data": [
    {
      "Year": "2026",
      "Month": "05",
      "date": "2026-05-19",
      "time": "09:30",
      "market": "XHKG",
      "stock_code": "00700",
      "stock_name": "腾讯控股",
      "open": 487.6,
      "close": 490.2,
      "high": 492.1,
      "low": 485.3,
      "volume": 1151507943
    }
  ],
  "metadata": {
    "data_type": "stock_5min",
    "version": "v1",
    "total_rows": 1,
    "filters": {"date": "2026-05-19", "stock_code": "00700"}
  }
}
```

**成功（无数据）**：

```json
{
  "success": true,
  "data": [],
  "metadata": {
    "data_type": "stock_5min",
    "version": "v1",
    "total_rows": 0,
    "filters": {"date": "2099-01-01"},
    "message": "No matching data found"
  }
}
```

**Schema 不存在**：

```json
{
  "success": false,
  "error": "Schema not found: invalid_type"
}
```

---

## 5. 写入接口 POST

### 5.1 请求格式

```
POST /api/v1/{data_type}
Content-Type: application/json
```

```json
{
  "version": "v1",
  "data": [
    {
      "Year": "2026",
      "Month": "05",
      "date": "2026-05-19",
      "time": "09:30",
      "market": "XHKG",
      "stock_code": "00700",
      "stock_name": "腾讯控股",
      "open": 487.6,
      "close": 490.2,
      "high": 492.1,
      "low": 485.3,
      "volume": 1151507943
    }
  ]
}
```

> 字段名必须严格匹配 Schema 定义：`stock_code`（非 `ticker`/`code`），`market`（非 `exchange`）。

### 5.2 写入行为

| 特性 | 说明 |
|------|------|
| 写入模式 | 追加（append） |
| 自动分组 | 按 storage_rule 自动将数据分组到不同文件 |
| 去重检查 | 按主键（`date + stock_code [+ time]`）检查重复 |
| 重复处理 | 发现重复返回错误，不自动覆盖 |
| Schema 验证 | 字段名和类型必须匹配 schema 定义 |

### 5.3 响应

**成功** (201)：

```json
{
  "success": true,
  "message": "Data written successfully",
  "details": {
    "data_type": "stock_5min",
    "version": "v1",
    "total_rows": 10,
    "files_written": 1,
    "file_paths": ["/app/data/stock_5min/2026/05/2026-05-19.parquet"],
    "duplicates_found": 0,
    "duplicates_removed": 0
  }
}
```

**重复数据** (400)：

```json
{
  "success": false,
  "error": "Data validation failed",
  "details": ["Found 3 duplicate rows in stock_5min/2026/05/2026-05-19.parquet"]
}
```

**Schema 验证失败** (400)：

```json
{
  "success": false,
  "error": "Data validation failed",
  "details": ["Missing required field: stock_code"]
}
```

---

## 6. 覆盖接口 PUT

受 `ALLOW_PUT` 配置开关控制，关闭时返回 HTTP 405。

请求格式同 POST，写入模式为 `overwrite`（全量覆盖对应路径的 Parquet 文件）。

---

## 7. 删除接口 DELETE

受 `ALLOW_DELETE` 配置开关控制，关闭时返回 HTTP 405。

### 请求格式

```
DELETE /api/v1/{data_type}?version=v1&f_{field}={value}
```

### 行为

| 特性 | 说明 |
|------|------|
| 过滤要求 | 须传入至少一个 `f_` filter 参数 |
| 删除粒度 | **文件级**，按 filter 匹配到的整个 Parquet 文件删除，非行级删除 |
| Filter 格式 | 与 GET 查询相同，使用 `f_` 前缀 |

### 响应

```json
{
  "success": true,
  "message": "Deleted 1 file(s)",
  "details": {
    "data_type": "stock_5min",
    "version": "v1",
    "files_deleted": 1,
    "filters": {"date": "2026-05-19"},
    "errors": null
  }
}
```

---

## 8. Schema 查询 GET /schemas

```
GET /api/v1/{data_type}/schemas
```

返回该数据类型的 Schema 定义信息，包含字段列表和存储规则。

```json
{
  "success": true,
  "data_type": "stock_5min",
  "schemas": [
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
        "open": "double",
        "close": "double",
        "high": "double",
        "low": "double",
        "volume": "int64"
      },
      "storage_rule": "{schema.name}/{schema.Year}/{schema.Month}/{schema.date}.parquet"
    }
  ],
  "count": 1
}
```

---

## 9. 存储统计 GET /stats

```
GET /api/v1/{data_type}/stats
```

返回该数据类型的存储统计信息。

```json
{
  "success": true,
  "stats": {
    "data_type": "stock_5min",
    "version": "v1",
    "total_files": 15,
    "total_rows": 49800,
    "total_size_bytes": 1234567,
    "total_size_mb": 1.18
  }
}
```

---

## 10. 存储路径示例

以 `stock_code=00700`, `date=2026-05-19` 为例：

| 数据类型 | 实际存储路径 | 一个文件包含 |
|----------|-------------|-------------|
| `stock_5min` | `stock_5min/2026/05/2026-05-19.parquet` | 当日所有股票的5分钟数据 |
| `stock_30min` | `stock_30min/2026/05.parquet` | 当月所有股票的30分钟数据 |
| `stock_60min` | `stock_60min/2026/05.parquet` | 当月所有股票的60分钟数据 |
| `stock_1day` | `stock_1day/2026/05.parquet` | 当月所有股票的日线数据 |

> 存储路径由 `storage_rule` 决定，不同股票的数据存储在同一文件中，通过 `stock_code` 行级过滤区分。

---

## 11. 错误码汇总

| HTTP 状态码 | 含义 | 场景 |
|-------------|------|------|
| 200 | 成功 | GET 查询成功（含空结果） |
| 201 | 创建成功 | POST 写入成功 |
| 400 | 请求错误 | 缺少必填字段、Schema 验证失败、数据重复 |
| 404 | 未找到 | data_type 不存在、Schema 不存在 |
| 405 | 方法不允许 | PUT/DELETE 被配置开关禁用 |
| 500 | 服务器错误 | 内部异常 |

---

## 12. 已知限制与待改进

| # | 限制 | 说明 | 建议 |
|---|------|------|------|
| 1 | date 重复过滤 | 路径级已过滤的 date，DataProcessor 又做一次行级过滤 | IndexManager 将 filters 分为路径级/行级返回，DataProcessor 只处理行级 |
| 2 | year/month 独立传入效率低 | 不传 date 时 year/month 只做行级过滤，无法缩小文件扫描 | 鼓励通过 date 传入 |
