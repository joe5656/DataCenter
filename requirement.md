# DataCenter 需求文档

本文档记录 DataCenter 项目的所有需求，由需求方（用户）提供，AI 根据文档实现。

---

## 需求列表

| 编号 | 标题 | 状态 | 创建日期 |
|------|------|------|----------|
| REQ-001 | 采用 Parquet 进行基础数据存储 | 待实现 | 2026-05-11 |

---

## REQ-001：采用 Parquet 进行基础数据存储

**需求方**：用户  
**创建日期**：2026-05-11  
**状态**：待实现  
**优先级**：高

### 1. 背景

当前 DataCenter 使用 JSON 紧凑格式存储 K 线数据，定义在 `data_schema.xml` 中。

**现有存储结构**（JSON 紧凑格式）：

```
{data_dir}/{exchange}/{name}_{code}/{YYYYMM}.json
```

文件内容为 JSON 数组，按 schema index 顺序排列：

```json
[
  "0700",         // [0] code
  "XHKG",         // [1] exchange
  "腾讯控股",      // [2] name
  "5min",         // [3] period
  2025,           // [4] year
  4,              // [5] month
  66,             // [6] total_entry
  3,              // [7] total_date
  [               // [8] data
    ["2025-04-28", [["09:30", 350.0, 351.0, 349.5, 350.5, 1000000], ...]],
    ["2025-04-29", [["09:30", 351.0, ...], ...]],
    ...
  ]
]
```

数据分层组织：按 `年/月` 打包（每个文件含一整个月的分钟数据）。

**当前架构分析**（`data_manager.py`）：

- `DataSchema`：从 `data_schema.xml` 解析字段定义（树型结构）
- `DataRecord`：DOM 模式，管理单只标的单月数据，含 `to_compact()` / `to_full()` 双向转换
- `DataManager`：负责 `save_data()` 和 `load_data()`，按 `exchange/code/year/month` 组织文件

**已收集的数据规模**：

- 30 只恒生科技指数成分股
- 2025-01 至 2026-04，共约 16 个月的 5min 分钟数据
- 数据类型：OHLCV（开盘价、最高价、最低价、收盘价、成交量）

### 2. 问题与动机

JSON 紧凑格式的局限：

| 问题 | 说明 |
|------|------|
| **读写性能** | JSON 解析全文件加载，修改时需读写整个文件，月份数据越大越慢 |
| **空间效率** | 纯文本格式，无压缩；数字也存为字符串，浪费空间 |
| **查询能力** | 无法按列过滤（如只查 close 列），必须解析整个文件 |
| **类型安全** | 所有数字在 JSON 中都是 float，无法区分 int/float/decimal |
| **生态兼容性** | JSON 不便于 pandas 直接读取（需手动处理格式） |

### 3. Parquet 方案分析

**Parquet 优势**：

- 列式存储 + 多种压缩算法（Snappy/Zstd），空间节省约 50-80%
- 支持谓词下推（Predicate Pushdown），按列和行组过滤，查询快 10-100x
- 支持嵌套结构（Repetition Level / Definition Level），贴合 K 线数据
- 原生被 pandas `pd.read_parquet()` / `df.to_parquet()` 支持
- Arrow 生态系统互通

**Parquet 局限**：

- 不适合频繁单条写入（append 代价高），适合批量全量写入
- 单文件追加更新需要重写文件，需设计分区策略

### 4. 实现建议

#### 4.1 分区策略

建议按 `date`（日期）分区，而非现有的 `year/month` 打包：

```
{data_dir}/{exchange}/{code}/{date}.parquet
```

例如：`data/XHKG/0700/2025-04-28.parquet`

**理由**：
- Parquet 谓词下推以行组（Row Group）为单位，按日期分区可精准跳过不需要的日期
- 数据工程中日期是最常用的过滤维度
- 每日数据量稳定（港股 5min 约 66 条/日），文件大小适中

#### 4.2 数据 Schema

```python
import pyarrow as pa
import pyarrow.parquet as pq

schema = pa.schema([
    ("code",      pa.string()),          # 标的代码
    ("exchange",  pa.string()),          # 交易所
    ("name",      pa.string()),          # 标的名称
    ("period",    pa.string()),          # K线周期
    ("date",      pa.date32()),           # 日期
    ("time",      pa.string()),           # 时间（HH:MM）
    ("open",      pa.float64()),          # 开盘价
    ("high",      pa.float64()),          # 最高价
    ("low",       pa.float64()),          # 最低价
    ("close",     pa.float64()),          # 收盘价
    ("volume",    pa.float64()),          # 成交量
])
```

> 注意：`code`、`exchange`、`name`、`period` 作为每个 parquet 文件的 metadata 存储，而非每行重复，避免空间浪费。

#### 4.3 写入流程（批量模式）

```
DataFrame (source) → 预处理 → 按 date 分组 → 每组一个 parquet 文件
```

```python
def save_data_parquet(exchange, code, name, df: pd.DataFrame, period="5min"):
    # 1. 预处理
    df["code"]     = code
    df["exchange"] = exchange
    df["name"]     = name
    df["period"]   = period
    df["date"]     = pd.to_datetime(df["date"]).dt.date

    # 2. 按日期分组，每组一个文件
    for date, group in df.groupby("date"):
        filepath = f"{data_dir}/{exchange}/{code}/{date}.parquet"
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        # 3. 追加写入（已有文件则合并去重）
        if os.path.exists(filepath):
            existing = pd.read_parquet(filepath)
            combined = pd.concat([existing, group]).drop_duplicates(subset=["date","time"]).sort_values("time")
        else:
            combined = group.sort_values("time")

        # 4. 写入 + 列级压缩
        combined.to_parquet(
            filepath,
            engine="pyarrow",
            compression="zstd",       # Zstd 压缩率好于 Snappy
            index=False,
        )
```

#### 4.4 读取优化

```python
def load_data_parquet(exchange, code, start_date, end_date) -> pd.DataFrame:
    """按日期范围读取，支持谓词下推"""
    base = f"{data_dir}/{exchange}/{code}/"
    files = [
        f for f in os.listdir(base)
        if start_date <= f[:-8] <= end_date    # 过滤文件名中的日期
    ]
    dfs = [pd.read_parquet(os.path.join(base, f)) for f in files]
    return pd.concat(dfs, ignore_index=True)
```

Parquet 会自动在文件级别跳过不符合条件的行组，无需全量读入。

#### 4.5 JSON → Parquet 迁移

设计一个一次性迁移脚本：

```python
def migrate_json_to_parquet(data_dir: str, output_dir: str):
    """遍历所有 JSON 文件，转换为 Parquet 分区格式"""
    for root, _, files in os.walk(data_dir):
        for fname in files:
            if not fname.endswith(".json"):
                continue
            json_path = os.path.join(root, fname)
            df = load_json_as_df(json_path)   # 复用现有的 from_compact 逻辑

            # 按日期写出
            for date, group in df.groupby("date"):
                out_path = f"{output_dir}/{df['exchange'].iloc[0]}/{df['code'].iloc[0]}/{date}.parquet"
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                group.to_parquet(out_path, engine="pyarrow", compression="zstd", index=False)
```

### 5. 决策点（需需求方确认）

| 问题 | 选项 |
|------|------|
| **文件粒度** | A. 按日拆分成独立 .parquet 文件 / B. 仍按月合并（但用 Parquet 压缩） |
| **压缩算法** | A. Zstd（推荐，压缩率高） / B. Snappy（解压更快） |
| **迁移策略** | A. 一次性迁移所有历史 JSON / B. 新数据用 Parquet，历史保持 JSON |
| **兼容性** | A. 废弃 JSON，仅保留 Parquet / B. 双写并行，DataManager 同时支持两种格式 |
| **依赖包** | 需新增 `pyarrow`（`pip install pyarrow`），是否接受？ |

### 6. 验收标准

- [ ] Parquet 写入功能可用，单日数据写入正常
- [ ] Parquet 读取功能可用，支持按日期范围过滤
- [ ] 文件大小对比 JSON 减少 ≥ 50%
- [ ] 迁移脚本可将现有 JSON 数据转换为 Parquet
- [ ] 读写接口与现有 `DataManager.save_data()` / `load_data()` 行为一致（外部无感知）
