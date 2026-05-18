# DataCenter - 金融数据存储中心

基于 Parquet 格式的金融 K 线数据存储系统，支持多级别、多市场、多日期的数据写入与读取。

## 项目结构

```
DataCenter/
├── app/                    # 核心模块
│   ├── config.py           # 配置管理（环境变量/XML/运行时覆盖）
│   ├── schema_manager.py   # Schema 加载与验证
│   ├── storage_manager.py  # Parquet 文件 I/O + 文件锁
│   ├── index_manager.py    # 路径计算与分组
│   └── data_processor.py   # 读写协调层
├── schemas/                # Schema 定义（JSON 格式）
│   ├── stock_5min_v1.json
│   ├── stock_30min_v1.json
│   ├── stock_60min_v1.json
│   └── stock_1day_v1.json
├── config.xml              # 默认配置文件
├── tests/                  # 单元测试（144 个测试用例）
├── CTtest/                 # 集成测试
│   ├── test_write.py       # 多级别/多天/多市场写入验证
│   ├── test_filters.py     # Filter 功能测试
│   └── data/               # 测试数据目录（.gitignore）
├── test-report.md          # 测试报告
├── data-types.md           # 数据类型说明书（Schema + Filter 支持）
├── requirement.md          # 需求文档
├── design-plan.md          # 设计文档
└── README.md               # 本文件
```

## 核心模块

### Config

配置管理，支持三级优先级：`runtime override > env vars > XML config > defaults`

```python
from app.config import Config

# 默认配置
config = Config()

# 环境变量覆盖
# DATACENTER_DATA_DIR=/path/to/data
# DATACENTER_COMPRESSION=SNAPPY
# DATACENTER_ALLOW_DELETE=true
# DATACENTER_ALLOW_PUT=false

# 运行时覆盖（最高优先级）
config = Config(overrides={"DATA_DIR": "/custom/path", "COMPRESSION": "GZIP"})
```

**配置项**:

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|---------|--------|------|
| DATA_DIR | DATACENTER_DATA_DIR | ~/.qclaw/datacenter | 数据存储目录 |
| COMPRESSION | DATACENTER_COMPRESSION | SNAPPY | Parquet 压缩算法 |
| ALLOW_DELETE | DATACENTER_ALLOW_DELETE | False | 是否允许删除数据 |
| ALLOW_PUT | DATACENTER_ALLOW_PUT | False | 是否允许覆写数据 |

### SchemaManager

Schema 加载、验证、数据格式检查。

```python
from app.schema_manager import SchemaManager

sm = SchemaManager("schemas/")

# 加载 schema
schema = sm.load_schema("stock_5min", "v1")

# 获取存储规则
storage_rule = sm.get_storage_rule("stock_5min", "v1")
# 返回: "{schema.name}/{schema.Year}/{schema.Month}/{schema.date}.parquet"

# 获取数据 schema
data_schema = sm.get_data_schema("stock_5min", "v1")
# 返回: {"Year": "string", "Month": "string", ...}

# 验证数据
valid, errors = sm.validate_data(df, "stock_5min", "v1")

# 列出所有 schema
schemas = sm.list_schemas()
```

**Schema 格式（REQ-003）**:

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

**验证规则**:
- 必填字段：name / version / data_schema / storage_rule
- data_schema：dict、非空、key-value 均为 str
- storage_rule：字符串、必须以 `.parquet` 结尾
- `{schema.xxx}` 引用：name/version 内置免检，其他必须在 data_schema 有定义

### StorageManager

Parquet 文件读写，支持文件锁（进程安全）。

```python
from app.storage_manager import StorageManager

st = StorageManager(compression="SNAPPY")

# 写入（支持 overwrite/append 模式）
st.write_parquet([file_path], df, mode="overwrite")

# 读取
df = st.read_parquet([file_path1, file_path2])

# 删除
st.delete_parquet(file_path)

# 文件存在检查
exists = st.file_exists(file_path)

# 元数据
meta = st.get_file_metadata(file_path)
```

**支持压缩算法**: SNAPPY（默认）、GZIP、NONE

**文件锁**: 使用 `fcntl.flock` 实现
- `LOCK_EX` 写锁（排他）
- `LOCK_SH` 读锁（共享）
- 读写互斥，确保进程安全

### IndexManager

路径计算与分组，从 schema 的 storage_rule 自动推导。

```python
from app.index_manager import IndexManager

im = IndexManager(schema_manager)

# 写入路径（自动分组）
path_map = im.get_write_paths(df, "stock_5min", "v1")
# 返回: {"stock_5min/2026/05/2026-05-15.parquet": df_day1, 
#        "stock_5min/2026/05/2026-05-16.parquet": df_day2}

# 读取路径（支持 filter）
paths = im.get_read_paths("stock_5min", "v1", date="2026-05-15")
paths = im.get_read_paths("stock_5min", "v1", date=["2026-05-15", "2026-05-16"])
paths = im.get_read_paths("stock_5min", "v1", date={"start": "2026-05-15", "end": "2026-05-17"})
paths = im.get_read_paths("stock_5min", "v1", market="XHKG", stock_code="00700")
```

**Filter 支持类型**:
- 单值：`date="2026-05-15"`
- 枚举：`date=["2026-05-15", "2026-05-16"]`
- 范围：`date={"start": "2026-05-15", "end": "2026-05-17"}`

**路径渲染**:
- 从 storage_rule 提取 `{schema.xxx}` 引用
- 分离 path filters（用于 glob 扫描）和 row filters（DataFrame 过滤）

### DataProcessor

读写协调层，对外统一接口。

```python
from app.data_processor import DataProcessor

dp = DataProcessor(schema_manager, index_manager, storage_manager)

# 写入数据
result = dp.write_data(df, "stock_5min", "v1")
# 返回: {
#   "success": True,
#   "total_rows": 720,
#   "files_written": 3,
#   "file_paths": ["stock_5min/2026/05/2026-05-15.parquet", ...],
#   "duplicates_found": 0,
#   "duplicates_removed": 0
# }

# 读取数据
df = dp.read_data("stock_5min", "v1", date="2026-05-15")
df = dp.read_data("stock_5min", "v1", date={"start": "2026-05-15", "end": "2026-05-17"},
                  market="XHKG", stock_code="00700")

# 验证数据格式
valid, errors = dp.validate_schema(df, "stock_5min", "v1")
```

**写入流程**:
1. Schema 验证（列名、类型）
2. 重复检测（基于 date/code/time 主键）
3. 路径分组（按 storage_rule 字段拆分）
4. 多文件写入（自动创建父目录）
5. 返回写入结果

**读取流程**:
1. Filter 解析（path filters + row filters）
2. Glob 扫描实际文件
3. 合并读取多个 Parquet
4. Row filter 过滤（DataFrame 级别）

## 数据流程

### 写入管线

```
DataFrame 输入
    → DataProcessor.write_data()
        → validate_data() [Schema 验证]
        → _find_duplicates() [重复检测]
        → IndexManager.get_write_paths() [路径分组]
        → StorageManager.write_parquet() [多文件写入]
```

### 读取管线

```
Filter 参数
    → DataProcessor.read_data()
        → IndexManager.get_read_paths() [Glob 扫描]
        → StorageManager.read_parquet() [合并读取]
        → Row filter 过滤 [DataFrame 级别]
```

## 存储路径示例

基于 `storage_rule: "{schema.name}/{schema.Year}/{schema.Month}/{schema.date}.parquet"`：

```
{DATA_DIR}/
├── stock_5min/
│   └── 2026/
│       └── 05/
│           ├── 2026-05-15.parquet
│           ├── 2026-05-16.parquet
│           └── 2026-05-17.parquet
├── stock_30min/
│   └── 2026/
│       └── 05/
│           └── 2026-05-15.parquet
├── stock_60min/
│   └── 2026/
│       └── 05/
│           └── 2026-05-15.parquet
└── stock_1day/
    └── 2026/
        └── 05/
            └── 2026-05-15.parquet
```

## 使用示例

### 完整流程

```python
import os
import pandas as pd
from app.config import Config
from app.schema_manager import SchemaManager
from app.storage_manager import StorageManager
from app.index_manager import IndexManager
from app.data_processor import DataProcessor

# 初始化
os.environ["DATACENTER_DATA_DIR"] = "/path/to/data"
config = Config()

sm = SchemaManager("schemas/")
st = StorageManager(compression=config.COMPRESSION)
im = IndexManager(sm)
dp = DataProcessor(sm, im, st)

# 生成数据
df = pd.DataFrame([
    {"Year": "2026", "Month": "05", "date": "2026-05-15", "time": "09:00",
     "market": "XHKG", "stock_code": "00700", "stock_name": "腾讯控股",
     "open": 350.0, "close": 351.5, "high": 352.0, "low": 349.0, "volume": 12345},
    ...
])

# 写入
result = dp.write_data(df, "stock_5min", "v1")
print(f"写入成功: {result['total_rows']} 行, {result['files_written']} 文件")

# 读取
df_read = dp.read_data("stock_5min", "v1", date="2026-05-15")
print(f"读取: {len(df_read)} 行")

# Filter 读取
df_hk = dp.read_data("stock_5min", "v1", 
                     date={"start": "2026-05-15", "end": "2026-05-17"},
                     market=["XHKG", "XSHG"],
                     stock_code="00700")
```

### 跨文件写入

一次写入多日数据，自动拆分到多个文件：

```python
# 3 天数据合并为一个 DataFrame
df_3days = pd.DataFrame([...])  # 包含 2026-05-15/16/17 的数据

result = dp.write_data(df_3days, "stock_5min", "v1")
# 自动生成 3 个文件：
# - stock_5min/2026/05/2026-05-15.parquet
# - stock_5min/2026/05/2026-05-16.parquet
# - stock_5min/2026/05/2026-05-17.parquet
```

## 测试

### 单元测试

```bash
pytest tests/ -v
# 144 passed, 100%
```

**测试覆盖**:
- Config: 33 测试（配置优先级、XML 加载、单例）
- SchemaManager: 54 测试（加载、验证、引用检查）
- StorageManager: 35 测试（写入、读取、压缩、文件锁）
- IndexManager: 14 测试（路径分组、filter）
- DataProcessor: 13 测试（写入、读取、验证）

### 集成测试

```bash
cd CTtest
python test_write.py    # 多级别/多天/多市场写入验证
python test_filters.py  # Filter 功能测试
```

详细测试报告见 `test-report.md`。

## 设计文档

- `requirement.md` - 需求文档（REQ-001~REQ-004）
- `design-plan.md` - 设计文档（架构、接口、Schema 格式）

## 注意事项

1. **Schema 不可动态扩展**：新增 data_type 需版本升级，SchemaManager 加载后不可变
2. **文件锁是建议锁**：fcntl.flock 是 advisory lock，非强制，需所有进程配合
3. **重复检测**：基于 schema 主键（date/code/time）自动检测并移除重复行
4. **Filter 分离**：path filters（glob 扫描）+ row filters（DataFrame 过滤）
5. **跨平台兼容**：DATA_DIR 支持环境变量/XML 配置，适配不同部署环境

## 新增数据类型开发路径

详见完整文档 `data-types.md`，以下为快速步骤：

### 步骤 1：定义 Schema

在 `schemas/` 目录下创建 `{data_type}_v1.json`：

```json
{
  "name": "stock_1min",
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

### 步骤 2：理解 Filter 设计

`storage_rule` 中出现的 `{schema.xxx}` 字段自动成为 **Path Filter**（用于 glob 扫描，减少 I/O）。`data_schema` 中未出现在路径里的字段自动成为 **Row Filter**（读取后在内存过滤）。

| storage_rule 包含 | Filter 类型 | 说明 |
|-----------------|------------|------|
| `{schema.date}` | Path Filter | date 在路径中，可 glob 扫描 |
| `{schema.Year}` / `{schema.Month}` | Path Filter（内置） | 自动从 date 解析 |
| `{schema.market}` / `{schema.stock_code}` | Row Filter | 不在路径中，读取后过滤 |

**示例对比**：

| 数据类型 | storage_rule | Path Filter | Row Filter |
|---------|-------------|------------|------------|
| stock_5min | `{name}/{Year}/{Month}/{date}.parquet` | date / Year / Month | market / stock_code |
| stock_30min | `{name}/{Year}/{Month}.parquet` | Year / Month | date / market / stock_code |

### 步骤 3：编写单元测试

```python
# tests/test_data_processor.py 中添加 fixture
{
    "name": "new_type",
    "version": "v1",
    "data_schema": {"Year": "string", "Month": "string", "date": "string",
                      "time": "string", "market": "string", "stock_code": "string",
                      "stock_name": "string", "open": "float", "close": "float",
                      "high": "float", "low": "float", "volume": "int"},
    "storage_rule": "{schema.name}/{schema.Year}/{schema.Month}/{schema.date}.parquet"
}
```

### 步骤 4：运行测试

```bash
pytest tests/ -v
```

### 步骤 5：编写集成测试（Filter 验证）

```bash
# CTtest/test_filters.py 中添加新数据类型测试
# 必需场景：
#   - date/Year/Month: 单值 + 枚举 + 范围
#   - market/stock_code: 单值 + 枚举
#   - 组合 Filter
#   - 无 Filter 全量读取
```

### 步骤 6：运行集成测试

```bash
cd CTtest
python test_write.py
python test_filters.py
```

### 步骤 7：更新文档

- `data-types.md` — 新增数据类型章节（schema / storage_rule / filter 支持 / 实测结果）
- `README.md` — schemas/ 目录下更新文件列表（如有新增）

### 检查清单

- [ ] Schema 文件放置到 `schemas/` 目录
- [ ] `_validate_schema` 验证通过（非法 schema 拒绝加载）
- [ ] 单元测试覆盖新类型（`get_write_paths` / `get_read_paths`）
- [ ] Path Filter 三种类型（单值/枚举/范围）测试通过
- [ ] Row Filter 三种类型（单值/枚举/范围）测试通过
- [ ] 组合 Filter 测试通过
- [ ] 数据完整性验证（写入-读取一致性）
- [ ] `data-types.md` 更新

详细说明和完整测试模板见 `data-types.md` 第八节。

## 后续开发

- [ ] API Handler（Flask Blueprint）
- [ ] RESTful API 文档
- [ ] Docker 部署配置
- [ ] 监控与告警