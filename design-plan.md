# DataCenter 设计计划文档

本文档根据 requirement.md 中的需求，详细分析每个需求的实现方法，并制定技术实施方案。

---

## 目录

1. [项目概述](#1-项目概述)
2. [REQ-001: Parquet 存储方案](#2-req-001-采用-parquet-进行基础数据存储)
3. [REQ-002: RESTful API 微服务架构](#3-req-002-微服务架构使用-restful-api-接口)
4. [REQ-003: 灵活数据类型支持](#4-req-003-存储数据类型灵活支持拓展)
5. [REQ-004: 依赖关系](#5-req-004-依赖关系)
6. [技术架构设计](#6-技术架构设计)
7. [实施计划](#7-实施计划)
8. [风险与注意事项](#8-风险与注意事项)

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

- 默认按天存储：`data/stock/5min/2026-05-17.parquet`
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

#### 2.4.1 目录结构

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

**格式**: `{date}[_part{num}].parquet`

**示例**:
- `2026-05-17.parquet` (默认)
- `2026-05-17_part001.parquet` (分片)
- `2026-05-17_part002.parquet` (分片)

### 2.5 Schema 模块设计

#### 2.5.1 Schema 管理器 (`schema_manager.py`)

**职责**:
1. 加载和验证 schema 定义文件
2. 根据数据类型和版本获取 schema
3. 验证数据是否符合 schema
4. 支持 schema 版本管理

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
```

#### 2.5.2 Schema 注册流程

**步骤**:
1. 在 `schemas/` 目录创建 JSON 定义文件（如 `stock_5min_v1.json`）
2. SchemaManager 启动时自动加载所有 schema
3. 数据写入前验证 schema
4. 数据读取时应用 schema

**示例**: 注册新数据类型
```bash
# 1. 创建 schema 文件
vim schemas/new_datatype_v1.json

# 2. 重启服务（自动加载）
# 3. 验证
curl http://localhost:8080/api/v1/schemas
```

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
    def __init__(self, data_dir: str):
        """初始化索引管理器"""
        self.data_dir = data_dir
        
    def get_write_path(self, data_type: str, granularity: str, 
                        date: str, market: str = None) -> str:
        """获取数据写入路径（单个文件）"""
        # 示例返回: data/stock/5min/2026/05/2026-05-17.parquet
        
    def get_read_paths(self, data_type: str, granularity: str,
                       start_date: str, end_date: str,
                       market: str = None) -> List[str]:
        """获取数据读取路径（可能多个文件）"""
        # 示例返回: [
        #   "data/stock/5min/2026/05/2026-05-17.parquet",
        #   "data/stock/5min/2026/05/2026-05-18.parquet"
        # ]
        
    def get_partition_paths(self, data_type: str, granularity: str,
                           date: str) -> List[str]:
        """获取分区路径（用于分区写入）"""
        # 如果数据量大，返回分片路径
        # 示例: [
        #   "data/stock/5min/2026/05/2026-05-17_part001.parquet",
        #   "data/stock/5min/2026/05/2026-05-17_part002.parquet"
        # ]
        
    def validate_path(self, path: str) -> bool:
        """验证路径是否符合规范"""
```

#### 2.6.3 路径计算规则

**路径格式**：`{data_dir}/{data_type}/{granularity}/YYYY/MM/{date}.parquet`

**示例**：
- 股票 5 分钟数据：`data/stock/5min/2026/05/2026-05-17.parquet`
- 股票日线数据：`data/stock/1day/2026/05/2026-05-17.parquet`
- 指数成分股：`data/index/constituents/2026/05/2026-05-17.parquet`

**分片规则**：
- 单文件超过 100MB 或 100 万条记录时自动分片
- 分片格式：`{date}_part{num:03d}.parquet`
- 示例：`2026-05-17_part001.parquet`

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
#   "file_path": "data/stock/5min/2026/05/2026-05-17.parquet",
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
        
    def write_parquet(self, data: pd.DataFrame, file_path: str,
                      schema: pa.Schema = None, mode: str = 'append') -> str:
        """写入 Parquet 文件"""
        # 如果 mode='append' 且文件存在，读取后合并
        # 如果 mode='overwrite'，直接覆盖
        
    def read_parquet(self, file_paths: List[str],
                     columns: List[str] = None) -> pd.DataFrame:
        """读取 Parquet 文件"""
        # 读取单个或多个文件
        # 如果指定 columns，只读取指定列
        
    def delete_parquet(self, file_path: str) -> bool:
        """删除 Parquet 文件"""
        
    def file_exists(self, file_path: str) -> bool:
        """检查文件是否存在"""
        
    def get_file_metadata(self, file_path: str) -> dict:
        """获取文件元数据（行数、大小等）"""
```

### 2.8 实施步骤

**阶段 1: 基础框架搭建**
1. 创建项目结构
2. 实现 SchemaManager
3. 实现 IndexManager (JSON 版本)
4. 实现 StorageManager

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
- 按照数据类型定义 API 的结构和操作
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

### 3.3 API 设计

#### 3.3.1 RESTful API 端点设计

**资源**: `data`

**端点列表**:

| HTTP 方法 | 端点 | 功能 | 请求体 | 响应 |
|-----------|------|------|--------|------|
| POST | `/api/v1/data` | 写入数据 | JSON/Parquet | 写入结果 |
| GET | `/api/v1/data` | 查询数据 | Query 参数 | JSON/Parquet |
| PUT | `/api/v1/data` | 更新数据 | JSON/Parquet | 更新结果 |
| DELETE | `/api/v1/data` | 删除数据 | Query 参数 | 删除结果 |
| GET | `/api/v1/data/schemas` | 列出所有 schema | - | JSON |
| GET | `/api/v1/data/stats` | 获取存储统计 | - | JSON |

#### 3.3.2 API 详细说明

**1. 写入数据**

```
POST /api/v1/data
Content-Type: application/json

{
  "data_type": "stock",
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

**响应**:
```json
{
  "success": true,
  "message": "Data written successfully",
  "details": {
    "rows_written": 1,
    "file_path": "data/stock/5min/2026/05/2026-05-17.parquet",
    "schema": "stock_5min_v1"
  }
}
```

**2. 查询数据**

```
GET /api/v1/data?data_type=stock&granularity=5min&start_date=2026-05-17&end_date=2026-05-18&market=XHKG&codes=00700,00701
```

**响应**:
```json
{
  "success": true,
  "data": [...],
  "metadata": {
    "total_rows": 96,
    "files_read": 2,
    "schema": "stock_5min_v1"
  }
}
```

**3. 列出所有 schema**

```
GET /api/v1/data/schemas
```

**响应**:
```json
{
  "success": true,
  "schemas": [
    {
      "name": "stock_5min",
      "version": "v1",
      "fields": [...]
    }
  ]
}
```

### 3.4 Interface 定义

#### 3.4.1 创建 interface 文件

**文件**: `interfaces/data_interface.yaml`

```yaml
api_version: v1
endpoints:
  - path: /api/v1/data
    methods: [POST, GET, PUT, DELETE]
    handler: data_handler.DataHandler
    description: "数据写入和查询接口"
    
  - path: /api/v1/data/schemas
    methods: [GET]
    handler: data_handler.SchemaHandler
    description: "Schema 管理接口"
    
  - path: /api/v1/data/stats
    methods: [GET]
    handler: data_handler.StatsHandler
    description: "存储统计接口"
```

### 3.5 Handler 实现

#### 3.5.1 数据处理器 (`handlers/data_handler.py`)

```python
from flask import request, jsonify
import pandas as pd
from app.storage_manager import StorageManager
from app.schema_manager import SchemaManager

class DataHandler:
    def __init__(self, storage_manager: StorageManager, 
                 schema_manager: SchemaManager):
        self.storage_manager = storage_manager
        self.schema_manager = schema_manager
    
    def post(self):
        """写入数据"""
        try:
            payload = request.json
            data_type = payload['data_type']
            granularity = payload['granularity']
            date = payload['date']
            data = payload['data']
            
            # 转换为 DataFrame
            df = pd.DataFrame(data)
            
            # 写入数据
            file_path = self.storage_manager.write_data(
                df, data_type, granularity, date
            )
            
            return jsonify({
                "success": True,
                "message": "Data written successfully",
                "details": {
                    "rows_written": len(df),
                    "file_path": file_path
                }
            }), 200
            
        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 400
    
    def get(self):
        """查询数据"""
        try:
            data_type = request.args.get('data_type')
            granularity = request.args.get('granularity')
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            market = request.args.get('market')
            
            # 读取数据
            df = self.storage_manager.read_data(
                data_type, granularity, 
                start_date, end_date, market
            )
            
            return jsonify({
                "success": True,
                "data": df.to_dict('records'),
                "metadata": {
                    "total_rows": len(df)
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

### 4.2 Schema 注册机制

#### 4.2.1 Schema 注册流程

**步骤**:
1. 定义 schema JSON 文件
2. 放置到 `schemas/` 目录
3. 重启服务或热加载
4. Schema 自动注册到 SchemaManager
5. API 自动支持新数据类型

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

#### 4.3.2 动态加载机制

**SchemaManager 加载逻辑**:
```python
def load_all_schemas(self):
    """加载所有 schema 文件"""
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
        else:
            # 比较版本号，更新最新版本
            pass
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

**阶段 3: 扩展支持**
1. 添加更多数据类型（日线、Tick等）
2. 实现动态加载
3. 文档和示例

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

## 6. 技术架构设计

### 6.1 系统架构图（已更新）

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

### 6.2 数据流图（已更新）

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

### 6.3 模块交互（已更新）

| 模块 | 依赖模块 | 被依赖模块 | 职责 |
|------|----------|------------|------|
| Config | - | All | 配置管理 |
| SchemaManager | Config | DataProcessor | Schema 加载和验证 |
| IndexManager | Config | DataProcessor | 路径计算（不存储数据） |
| DataProcessor | SchemaManager, IndexManager, StorageManager | Handler | 数据读写和验证 |
| StorageManager | Config | DataProcessor | Parquet I/O（底层） |
| Handler | DataProcessor | - | API 请求处理 |

---

## 7. 实施计划

### 7.1 开发阶段

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

### 7.2 里程碑

| 里程碑 | 时间 | 交付物 |
|--------|------|--------|
| M1: 项目初始化 | Day 2 | 项目结构、Dockerfile |
| M2: Schema 管理 | Day 5 | SchemaManager、Schema 定义 |
| M3: 存储管理 | Day 9 | StorageManager、IndexManager |
| M4: API 开发 | Day 13 | RESTful API、文档 |
| M5: 部署完成 | Day 16 | Docker 镜像、部署文档 |

### 7.3 任务分配

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

## 8. 风险与注意事项

### 8.1 技术风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| Parquet 性能问题 | 高 | 低 | 性能测试、优化压缩算法 |
| Schema 演进不兼容 | 中 | 中 | 版本管理、兼容性检查 |
| RESTful API 性能瓶颈 | 高 | 低 | 缓存、分页、异步处理 |
| 数据丢失 | 高 | 低 | 备份策略、事务支持 |

### 8.2 依赖风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| restfulapi-interface 变更 | 中 | 中 | 版本锁定、接口抽象 |
| 192.168.31.32:5001 不可用 | 高 | 低 | 本地缓存镜像 |
| baseos 更新 | 低 | 高 | 定期同步、测试 |

### 8.3 注意事项

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

## 9. 附录

### 9.1 参考资料

- [Apache Parquet 官方文档](https://parquet.apache.org/docs/)
- [PyArrow 文档](https://arrow.apache.org/docs/python/)
- [OpenAPI 规范](https://swagger.io/specification/)
- [RESTful API 设计最佳实践](https://restfulapi.net/)

### 9.2 相关项目

- **baseos**: 基础操作系统镜像
- **restfulapi-interface**: RESTful API 基础镜像
- **stockdata**: 股票数据采集项目（未来集成）

### 9.3 变更日志

| 版本 | 日期 | 作者 | 变更内容 |
|------|------|------|----------|
| v1.0 | 2026-05-17 | AI | 初始版本 |
| v1.1 | 2026-05-17 | AI | 架构调整：IndexManager纯计算、新增DataProcessor |
| v1.2 | 2026-05-17 | AI | 三项更新：数据类型不支持动态扩展(版本升级实现)；API新增ALLOW_PUT/ALLOW_DELETE配置开关；API路径体现data_type |

---

**文档状态**: 草稿
**下次评审**: 2026-05-20
**负责人**: 待定
