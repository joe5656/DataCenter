# DataCenter 设计计划文档

本文档根据 requirement.md 中的需求，详细分析每个需求的实现方法，并制定技术实施方案。

---

## 目录

1. [项目概述](#1-项目概述)
2. [REQ-001: Parquet 存储方案](#2-req-001-采用-parquet-进行基础数据存储)
3. [REQ-002: RESTful API 微服务架构](#3-req-002-微服务架构使用-restful-api-接口)
4. [REQ-003: 灵活数据类型支持](#4-req-003-存储数据类型灵活支持拓展)
5. [REQ-004: 依赖关系](#5-req-004-依赖关系)
6. [REQ-005: 配置管理](#6-req-005-配置管理)
7. [技术架构设计](#7-技术架构设计)
8. [实施计划](#8-实施计划)
9. [风险与注意事项](#9-风险与注意事项)

---

## 1. 项目概述

### 1.1 项目目标

DataCenter 是一个基于微服务架构的数据存储和检索系统，使用 Parquet 格式进行高效数据存储，通过 RESTful API 提供统一的数据访问接口。

### 1.2 技术栈

- **基础镜像**: 192.168.31.32:5001/restfulapi-interface (基于 baseos)
- **编程语言**: Python 3.12+
- **存储格式**: Apache Parquet
- **Web 框架**: Flask (通过 restfulapi-interface)
- **WSGI 服务器**: uWSGI
- **Web 服务器**: nginx

### 1.3 项目结构

```
DataCenter/
├── app/
│   ├── __init__.py
│   ├── config.py              # 配置管理
│   ├── schema_manager.py      # Schema 注册和管理
│   ├── storage_manager.py     # Parquet 存储管理
│   ├── index_manager.py       # 索引管理
│   └── handlers/             # API 处理器
│       ├── __init__.py
│       └── data_handler.py
├── schemas/                   # Schema 定义文件
│   └── stock_5min_v1.json
├── interfaces/               # RESTful API 接口定义
│   └── data_interface.yaml
├── data/                     # 数据存储目录
│   └── stock/
│       └── 5min/
├── tests/                    # 单元测试
├── Dockerfile                # Docker 构建文件
├── requirement.md           # 需求文档（不可修改）
├── design-plan.md           # 设计计划文档
└── README.md               # 项目说明
```

---

## 2. REQ-001: 采用 Parquet 进行基础数据存储

### 2.1 需求分析

**需求描述**:
- 采用 Parquet 作为基础数据存储格式
- 数据颗粒度根据具体存储的数据类型确定
- 不同数据类型的存储归类分开
- 不同数据类型需要建立数据 schema
- 数据读取和写入设计单独的 schema 模块保障数据格式正确性
- 设计索引模块，根据不同的数据类型创建不同的索引

### 2.2 技术选型

#### 2.2.1 Parquet 库选择

**推荐方案**: `pyarrow`

**理由**:
- Apache Arrow 项目的一部分，业界标准
- 性能优秀，支持列式存储
- 与 pandas 良好集成
- 支持 schema 验证
- 社区活跃，文档完善

**替代方案**: `fastparquet`（纯 Python 实现，性能略差）

#### 2.2.2 Schema 定义方式

**方案**: 使用 JSON 文件定义 schema

**示例** (`schemas/stock_5min_v1.json`):
```json
{
  "name": "stock_5min",
  "version": "v1",
  "fields": [
    {"name": "date", "type": "string", "required": true},
    {"name": "code", "type": "string", "required": true},
    {"name": "market", "type": "string", "required": true},
    {"name": "name", "type": "string", "required": true},
    {"name": "time", "type": "string", "required": true},
    {"name": "open", "type": "double", "required": true},
    {"name": "close", "type": "double", "required": true},
    {"name": "high", "type": "double", "required": true},
    {"name": "low", "type": "double", "required": true},
    {"name": "volume", "type": "long", "required": true}
  ],
  "partitioning": ["date", "market"]
}
```

### 2.3 数据颗粒度设计

#### 2.3.1 存储粒度决策

**问题**: 数据按什么粒度存储？

**方案对比**:

| 方案 | 优点 | 缺点 | 适用场景 |
|------|------|------|----------|
| 按天存储 (1 file/day) | 文件少，管理简单 | 单文件可能很大 | 数据量小 |
| 按周存储 (1 file/week) | 平衡文件和大小 | 时间范围查询需跨文件 | 中等数据量 |
| 按月存储 (1 file/month) | 文件最少 | 文件大，读写慢 | 不推荐 |
| 按数据量分片 (e.g., 100K rows/file) | 文件大小可控 | 文件多，管理复杂 | 大数据量 |

**推荐方案**: **按天存储 + 按市场规模自动分片**

- 默认按天存储：`data/stock_5min/5min/2026-05-17.parquet`
- 如果单日数据超过 100万条，自动分片：`2026-05-17_part001.parquet`
- 支持配置分片阈值

#### 2.3.2 不同数据类型的颗粒度

**股票 5分钟数据**:
- 颗粒度：按天
- 每只股票每天约 48 条数据 (4小时 × 12个5分钟)
- 3000 只股票每天约 144,000 条数据
- 单文件大小约 5-10 MB（可接受）

**其他数据类型**（未来扩展）:
- 分钟级数据：按天存储
- 日级数据：按月存储
- Tick 数据：按小时存储

### 2.4 存储归类设计

**重要设计变更（REQ-003 新增）**：

不同数据结构可以有不同的存储颗粒度。存储路径模板定义在 schema 的 `storage_rules.path_template` 字段中，IndexManager 根据该模板动态计算路径。

**存储路径原语**（可在 `path_template` 中使用）：

> **设计说明**：`path_template` 是**相对于 `Config.DATA_DIR`** 的路径模板，系统会自动拼接 `Config.DATA_DIR` 前缀，无需在模板中写 `{data_dir}`。

| 原语 | 含义 | 示例 |
|------|------|------|
| `{data_type}` | `schema["name"]` | `stock_5min` |
| `{granularity}` | `schema["granularity"]` | `5min` |
| `{year}` | `date[:4]` | `2026` |
| `{month}` | `date[5:7]` | `05` |
| `{date}` | 请求参数 `date` | `2026-05-17` |
| `{market}` | 请求参数 `market`（可选） | `XHKG` |
| `{code}` | 请求参数 `code`（可选） | `00700` |
| `{size:03d}` | 分片编号（3位零填充） | `001` |
| `{granularity}` | 存储颗粒度（来自 `granularity` 字段） | `5min`、`1day` |
| `{year}` | 年份 | `2026` |
| `{month}` | 月份 | `05` |
| `{date}` | 完整日期 | `2026-05-17` |
| `{market}` | 市场代码（可选） | `XHKG`、`XSHG` |
| `{code}` | 股票代码（可选，用于按股票分文件） | `00700` |
| `{size}` | 文件大小提示（用于分片） | `001`（分片编号） |

**示例 —— stock_5min 的 path_template**：
```
{data_dir}/{data_type}/{granularity}/```

**示例 —— stock_1day 的 path_template**（不同颗粒度，不同路径）：
```
{data_dir}/{data_type}/{granularity}/```

#### 2.4.1 目录结构（示例）

> 以下为 `stock_5min` 的默认路径结构，其他数据类型由各自 schema 的 `storage_rules` 决定。

```
data/
├── stock_5min/            # data_type = schema.name
│   └── 5min/            # granularity
│       └── 2026/
│           └── 05/
│               ├── 2026-05-17.parquet
│               └── 2026-05-18.parquet
├── stock_1day/           # 另一个 data_type
│   └── 1day/
│       └── 2026/
│           └── 05/
│               └── 2026-05-17.parquet
```

```
data/
├── stock/
│   ├── 5min/           # 股票5分钟数据
│   │   ├── 2026/
│   │   │   ├── 05/
│   │   │   │   ├── 2026-05-17.parquet
│   │   │   │   └── 2026-05-18.parquet
│   │   │   └── 06/
│   │   └── 2025/
│   ├── 1day/           # 股票日线数据
│   └── tick/           # Tick数据
├── index/
│   ├── constituents/    # 指数成分股
│   └── 5min/          # 指数5分钟数据
└── fund/
    └── 1day/          # 基金日线数据
```

**设计原则**:
- 一级目录：数据类型 (stock, index, fund)
- 二级目录：数据颗粒度 (5min, 1day, tick)
- 三级目录：按年月分层 (2026/05/)
- 文件：按日期命名 (2026-05-17.parquet)

#### 2.4.2 文件命名规范

**格式**: `{date}[_part{size:03d}].parquet`（由 schema `storage_rules.partition` 控制）

**分片触发条件**（满足任一即分片）：
- 文件行数超过 `storage_rules.partition.max_rows`
- 文件大小超过 `storage_rules.partition.max_size_mb` MB

**示例**:
- `2026-05-17.parquet` (默认，未触发分片)
- `2026-05-17_part001.parquet` (触发分片，第1片)
- `2026-05-17_part002.parquet` (触发分片，第2片)

**注意**：分片编号 `{size}` 在 `path_template` 中用 `{size:03d}` 表示（3位零填充）。

### 2.5 Schema 模块设计

#### 2.5.1 Schema 管理器 (`schema_manager.py`)

**职责**:
1. 加载和验证 schema 定义文件
2. 根据数据类型和版本获取 schema
3. 验证数据是否符合 schema
4. 支持 schema 版本管理

#### 2.5.1.1 Schema JSON 格式（含 `storage_rules`）

**文件命名**: `{name}_v{version}.json`（如 `stock_5min_v1.json`）

**完整格式示例**：
```json
{
  "name": "stock_5min",
  "version": "v1",
  "description": "股票5分钟K线数据",
  "granularity": "5min",
  "fields": [
    {"name": "date", "type": "string", "description": "交易日期"},
    {"name": "code", "type": "string", "description": "股票代码"},
    {"name": "market", "type": "string", "description": "市场"},
    {"name": "name", "type": "string", "description": "股票名称"},
    {"name": "time", "type": "string", "description": "时间HH:MM"},
    {"name": "open", "type": "double", "description": "开盘价"},
    {"name": "close", "type": "double", "description": "收盘价"},
    {"name": "high", "type": "double", "description": "最高价"},
    {"name": "low", "type": "double", "description": "最低价"},
    {"name": "volume", "type": "int64", "description": "成交量"}
  ],
  "storage_rules": {
    "path_template": "{data_type}/{granularity}/{year}/{month}/{date}.parquet",
    "partition": {
      "by": "date",
      "max_rows": 1000000,
      "max_size_mb": 100
    }
  }
}
```

**字段说明**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ✅ | 数据类型名称，**用于 API 路径**（如 `stock_5min`） |
| `version` | string | ✅ | 版本号（如 `v1`） |
| `description` | string | ❌ | 描述信息 |
| `granularity` | string | ✅ | 存储颗粒度（如 `5min`、`1day`） |
| `fields` | array | ✅ | 字段定义（name/type/description） |
| `storage_rules` | object | ✅ | 存储规则（见下表） |

**`storage_rules` 字段说明**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `path_template` | string | ✅ | 路径模板，支持原语 `{data_dir}` `{data_type}` `{granularity}` `{year}` `{month}` `{date}` `{market}` `{code}` |
| `partition.by` | string | ✅ | 分片依据（`date`=按天，`code`=按股票） |
| `partition.max_rows` | int | ✅ | 单文件最大行数 |
| `partition.max_size_mb` | int | ✅ | 单文件最大大小（MB） |

**不同数据类型的 `path_template` 可以不同**：

| 数据类型 | `path_template` |
|----------|-------------|
| `stock_5min` | `{data_type}/{granularity}/{year}/{month}/{date}.parquet` |
| `stock_1day` | `{data_type}/{granularity}/{year}/{month}/{date}.parquet` |
| `index_weight` | `{data_dir}/{data_type}/{year}/{month}/{date}.parquet` |

---

**核心接口**:
```python
class SchemaManager:
    def __init__(self, schemas_dir: str):
        """初始化 Schema 管理器"""
        
    def load_schema(self, data_type: str, version: str) -> dict:
        """加载指定数据类型和版本的 schema"""
        
    def validate_data(self, data: pd.DataFrame, data_type: str, version: str) -> bool:
        """验证数据是否符合 schema"""
        
    def get_parquet_schema(self, data_type: str, version: str) -> pa.Schema:
        """获取 PyArrow Schema 对象"""
        
    def list_schemas(self) -> List[dict]:
        """列出所有可用的 schema"""
    def get_storage_rules(self, data_type: str, version: str) -> dict:
        """获取 storage_rules（供 IndexManager 使用）"""
```

#### 2.5.2 Schema 加载流程

**重要说明**：数据类型不支持动态扩展，新增数据类型需要通过版本升级实现。

**步骤**:
1. 在 `schemas/` 目录创建 JSON 定义文件（如 `stock_5min_v1.json`）
2. SchemaManager 启动时加载所有 schema（启动时确定，运行时不可变）
3. 数据写入前验证 schema
4. 数据读取时应用 schema

**新增数据类型的流程**（版本升级）：
1. 创建新的 schema JSON 文件
2. 如需自定义处理逻辑，修改代码
3. 更新 VERSION 文件
4. 构建并发布新版本 Docker 镜像
5. 重新部署服务

### 2.6 索引模块设计（已调整）

#### 2.6.1 设计调整说明

**重要变更**：索引模块不存储任何数据，只负责路径计算。

**新职责**：
1. 收到数据读请求时，根据数据类型和请求参数决定数据路径
2. 收到数据写请求时，决定数据存储的路径
3. 不存储任何元数据（无 index.json 或数据库）

**设计理由**：
- 简化架构，索引模块变成纯计算模块
- 元数据存储在 Parquet 文件内部（自带 schema）
- 提高性能，避免额外的 I/O 操作

#### 2.6.2 索引管理器 (`index_manager.py`)

**职责**：
1. 根据数据类型、日期、市场等参数计算文件路径
2. 支持路径模式匹配（查找多个文件）
3. 管理目录结构规范

**核心接口**：
```python
class IndexManager:
    def __init__(self, schema_manager: SchemaManager):
        """初始化索引管理器（依赖 SchemaManager）"""
        self.schema_manager = schema_manager
        
    def get_write_path(self, data_type: str, version: str,
                        date: str, market: str = None,
                        code: str = None) -> str:
        """获取数据写入路径（渲染 path_template）"""
        # 1. 从 schema 获取 storage_rules
        # 2. 渲染 path_template
        # 3. 返回完整路径
        # 示例返回: data/stock_5min/5min/2026/05/2026-05-17.parquet
        
    def get_read_paths(self, data_type: str, version: str,
                       start_date: str, end_date: str,
                       market: str = None) -> List[str]:
        """获取数据读取路径（可能多个文件）"""
        # 1. 从 schema 获取 storage_rules.path_template
        # 2. 根据 date 范围渲染多个路径
        # 3. 返回路径列表
        # 示例返回: [
        #   "data/stock_5min/5min/2026/05/2026-05-17.parquet",
        #   "data/stock_5min/5min/2026/05/2026-05-18.parquet"
        # ]
        
    def get_partition_paths(self, data_type: str, version: str,
                           date: str, data: pd.DataFrame = None) -> List[str]:
        """获取分片路径（用于分片写入）"""
        # 1. 从 schema 获取 storage_rules.partition
        # 2. 如果 data 行数超过 max_rows 或大小超过 max_size_mb，计算分片路径
        # 3. 替换 {size:03d} 为分片编号
        # 示例: [
        #   "data/stock_5min/5min/2026/05/2026-05-17_part001.parquet",
        #   "data/stock_5min/5min/2026/05/2026-05-17_part002.parquet"
        # ]
        
```

#### 2.6.3 路径计算规则

**路径格式**：由 schema `storage_rules.path_template` 定义（支持原语替换）

**原语替换规则**：

> **说明**：`IndexManager` 渲染路径时自动拼接 `Config.DATA_DIR` 前缀。

| 原语 | 替换为 | 示例 |
|------|--------|------|
| `{data_type}` | `schema["name"]` | `stock_5min` |
| `{granularity}` | `schema["granularity"]` | `5min` |
| `{year}` | `date[:4]` | `2026` |
| `{month}` | `date[5:7]` | `05` |
| `{date}` | 请求参数 `date` | `2026-05-17` |
| `{market}` | 请求参数 `market`（可选） | `XHKG` |
| `{code}` | 请求参数 `code`（可选） | `00700` |
| `{size:03d}` | 分片编号（3位零填充） | `001` |
| `{granularity}` | `schema["granularity"]` | `5min` |
| `{year}` | `date[:4]` | `2026` |
| `{month}` | `date[5:7]` | `05` |
| `{date}` | 请求参数 `date` | `2026-05-17` |
| `{market}` | 请求参数 `market`（可选） | `XHKG` |
| `{code}` | 请求参数 `code`（可选） | `00700` |
| `{size:03d}` | 分片编号（3位零填充） | `001` |

**示例（`stock_5min`）**：

`path_template` = `{data_type}/{granularity}/{year}/{month}/{date}.parquet`

渲染结果：
```
# Config.DATA_DIR = "./data"
# 渲染结果（系统自动拼接 data_dir）:
./data/stock_5min/5min/2026/05/2026-05-17.parquet
```

**分片规则**（由 `storage_rules.partition` 控制）：
- 触发条件：`data.rows > max_rows` 或 `file_size > max_size_mb`
- 分片格式：`{date}_part{size:03d}.parquet`
- 示例：`2026-05-17_part001.parquet`、`2026-05-17_part002.parquet`

### 2.7 数据处理模块设计（新增）

#### 2.7.1 设计目标

**新增模块**：`data_processor.py`

**职责**：
1. 负责数据的读写请求
2. 读取时：直接读出数据
3. 写入时：
   - 按照 schema 进行数据格式验证
   - 重复验证（可选）
   - 根据索引模块的路径存储数据

**与索引模块的关系**：
- 数据处理模块调用索引模块获取路径
- 索引模块只返回路径，不存储任何数据

#### 2.7.2 数据处理器 (`data_processor.py`)

**职责**：
1. 接收读写请求
2. 调用 SchemaManager 进行数据验证
3. 调用 IndexManager 获取路径
4. 调用 ParquetReader/Writer 进行实际 I/O

**核心接口**：
```python
class DataProcessor:
    def __init__(self, schema_manager: SchemaManager,
                 index_manager: IndexManager):
        """初始化数据处理器"""
        self.schema_manager = schema_manager
        self.index_manager = index_manager
        
    def write_data(self, data: pd.DataFrame, data_type: str,
                   granularity: str, date: str,
                   schema_version: str = 'v1',
                   mode: str = 'append') -> dict:
        """写入数据"""
        # 1. Schema 验证
        # 2. 重复验证（如果 mode='append'）
        # 3. 调用 index_manager.get_write_path() 获取路径
        # 4. 写入 Parquet 文件
        # 5. 返回写入结果
        
    def read_data(self, data_type: str, granularity: str,
                  start_date: str, end_date: str,
                  market: str = None, codes: List[str] = None,
                  schema_version: str = None) -> pd.DataFrame:
        """读取数据"""
        # 1. 调用 index_manager.get_read_paths() 获取文件路径列表
        # 2. 逐个读取 Parquet 文件
        # 3. 合并 DataFrame
        # 4. 过滤（market, codes）
        # 5. 返回 DataFrame
        
    def validate_schema(self, data: pd.DataFrame, data_type: str,
                        version: str) -> tuple[bool, List[str]]:
        """验证数据是否符合 schema"""
        # 返回 (是否通过, 错误列表)
        
    def check_duplicates(self, data: pd.DataFrame, data_type: str,
                        granularity: str, date: str) -> pd.DataFrame:
        """检查重复数据"""
        # 读取已有数据
        # 找出重复的行（基于主键：date + code + time）
        # 返回重复数据 DataFrame
        
    def remove_duplicates(self, data: pd.DataFrame, data_type: str,
                         granularity: str, date: str) -> pd.DataFrame:
        """移除重复数据"""
        # 调用 check_duplicates
        # 移除重复行
        # 返回去重后的 DataFrame
```

#### 2.7.3 数据验证流程

**写入数据时的验证步骤**：

1. **Schema 验证**：
   - 检查所有必需字段是否存在
   - 检查字段类型是否正确
   - 检查字段值是否在枚举范围内（如果有）
   
2. **重复验证**（可选，由参数控制）：
   - 读取目标文件的已有数据
   - 检查新数据是否与已有数据重复（基于主键）
   - 如果重复：报错 或 自动去重（由参数控制）
   
3. **数据清洗**（可选）：
   - 去除空值
   - 格式化日期/时间
   - 统一代码格式（如：700 → 0700）

**验证示例**：
```python
# 写入数据
processor = DataProcessor(schema_mgr, index_mgr)

result = processor.write_data(
    data=df,
    data_type='stock',
    granularity='5min',
    date='2026-05-17',
    schema_version='v1',
    mode='append',  # 'append' 或 'overwrite'
    validate_schema=True,
    check_duplicates=True,
    remove_duplicates=False  # True: 自动去重；False: 报错
)

# 返回结果
# {
#   "success": True,
#   "rows_written": 48,
#   "file_path": "data/stock_5min/5min/2026/05/2026-05-17.parquet",
#   "duplicates_found": 2,
#   "duplicates_removed": 0
# }
```

#### 2.7.4 读取数据流程

**读取数据时的处理步骤**：

1. **获取文件路径**：调用 `index_manager.get_read_paths()`
2. **逐个读取**：读取所有符合条件的 Parquet 文件
3. **合并数据**：将多个 DataFrame 合并为一个
4. **过滤数据**（可选）：
   - 按市场过滤（market 参数）
   - 按股票代码过滤（codes 参数）
   - 按日期范围过滤（已经在路径计算时完成）
5. **返回结果**：返回 DataFrame

**读取示例**：
```python
# 读取数据
df = processor.read_data(
    data_type='stock',
    granularity='5min',
    start_date='2026-05-17',
    end_date='2026-05-18',
    market='XHKG',
    codes=['00700', '00701']
)

# 返回 DataFrame
#       date   code market   name   time   open  close  high   low    volume
# 0  2026-05-17  00700  XHKG  腾讯控股  09:30  380.0  381.0  381.5  379.5  120000
# 1  2026-05-17  00700  XHKG  腾讯控股  09:35  381.0  382.0  382.5  380.5  115000
# ...
```

### 2.8 存储管理器设计（简化）

#### 2.8.1 存储管理器 (`storage_manager.py`)

**职责**（已简化）：
1. 封装 Parquet 读写操作（底层 I/O）
2. 不负责路径计算（由 IndexManager 负责）
3. 不负责数据验证（由 DataProcessor 负责）

**核心接口**：
```python
class StorageManager:
    def __init__(self, compression: str = 'SNAPPY'):
        """初始化存储管理器"""
        self.compression = compression

    # ---------- 文件锁机制（进程安全，REQ-001）----------
    def _get_lock_path(self, file_path: str) -> str:
        """返回对应的锁文件路径（与数据文件同目录，.lock 后缀）"""
        return file_path + '.lock'

    def _acquire_write_lock(self, file_path: str):
        """获取写锁（排他锁 LOCK_EX），阻塞直到获取成功
        返回锁文件 fd，调用方需在 finally 中调用 _release_lock(fd)
        """
        import fcntl, os
        lock_path = self._get_lock_path(file_path)
        lock_fd = open(lock_path, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        return lock_fd

    def _acquire_read_lock(self, file_path: str):
        """获取读锁（共享锁 LOCK_SH），如有写锁则阻塞等待
        返回锁文件 fd，调用方需在 finally 中调用 _release_lock(fd)
        """
        import fcntl, os
        lock_path = self._get_lock_path(file_path)
        if not os.path.exists(lock_path):
            open(lock_path, 'w').close()
        lock_fd = open(lock_path, 'r')
        fcntl.flock(lock_fd, fcntl.LOCK_SH)
        return lock_fd

    def _release_lock(self, lock_fd):
        """释放锁（LOCK_UN）并关闭 fd"""
        import fcntl
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

    # ---------- 读写删接口（含锁）----------
    def write_parquet(self, data: pd.DataFrame, file_path: str,
                      schema: pa.Schema = None, mode: str = 'append') -> str:
        """写入 Parquet 文件（内含写锁）"""
        lock_fd = None
        try:
            lock_fd = self._acquire_write_lock(file_path)
            # ... 原有写入逻辑（append/overwrite）...
        finally:
            if lock_fd:
                self._release_lock(lock_fd)

    def read_parquet(self, file_paths: List[str],
                     columns: List[str] = None) -> pd.DataFrame:
        """读取 Parquet 文件（内含读锁）"""
        lock_fds = []
        try:
            for fp in file_paths:
                if os.path.exists(fp):
                    lock_fds.append(self._acquire_read_lock(fp))
            # ... 原有读取逻辑 ...
        finally:
            for fd in lock_fds:
                self._release_lock(fd)

    def delete_parquet(self, file_path: str) -> bool:
        """删除 Parquet 文件（内含写锁）"""
        lock_fd = None
        try:
            lock_fd = self._acquire_write_lock(file_path)
            result = os.remove(file_path)
            lock_path = self._get_lock_path(file_path)
            if os.path.exists(lock_path):
                os.remove(lock_path)
            return result
        finally:
            if lock_fd:
                self._release_lock(lock_fd)

    def file_exists(self, file_path: str) -> bool:
        """检查文件是否存在（无需加锁，只检查路径）"""
        return os.path.exists(file_path)

    def get_file_metadata(self, file_path: str) -> dict:
        """获取文件元数据（内含读锁）"""
        lock_fd = None
        try:
            if os.path.exists(file_path):
                lock_fd = self._acquire_read_lock(file_path)
            # ... 获取行数、文件大小 ...
        finally:
            if lock_fd:
                self._release_lock(lock_fd)
```

#### 2.8.2 进程安全设计（文件锁机制）

**需求来源**：REQ-001 新增 — 数据存储进程安全

**设计要求**：
1. 同时只能有一个写入操作（写锁排他）
2. 文件被写入时，阻塞读取（写锁期间读锁等待）
3. 多个读取可以并发（读锁共享）
4. 访问文件时必须获得读取锁或写入锁

**实现方案**：使用 `fcntl.flock` 文件级建议锁（Linux/macOS 通用）

| 操作 | 锁类型 | 行为 |
|------|--------|------|
| 写入 / 删除 | 排他锁 `LOCK_EX` | 阻塞直到获取，期间其他进程无法读或写 |
| 读取 | 共享锁 `LOCK_SH` | 可多个并发，但需等待写锁释放 |
| 释放 | `LOCK_UN` | 释放锁，唤醒等待进程 |

**锁文件规则**：
- 每个数据文件对应一个锁文件：`<data_file>.lock`
- 锁文件与数据文件同目录，可随数据文件一起删除
- `fcntl.flock` 是建议锁，所有访问方都需遵守锁协议

**注意事项**：
- Windows 不支持 `fcntl`，跨平台可用 `portalocker` 库（可选依赖）
- 同一进程内多线程并发，需用 `threading.Lock` 额外保护（可选）

#### 2.8.3 存储管理器实施步骤

**步骤 1: 实现存储管理器基础框架** (`storage_manager.py`)
1. 实现 `__init__` 方法（初始化压缩算法）
2. 实现 `write_parquet` 方法（写入 Parquet 文件，支持 append/overwrite 模式）
3. 实现 `read_parquet` 方法（读取 Parquet 文件，支持多文件、列过滤）
4. 实现 `delete_parquet` 方法（删除 Parquet 文件）
5. 实现 `file_exists` 方法（检查文件是否存在，无需加锁）
6. 实现 `get_file_metadata` 方法（获取文件元数据，含读锁）

**步骤 2: 实现文件锁机制**
1. 实现 `_get_lock_path` 方法（生成 `.lock` 文件路径）
2. 实现 `_acquire_write_lock` 方法（获取排他写锁，阻塞）
3. 实现 `_acquire_read_lock` 方法（获取共享读锁，等待写锁释放）
4. 实现 `_release_lock` 方法（释放锁并关闭 fd）
5. 在 `write_parquet`/`read_parquet`/`delete_parquet`/`get_file_metadata` 中集成锁机制

**步骤 3: 编写单元测试** (`test_storage_manager.py`)
1. 测试写入和读取（含 schema 验证）
2. 测试追加模式（append）
3. 测试覆盖模式（overwrite）
4. 测试删除功能
5. 测试元数据获取
6. 测试锁机制（模拟多进程访问，验证写锁排他、读锁共享）

---

### 2.9 项目级实施步骤

**阶段 1: 基础框架搭建**
1. 创建项目结构
2. 实现 SchemaManager
3. 实现 IndexManager
4. 实现 StorageManager（含文件锁机制）

**阶段 2: 功能完善**
1. 支持数据分区和分片
2. 实现 schema 验证
3. 添加数据压缩
4. 性能优化

**阶段 3: 高级功能**
1. 索引迁移到 SQLite
2. 支持数据版本管理
3. 添加数据备份和恢复
4. 监控和告警

---

## 3. REQ-002: 微服务架构，使用 RESTful API 接口

### 3.1 需求分析

**需求描述**:
- 微服务架构，使用 RESTful API 接口进行数据存储和提取
- 集成 restful-interface
- 按照 **`schema.name`** 定义 API 的结构和操作（如 `stock_5min`）
- 建立 RESTful API 文档，定义 API
- 按照 restful 基础镜像的要求实现 interface 和 handler

### 3.2 技术架构

#### 3.2.1 基于 restfulapi-interface

**基础镜像**: `192.168.31.32:5001/restfulapi-interface:latest`

**架构层次**:
```
Client → nginx → uWSGI → Flask App → Storage Manager
                ↓
          Schema Manager
                ↓
          Index Manager
                ↓
          Parquet Files
```

#### 3.2.2 应用结构

**遵循 restfulapi-interface 规范**:
```
app/
├── __init__.py
├── config.py          # 配置管理
├── loader.py         # DynamicLoader (从 restfulapi-interface 继承)
├── handlers/         # 业务处理器
│   ├── __init__.py
│   └── data_handler.py
└── interfaces/       # API 接口定义
    └── data_interface.yaml
```

### 3.3 API 设计（已更新）

#### 3.3.0 配置开关

**设计原则**：修改(PUT)和删除(DELETE)操作通过配置开关控制是否允许。

**配置项** (`app/config.py`):
```python
class Config:
    # 是否允许修改数据（PUT 操作）
    ALLOW_PUT = False  # 默认关闭

    # 是否允许删除数据（DELETE 操作）
    ALLOW_DELETE = False  # 默认关闭

    # 也可通过环境变量覆盖
    # DATACENTER_ALLOW_PUT=true
    # DATACENTER_ALLOW_DELETE=false
```

**开关行为**:
- 开关关闭时，对应端点返回 `405 Method Not Allowed`
- 响应体：`{"success": false, "error": "PUT operation is disabled by configuration"}`
- 开关可通过环境变量运行时覆盖，无需重新部署

#### 3.3.1 RESTful API 端点设计（已更新）

**资源**: `data/{data_type}`

**设计说明**：API 路径中体现数据类型，不再通过请求体传递。

**端点列表**:

| HTTP 方法 | 端点 | 功能 | 请求体 | 响应 | 开关控制 |
|-----------|------|------|--------|------|----------|
| POST    | `/api/v1/data/{data_type}` | 写入数据，`data_type`=schema.name（如 `stock_5min`） | JSON | 写入结果 | - |
| GET     | `/api/v1/data/{data_type}` | 查询数据，`data_type`=schema.name（如 `stock_5min`） | Query 参数 | JSON | - |
| PUT     | `/api/v1/data/{data_type}` | 更新数据，`data_type`=schema.name | JSON | 更新结果 | ALLOW_PUT |
| DELETE  | `/api/v1/data/{data_type}` | 删除数据，`data_type`=schema.name | Query 参数 | 删除结果 | ALLOW_DELETE |
| GET     | `/api/v1/data/{data_type}/schemas` | 列出 schema，`data_type`=schema.name | - | JSON | - |
| GET     | `/api/v1/data/{data_type}/stats` | 存储统计，`data_type`=schema.name | - | JSON | - |

#### 3.3.2 API 详细说明

**1. 写入数据**

```
POST /api/v1/data/stock_5min
Content-Type: application/json

{
  "granularity": "5min",
  "date": "2026-05-17",
  "schema": "stock_5min_v1",
  "data": [
    {
      "date": "2026-05-17",
      "code": "00700",
      "market": "XHKG",
      "name": "腾讯控股",
      "time": "09:30",
      "open": 380.0,
      "close": 381.0,
      "high": 381.5,
      "low": 379.5,
      "volume": 120000
    }
  ]
}
```

> **变更说明**：data_type 从请求体移到 URL 路径中（`/api/v1/data/stock`）

**响应**:
```json
{
  "success": true,
  "message": "Data written successfully",
  "details": {
    "data_type": "stock_5min",
    "rows_written": 1,
    "file_path": "data/stock_5min/5min/2026/05/2026-05-17.parquet",
    "schema": "stock_5min_v1"
  }
}
```

**2. 查询数据**

```
GET /api/v1/data/stock_5min?granularity=5min&start_date=2026-05-17&end_date=2026-05-18&market=XHKG&codes=00700,00701
```

> **变更说明**：data_type 从 Query 参数移到 URL 路径中

**响应**:
```json
{
  "success": true,
  "data": [...],
  "metadata": {
    "data_type": "stock_5min",
    "total_rows": 96,
    "files_read": 2,
    "schema": "stock_5min_v1"
  }
}
```

**3. 更新数据**（受 ALLOW_PUT 开关控制）

```
PUT /api/v1/data/stock_5min
Content-Type: application/json

{
  "granularity": "5min",
  "date": "2026-05-17",
  "data": [...]
}
```

**开关关闭时响应**:
```json
{
  "success": false,
  "error": "PUT operation is disabled by configuration"
}
HTTP 405
```

**4. 删除数据**（受 ALLOW_DELETE 开关控制）

```
DELETE /api/v1/data/stock_5min?granularity=5min&start_date=2026-05-17&end_date=2026-05-17
```

**开关关闭时响应**:
```json
{
  "success": false,
  "error": "DELETE operation is disabled by configuration"
}
HTTP 405
```

**5. 列出 schema**

```
GET /api/v1/data/stock/schemas
```

**响应**:
```json
{
  "success": true,
  "data_type": "stock_5min",
  "schemas": [
    {
      "name": "stock_5min",
      "version": "v1",
      "fields": [...]
    }
  ]
}
```

**6. 存储统计**

```
GET /api/v1/data/stock/stats
```

### 3.4 Interface 定义（已更新）

#### 3.4.1 创建 interface 文件

**文件**: `interfaces/data_interface.yaml`

```yaml
api_version: v1
endpoints:
  - path: /api/v1/data/<data_type>
    methods: [POST, GET]
    handler: data_handler.DataHandler
    description: "数据写入和查询接口"

  - path: /api/v1/data/<data_type>
    methods: [PUT, DELETE]
    handler: data_handler.DataHandler
    config_gate:
      PUT: ALLOW_PUT
      DELETE: ALLOW_DELETE
    description: "数据修改和删除接口（受配置开关控制）"

  - path: /api/v1/data/<data_type>/schemas
    methods: [GET]
    handler: data_handler.SchemaHandler
    description: "Schema 查询接口"

  - path: /api/v1/data/<data_type>/stats
    methods: [GET]
    handler: data_handler.StatsHandler
    description: "存储统计接口"
```

### 3.5 Handler 实现（已更新）

#### 3.5.1 数据处理器 (`handlers/data_handler.py`)

```python
from flask import request, jsonify
import pandas as pd
from app.data_processor import DataProcessor
from app.schema_manager import SchemaManager
from app.config import Config

class DataHandler:
    def __init__(self, data_processor: DataProcessor,
                 schema_manager: SchemaManager,
                 config: Config):
        self.data_processor = data_processor
        self.schema_manager = schema_manager
        self.config = config

    def post(self, data_type: str):
        """写入数据"""
        try:
            payload = request.json
            granularity = payload['granularity']
            date = payload['date']
            data = payload['data']

            df = pd.DataFrame(data)

            result = self.data_processor.write_data(
                df, data_type, granularity, date
            )

            return jsonify({
                "success": True,
                "message": "Data written successfully",
                "details": {
                    "data_type": data_type,
                    "rows_written": result['rows_written'],
                    "file_path": result['file_path']
                }
            }), 200

        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 400

    def get(self, data_type: str):
        """查询数据"""
        try:
            granularity = request.args.get('granularity')
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            market = request.args.get('market')
            codes = request.args.get('codes', '').split(',') if request.args.get('codes') else None

            df = self.data_processor.read_data(
                data_type, granularity,
                start_date, end_date, market, codes
            )

            return jsonify({
                "success": True,
                "data": df.to_dict('records'),
                "metadata": {
                    "data_type": data_type,
                    "total_rows": len(df)
                }
            }), 200

        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 400

    def put(self, data_type: str):
        """更新数据（受 ALLOW_PUT 开关控制）"""
        if not self.config.ALLOW_PUT:
            return jsonify({
                "success": False,
                "error": "PUT operation is disabled by configuration"
            }), 405

        try:
            payload = request.json
            granularity = payload['granularity']
            date = payload['date']
            data = payload['data']

            df = pd.DataFrame(data)
            result = self.data_processor.write_data(
                df, data_type, granularity, date, mode='overwrite'
            )

            return jsonify({
                "success": True,
                "message": "Data updated successfully",
                "details": {
                    "data_type": data_type,
                    "rows_written": result['rows_written'],
                    "file_path": result['file_path']
                }
            }), 200

        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 400

    def delete(self, data_type: str):
        """删除数据（受 ALLOW_DELETE 开关控制）"""
        if not self.config.ALLOW_DELETE:
            return jsonify({
                "success": False,
                "error": "DELETE operation is disabled by configuration"
            }), 405

        try:
            granularity = request.args.get('granularity')
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')

            result = self.data_processor.delete_data(
                data_type, granularity, start_date, end_date
            )

            return jsonify({
                "success": True,
                "message": "Data deleted successfully",
                "details": {
                    "data_type": data_type,
                    "files_deleted": result['files_deleted']
                }
            }), 200

        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 400
```

### 3.6 API 文档

#### 3.6.1 文档格式

**工具选择**: OpenAPI 3.0 (Swagger)

**文档生成方式**:
1. 手动编写 OpenAPI spec (`docs/api.yaml`)
2. 使用 Flask-RESTX 自动生成（推荐）
3. 使用 Flask-OpenAPI 自动生成

**推荐方案**: 手动编写 + 代码注释

**文档文件**: `docs/api.yaml`

```yaml
openapi: 3.0.0
info:
  title: DataCenter API
  version: 1.0.0
  description: DataCenter RESTful API for data storage and retrieval
  
paths:
  /api/v1/data:
    post:
      summary: Write data
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                data_type:
                  type: string
                granularity:
                  type: string
                date:
                  type: string
                data:
                  type: array
      responses:
        200:
          description: Success
        400:
          description: Bad Request
```

### 3.7 实施步骤

**阶段 1: 基础集成**
1. 创建 Flask 应用，集成 restfulapi-interface
2. 实现基础的 handler 和 interface
3. 测试 API 端点

**阶段 2: 功能完善**
1. 完善数据写入和查询逻辑
2. 添加 schema 验证
3. 实现错误处理

**阶段 3: 文档和测试**
1. 编写 API 文档
2. 添加单元测试
3. 性能测试

---

## 4. REQ-003: 存储数据类型灵活，支持拓展

### 4.1 需求分析

**需求描述**:
- 存储数据类型灵活，支持拓展
- 不同数据类型注册不同 schema
- 不同版本的 schema 可以不同
- 当前支持的数据类型：股票数据的 5min 数据

**字段**: 日期、股票代码、市场、股票名称、时间、开盘、收盘、最高、最低、成交量

**重要说明**：「灵活」的含义是 schema 支持多版本（v1/v2），数据类型列表在版本发布时确定。
新增数据类型需要修改代码 + 发布新版本，不支持运行时动态注册。

### 4.2 Schema 加载机制（非动态注册）

#### 4.2.1 Schema 加载流程

**步骤**:
1. 定义 schema JSON 文件
2. 放置到 `schemas/` 目录
3. 服务启动时一次性加载
4. Schema 注册到 SchemaManager（运行时不可变）
5. API 支持已注册的数据类型

**示例**: 注册股票 5分钟数据 schema

**文件**: `schemas/stock_5min_v1.json`

```json
{
  "name": "stock_5min",
  "version": "v1",
  "description": "股票5分钟数据",
  "fields": [
    {
      "name": "date",
      "type": "string",
      "required": true,
      "description": "日期 (YYYY-MM-DD)",
      "example": "2026-05-17"
    },
    {
      "name": "code",
      "type": "string",
      "required": true,
      "description": "股票代码 (4位，含前导零)",
      "example": "00700"
    },
    {
      "name": "market",
      "type": "string",
      "required": true,
      "description": "市场代码",
      "enum": ["XHKG", "XSHG", "XSHE"],
      "example": "XHKG"
    },
    {
      "name": "name",
      "type": "string",
      "required": true,
      "description": "股票名称",
      "example": "腾讯控股"
    },
    {
      "name": "time",
      "type": "string",
      "required": true,
      "description": "时间 (HH:MM)",
      "example": "09:30"
    },
    {
      "name": "open",
      "type": "double",
      "required": true,
      "description": "开盘价",
      "example": 380.0
    },
    {
      "name": "close",
      "type": "double",
      "required": true,
      "description": "收盘价",
      "example": 381.0
    },
    {
      "name": "high",
      "type": "double",
      "required": true,
      "description": "最高价",
      "example": 381.5
    },
    {
      "name": "low",
      "type": "double",
      "required": true,
      "description": "最低价",
      "example": 379.5
    },
    {
      "name": "volume",
      "type": "long",
      "required": true,
      "description": "成交量",
      "example": 120000
    }
  ],
  "partitioning": ["date", "market"],
  "compression": "SNAPPY"
}
```

#### 4.2.2 Schema 版本管理

**场景**: Schema 演进

**示例**: 股票 5分钟数据 v2（添加成交额字段）

**文件**: `schemas/stock_5min_v2.json`

```json
{
  "name": "stock_5min",
  "version": "v2",
  "description": "股票5分钟数据 v2（添加成交额）",
  "fields": [
    // ... v1 的所有字段 ...
    {
      "name": "amount",
      "type": "double",
      "required": false,
      "description": "成交额（可选）",
      "example": 45600000.0
    }
  ],
  "partitioning": ["date", "market"],
  "compression": "SNAPPY",
  "compatible_with": ["v1"]
}
```

**版本兼容性**:
- `compatible_with`: 声明向前兼容的版本
- 读取时自动处理缺失字段
- 写入时可选版本

### 4.3 数据类型扩展

#### 4.3.1 添加新数据类型

**场景**: 添加股票日线数据

**步骤**:
1. 创建 schema 文件 (`schemas/stock_1day_v1.json`)
2. SchemaManager 自动加载
3. API 自动支持新数据类型
4. 无需修改代码

**示例**: 股票日线数据 schema

**文件**: `schemas/stock_1day_v1.json`

```json
{
  "name": "stock_1day",
  "version": "v1",
  "description": "股票日线数据",
  "fields": [
    {"name": "date", "type": "string", "required": true},
    {"name": "code", "type": "string", "required": true},
    {"name": "market", "type": "string", "required": true},
    {"name": "name", "type": "string", "required": true},
    {"name": "open", "type": "double", "required": true},
    {"name": "close", "type": "double", "required": true},
    {"name": "high", "type": "double", "required": true},
    {"name": "low", "type": "double", "required": true},
    {"name": "volume", "type": "long", "required": true},
    {"name": "turnover", "type": "double", "required": false}
  ],
  "partitioning": ["date", "market"],
  "compression": "SNAPPY"
}
```

#### 4.3.2 Schema 加载机制

**SchemaManager 加载逻辑**（启动时一次性加载，运行时不可变）：
```python
def load_all_schemas(self):
    """启动时加载所有 schema 文件（一次性加载，运行时不可变）"""
    schema_files = glob.glob(os.path.join(self.schemas_dir, "*.json"))

    for file_path in schema_files:
        with open(file_path, 'r') as f:
            schema_def = json.load(f)

        data_type = schema_def['name']
        version = schema_def['version']

        # 注册 schema
        self.schemas[(data_type, version)] = schema_def

        # 建立最新版本索引
        if data_type not in self.latest_versions:
            self.latest_versions[data_type] = version

# 注意：不提供 add_schema() / remove_schema() 等运行时修改方法
```

### 4.4 实施步骤

**阶段 1: Schema 基础**
1. 设计 schema JSON 格式
2. 实现 SchemaManager 加载逻辑
3. 注册股票 5分钟数据 schema

**阶段 2: 版本管理**
1. 支持多版本 schema
2. 实现版本兼容性检查
3. 测试版本演进场景

**阶段 3: 类型扩展**（通过版本升级）
1. 添加新数据类型时，修改代码 + schema
2. 更新 VERSION
3. 构建并发布新版本

---

## 5. REQ-004: 依赖关系

### 5.1 需求分析

**需求描述**:
- 集成 `192.168.31.32:5001/restfulapi-interface` 项目
- 以 `baseos` 项目为基础镜像

### 5.2 依赖关系图

```
baseos (Ubuntu 24.04 + Python 3.12)
  ↓
restfulapi-interface (Flask + uWSGI + nginx)
  ↓
DataCenter (Parquet + Schema + Index)
```

### 5.3 Dockerfile 设计

#### 5.3.1 Dockerfile

```dockerfile
# 基于 restfulapi-interface
FROM 192.168.31.32:5001/restfulapi-interface:latest

# 设置工作目录
WORKDIR /app

# 复制应用代码
COPY app/ /app/app/
COPY schemas/ /app/schemas/
COPY interfaces/ /app/interfaces/
COPY requirements.txt /app/

# 安装 Python 依赖
RUN pip3 install --break-system-packages -r requirements.txt

# 创建数据目录
RUN mkdir -p /app/data

# 设置环境变量
ENV DATA_DIR=/app/data
ENV SCHEMAS_DIR=/app/schemas
ENV INTERFACES_DIR=/app/interfaces

# 暴露端口（继承 restfulapi-interface）
# 80 (nginx)
# 8080 (uWSGI)

# 启动命令（继承 restfulapi-interface）
# CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
```

### 5.4 集成 restfulapi-interface

#### 5.4.1 应用工厂模式

**文件**: `app/__init__.py`

```python
from flask import Flask
from app.config import Config
from app.schema_manager import SchemaManager
from app.storage_manager import StorageManager
from app.index_manager import IndexManager

def create_app(config=None):
    """应用工厂"""
    app = Flask(__name__)
    
    # 加载配置
    app.config.from_object(Config())
    if config:
        app.config.update(config)
    
    # 初始化管理器
    schema_manager = SchemaManager(app.config['SCHEMAS_DIR'])
    index_manager = IndexManager(app.config['DATA_DIR'])
    storage_manager = StorageManager(
        app.config['DATA_DIR'],
        schema_manager,
        index_manager
    )
    
    # 注册 handler
    from app.handlers.data_handler import DataHandler
    data_handler = DataHandler(storage_manager, schema_manager)
    
    # 注册路由
    app.add_url_rule('/api/v1/data', 
                     view_func=data_handler.post, 
                     methods=['POST'])
    app.add_url_rule('/api/v1/data', 
                     view_func=data_handler.get, 
                     methods=['GET'])
    
    return app
```

#### 5.4.2 DynamicLoader 集成

**文件**: `app/loader.py`

```python
import yaml
from app.handlers import DataHandler, SchemaHandler, StatsHandler

class DynamicLoader:
    """动态加载 handler 和 interface"""
    
    def __init__(self, app, interfaces_dir: str):
        self.app = app
        self.interfaces_dir = interfaces_dir
        
    def load_interfaces(self):
        """加载所有 interface 定义"""
        interface_files = glob.glob(os.path.join(self.interfaces_dir, "*.yaml"))
        
        for file_path in interface_files:
            with open(file_path, 'r') as f:
                interface_def = yaml.safe_load(f)
                
            self._register_endpoints(interface_def)
    
    def _register_endpoints(self, interface_def):
        """注册端点"""
        for endpoint in interface_def['endpoints']:
            path = endpoint['path']
            methods = endpoint['methods']
            handler_class = endpoint['handler']
            
            # 动态导入 handler
            module_name, class_name = handler_class.rsplit('.', 1)
            module = __import__(f"app.handlers.{module_name}", fromlist=[class_name])
            handler_class = getattr(module, class_name)
            
            # 实例化 handler
            handler = handler_class()
            
            # 注册路由
            for method in methods:
                self.app.add_url_rule(
                    path,
                    view_func=getattr(handler, method.lower()),
                    methods=[method]
                )
```

### 5.5 实施步骤

**阶段 1: 基础集成**
1. 编写 Dockerfile
2. 创建应用工厂
3. 集成 DynamicLoader

**阶段 2: 功能实现**
1. 实现所有 handler
2. 测试 API 端点
3. 调试和修复

**阶段 3: 构建和部署**
1. 构建 Docker 镜像
2. 推送到 192.168.31.32:5001
3. 测试部署

---

## 6. REQ-005: 配置管理

### 6.1 需求分析

**需求描述**:
- 实现配置管理模块
- 目前需要管理的配置有：
  - `allow_delete`：全局控制数据删除操作
  - `allow_modify`：全局控制数据修改操作

**设计目标**:
- 配置集中管理，避免散落在代码各处
- 支持环境变量覆盖（便于容器化部署）
- 配置项有明确默认值，安全优先（默认关闭危险操作）

### 6.2 配置项设计

**配置优先级（从高到低）**：
1. 环境变量（`DATACENTER_*`）
2. XML 配置文件（`config.xml` 或 `DATACENTER_CONFIG_FILE` 指定路径）
3. 代码默认值

| 配置项 | 类型 | 默认值 | 环境变量 | XML 标签 | 说明 |
|--------|------|--------|----------|----------|------|
| `ALLOW_DELETE` | bool | `False` | `DATACENTER_ALLOW_DELETE` | `<ALLOW_DELETE>` | 全局控制 DELETE 操作 |
| `ALLOW_PUT` | bool | `False` | `DATACENTER_ALLOW_PUT` | `<ALLOW_PUT>` | 全局控制 PUT 操作 |
| `DATA_DIR` | str | `./data` | `DATACENTER_DATA_DIR` | `<DATA_DIR>` | 数据存储根目录 |
| `COMPRESSION` | str | `SNAPPY` | `DATACENTER_COMPRESSION` | `<COMPRESSION>` | Parquet 压缩算法 |
| `CONFIG_FILE` | str | `config.xml` | `DATACENTER_CONFIG_FILE` | — | XML 配置文件路径 |

**XML 配置文件格式**（`config.xml`）：
```xml
<config>
    <DATA_DIR>./data</DATA_DIR>
    <COMPRESSION>SNAPPY</COMPRESSION>
    <ALLOW_DELETE>false</ALLOW_DELETE>
    <ALLOW_PUT>false</ALLOW_PUT>
</config>
```

> 注：环境变量优先级高于 XML 文件；XML 文件不存在时不报错，使用默认值。

### 6.3 配置管理实现（`app/config.py`）

**配置加载顺序**（`__init__` 内按顺序执行）：
1. 加载代码默认值
2. 加载 XML 配置文件（若存在，`CONFIG_FILE` 或默认 `config.xml`）
3. 加载环境变量（覆盖 XML 中的值）
4. 应用运行时 override（`**overrides`）

```python
import os
import xml.etree.ElementTree as ET
from typing import Any, Dict


class Config:
    """集中式配置管理
    
    优先级（从高到低）：
    1. 运行时 override（`**overrides`）
    2. 环境变量（`DATACENTER_*`）
    3. XML 配置文件（`config.xml`）
    4. 代码默认值
    """

    def __init__(self, **overrides: Any) -> None:
        # 1. 代码默认值
        self.DATA_DIR: str = './data'
        self.COMPRESSION: str = 'SNAPPY'
        self.ALLOW_DELETE: bool = False
        self.ALLOW_PUT: bool = False

        # 2. 加载 XML 配置文件
        config_file = os.getenv('DATACENTER_CONFIG_FILE', 'config.xml')
        self._load_xml_config(config_file)

        # 3. 加载环境变量（优先级高于 XML）
        self.DATA_DIR = os.getenv('DATACENTER_DATA_DIR', self.DATA_DIR)
        self.COMPRESSION = os.getenv('DATACENTER_COMPRESSION', self.COMPRESSION)
        allow_delete_env = os.getenv('DATACENTER_ALLOW_DELETE')
        if allow_delete_env is not None:
            self.ALLOW_DELETE = allow_delete_env.lower() == 'true'
        allow_put_env = os.getenv('DATACENTER_ALLOW_PUT')
        if allow_put_env is not None:
            self.ALLOW_PUT = allow_put_env.lower() == 'true'

        # 4. 运行时 override（最高优先级）
        for key, value in overrides.items():
            if hasattr(self, key):
                setattr(self, key, value)

    def _load_xml_config(self, config_file: str) -> None:
        """从 XML 文件加载配置（文件不存在时跳过）"""
        if not os.path.exists(config_file):
            return
        try:
            tree = ET.parse(config_file)
            root = tree.getroot()
            for elem in root:
                if elem.tag == 'DATA_DIR':
                    self.DATA_DIR = elem.text or self.DATA_DIR
                elif elem.tag == 'COMPRESSION':
                    self.COMPRESSION = elem.text or self.COMPRESSION
                elif elem.tag == 'ALLOW_DELETE':
                    self.ALLOW_DELETE = (elem.text or 'false').lower() == 'true'
                elif elem.tag == 'ALLOW_PUT':
                    self.ALLOW_PUT = (elem.text or 'false').lower() == 'true'
        except Exception:
            # XML 解析失败时不报错，继续使用已有配置
            pass

    def to_dict(self) -> Dict[str, Any]:
        """导出当前配置（用于调试/健康检查）"""
        return {
            'DATA_DIR': self.DATA_DIR,
            'COMPRESSION': self.COMPRESSION,
            'ALLOW_DELETE': self.ALLOW_DELETE,
            'ALLOW_PUT': self.ALLOW_PUT,
        }
```

### 6.4 Handler 中的开关检查逻辑

配置开关在 Handler 层统一检查，不分散到 StorageManager 或 DataProcessor。

```python
# handlers/data_handler.py

class DataHandler:
    def __init__(self, data_processor, schema_manager, config):
        self.data_processor = data_processor
        self.schema_manager = schema_manager
        self.config = config

    def put(self, data_type: str):
        """修改数据 - 受 ALLOW_PUT 开关控制"""
        if not self.config.ALLOW_PUT:
            return jsonify({
                "success": False,
                "error": "PUT operation is disabled by configuration"
            }), 405
        # ... 正常处理逻辑 ...

    def delete(self, data_type: str):
        """删除数据 - 受 ALLOW_DELETE 开关控制"""
        if not self.config.ALLOW_DELETE:
            return jsonify({
                "success": False,
                "error": "DELETE operation is disabled by configuration"
            }), 405
        # ... 正常处理逻辑 ...
```

### 6.5 配置覆盖优先级

```
代码默认值（最底层）
    ← 环境变量覆盖（容器化部署推荐）
    ← 运行时 override（最高优先级，用于测试）
```

**示例**：
```bash
# 生产部署时通过环境变量开启修改权限
export DATACENTER_ALLOW_PUT=true
export DATACENTER_ALLOW_DELETE=false
python app.py

# 或者 Docker 启动时传递
docker run -e DATACENTER_ALLOW_PUT=true \
           -e DATACENTER_DATA_DIR=/data \
           datacenter:latest
```

### 6.6 实施步骤

**阶段 1: 基础配置管理**
1. 创建 `app/config.py`
2. 实现 `Config` 类（支持环境变量 + 运行时覆盖）
3. 单元测试：验证默认值、环境变量覆盖、类型转换

**阶段 2: 集成到 Handler**
1. 修改 `handlers/data_handler.py` 的 `put()` 和 `delete()` 方法
2. 添加配置开关检查逻辑
3. 单元测试：验证开关关闭时返回 405

**阶段 3: 文档和示例**
1. 更新 API 文档（已经包含在 §3.3.0）
2. 添加配置示例（docker-compose.yml 示例）

---

## 7. 技术架构设计

### 7.1 系统架构图（已更新）

```
┌─────────────────────────────────────────────────────────────┐
│                      Client (Browser/App)                 │
└────────────────────────────┬────────────────────────────────┘
                             │ HTTP Request
┌────────────────────────────▼────────────────────────────────┐
│                    nginx (Port 80)                         │
│  - Reverse Proxy                                          │
│  - Static File Serving                                    │
└────────────────────────────┬────────────────────────────────┘
                             │ uWSGI Protocol
┌────────────────────────────▼────────────────────────────────┐
│                  uWSGI (Port 8080)                        │
│  - WSGI Server                                            │
│  - Flask App Container                                    │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│                   Flask Application                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │
│  │   Router    │  │  Handlers   │  │   Config    │      │
│  └─────────────┘  └─────────────┘  └─────────────┘      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │
│  │    Schema   │  │     Data    │  │    Index    │      │
│  │   Manager   │  │  Processor  │  │   Manager   │      │
│  └─────────────┘  └─────────────┘  └─────────────┘      │
│  ┌─────────────┐                                           │
│  │  Storage    │                                           │
│  │   Manager   │                                           │
│  └─────────────┘                                           │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│                      Data Layer                            │
│  ┌─────────────┐  ┌─────────────┐                      │
│  │   Parquet   │  │   Schemas   │                      │
│  │    Files    │  │    JSON     │                      │
│  └─────────────┘  └─────────────┘                      │
└─────────────────────────────────────────────────────────────┘
```

**关键变化**：
- ❌ 移除了 Index JSON 存储（索引模块不再存储数据）
- ✅ 新增 DataProcessor 模块（负责数据读写和验证）
- ✅ IndexManager 只负责路径计算

### 7.2 数据流图（已更新）

**写入数据流**:
```
Client → POST /api/v1/data/{data_type} → Handler 
  → DataProcessor.write_data()
    → SchemaManager.validate()  # Schema 验证
    → DataProcessor.check_duplicates()  # 重复验证（可选）
    → IndexManager.get_write_path()  # 获取写入路径
    → StorageManager.write_parquet()  # 写入文件
  → Return Response to Client
```

**查询数据流**:
```
Client → GET /api/v1/data/{data_type} → Handler 
  → DataProcessor.read_data()
    → IndexManager.get_read_paths()  # 获取读取路径列表
    → StorageManager.read_parquet()  # 读取文件
    → Filter (market, codes)  # 过滤数据
  → DataFrame → JSON Response → Client
```

### 7.3 模块交互（已更新）

| 模块 | 依赖模块 | 被依赖模块 | 职责 |
|------|----------|------------|------|
| Config | - | All | 配置管理 |
| SchemaManager | Config | DataProcessor | Schema 加载和验证 |
| IndexManager | Config | DataProcessor | 路径计算（不存储数据） |
| DataProcessor | SchemaManager, IndexManager, StorageManager | Handler | 数据读写和验证 |
| StorageManager | Config | DataProcessor | Parquet I/O（底层） |
| Handler | DataProcessor | - | API 请求处理 |

---

## 8. 实施计划

### 8.1 开发阶段

**阶段 1: 项目初始化（1-2天）**
- [ ] 创建项目结构
- [ ] 编写 Dockerfile
- [ ] 实现 Config 模块
- [ ] 搭建测试框架

**阶段 2: Schema 管理（2-3天）**
- [ ] 实现 SchemaManager
- [ ] 定义股票 5min schema
- [ ] 实现 schema 验证
- [ ] 单元测试

**阶段 3: 存储管理（3-4天）**
- [ ] 实现 IndexManager
- [ ] 实现 StorageManager
- [ ] 支持 Parquet 读写
- [ ] 支持数据分区
- [ ] 集成测试

**阶段 4: API 开发（3-4天）**
- [ ] 集成 restfulapi-interface
- [ ] 实现 handler
- [ ] 定义 interface
- [ ] 编写 API 文档
- [ ] API 测试

**阶段 5: 优化和部署（2-3天）**
- [ ] 性能优化
- [ ] 错误处理
- [ ] 日志记录
- [ ] 构建 Docker 镜像
- [ ] 部署测试

**总计**: 11-16 个工作日

### 8.2 里程碑

| 里程碑 | 时间 | 交付物 |
|--------|------|--------|
| M1: 项目初始化 | Day 2 | 项目结构、Dockerfile |
| M2: Schema 管理 | Day 5 | SchemaManager、Schema 定义 |
| M3: 存储管理 | Day 9 | StorageManager、IndexManager |
| M4: API 开发 | Day 13 | RESTful API、文档 |
| M5: 部署完成 | Day 16 | Docker 镜像、部署文档 |

### 8.3 任务分配

**开发者 1**:
- Config 模块
- SchemaManager
- 单元测试

**开发者 2**:
- IndexManager
- StorageManager
- 集成测试

**开发者 3**:
- Flask 应用
- Handler 实现
- API 文档

---

## 9. 风险与注意事项

### 9.1 技术风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| Parquet 性能问题 | 高 | 低 | 性能测试、优化压缩算法 |
| Schema 演进不兼容 | 中 | 中 | 版本管理、兼容性检查 |
| RESTful API 性能瓶颈 | 高 | 低 | 缓存、分页、异步处理 |
| 数据丢失 | 高 | 低 | 备份策略、事务支持 |

### 9.2 依赖风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| restfulapi-interface 变更 | 中 | 中 | 版本锁定、接口抽象 |
| 192.168.31.32:5001 不可用 | 高 | 低 | 本地缓存镜像 |
| baseos 更新 | 低 | 高 | 定期同步、测试 |

### 9.3 注意事项

1. **Schema 设计**:
   - 字段类型选择要谨慎（string vs. int）
   - 考虑未来扩展性
   - 文档要详细

2. **性能优化**:
   - 使用合适的压缩算法（SNAPPY 推荐）
   - 分区策略要合理
   - 避免小文件问题

3. **API 设计**:
   - 遵循 RESTful 规范
   - 错误信息要详细
   - 支持批量操作

4. **数据安全**:
   - 输入验证
   - 权限控制
   - 审计日志

---

## 10. 附录

### 10.1 参考资料

- [Apache Parquet 官方文档](https://parquet.apache.org/docs/)
- [PyArrow 文档](https://arrow.apache.org/docs/python/)
- [OpenAPI 规范](https://swagger.io/specification/)
- [RESTful API 设计最佳实践](https://restfulapi.net/)

### 10.2 相关项目

- **baseos**: 基础操作系统镜像
- **restfulapi-interface**: RESTful API 基础镜像
- **stockdata**: 股票数据采集项目（未来集成）

### 10.3 变更日志

| 版本 | 日期 | 作者 | 变更内容 |
|------|------|------|----------|
| v1.0 | 2026-05-17 | AI | 初始版本 |
| v1.1 | 2026-05-17 | AI | 架构调整：IndexManager纯计算、新增DataProcessor |
| v1.2 | 2026-05-17 | AI | 三项更新：数据类型不支持动态扩展(版本升级实现)；API新增ALLOW_PUT/ALLOW_DELETE配置开关；API路径体现data_type |
| v1.3 | 2026-05-17 | AI | 新增 REQ-005 配置管理章节（§6）；更新全文章节编号 |
| v1.4 | 2026-05-17 | AI | 统一命名：`ALLOW_MODIFY` → `ALLOW_PUT`（全文替换） |

---

**文档状态**: 草稿
**下次评审**: 2026-05-20
**负责人**: 待定
