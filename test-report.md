# DataCenter 项目测试报告

**测试日期**: 2026-05-18  
**测试环境**: macOS 12.7.6, Python 3.13.12, pytest 9.0.3  
**项目路径**: ~/JoeClawWorkspace/DataCenter

---

## 一、单元测试（UT）

### 1.1 测试概览

| 测试模块 | 测试文件 | 测试用例数 | 通过率 |
|---------|---------|-----------|--------|
| Config | test_config.py | 33 | 100% |
| SchemaManager | test_schema_manager.py | 54 | 100% |
| StorageManager | test_storage_manager.py | 35 | 100% |
| IndexManager | test_index_manager.py | 14 | 100% |
| DataProcessor | test_data_processor.py | 13 | 100% |
| **总计** | | **144** | **100%** |

### 1.2 Config 模块测试（33/33 通过）

**测试类**: `TestConfigDefaults` / `TestConfigEnvOverride` / `TestConfigRuntimeOverride` / `TestToDict` / `TestGetConfigSingleton` / `TestConfigIntegration` / `TestConfigXml` / `TestConfigPriority`

**测试场景**:

| 场景类别 | 测试内容 | 用例数 |
|---------|---------|--------|
| 默认值 | DATA_DIR/COMPRESSION/ALLOW_DELETE/ALLOW_PUT 默认值验证 | 4 |
| 环境变量覆盖 | DATACENTER_DATA_DIR/DATACENTER_COMPRESSION/DATACENTER_ALLOW_DELETE/DATACENTER_ALLOW_PUT 环境变量优先级 | 6 |
| 运行时覆盖 | Config(overrides={...}) 运行时参数最高优先级 | 6 |
| 配置导出 | to_dict() 方法返回所有配置键值 | 2 |
| 单例模式 | get_config() 返回单例实例，override 不破坏单例 | 3 |
| 优先级集成 | env > xml > defaults，runtime > env > xml | 4 |
| XML 加载 | config.xml 读取 DATA_DIR/COMPRESSION/ALLOW_DELETE/ALLOW_PUT，文件不存在/无效 XML 不报错 | 6 |
| 优先级验证 | env 覆盖 xml，xml 覆盖 defaults，runtime 覆盖全部 | 4 |

**关键验证点**:
- 配置优先级：`runtime override > env vars > XML config > defaults`
- CONFIG_FILE 环境变量可指定配置文件路径
- XML 解析失败不抛异常，使用默认值

### 1.3 SchemaManager 模块测试（54/54 通过）

**测试类**: `TestSchemaLoading` / `TestExtractSchemaRefs` / `TestValidateSchema` / `TestSchemaAccessors` / `TestValidateData` / `TestParquetSchema` / `TestGetSchemaForApi` / `TestEdgeCases`

**测试场景**:

| 场景类别 | 测试内容 | 用例数 |
|---------|---------|--------|
| Schema 加载 | 加载合法 schema、跳过非法命名、跳过缺字段、跳过嵌套 data_schema、跳过无 .parquet 后缀、跳过未定义引用、跳过非法类型、跳过空 data_schema | 8 |
| 引用提取 | 单引用、无引用、重复引用、混合花括号格式 | 4 |
| Schema 验证 | 缺 name/version/data_schema/storage_rule、data_schema 非空/非 dict/值为 list/dict/int、data_schema 类型非法（decimal/varchar）、storage_rule 非字符串/无后缀/.parquet 在中间、引用未定义字段、内置 name/version 允许、合法 schema 通过 | 26 |
| Schema 访问器 | get_storage_rule()、get_data_schema()、未知 schema 抛 KeyError | 4 |
| 数据验证 | validate_data() 合法数据、缺列、空 DataFrame | 3 |
| Parquet Schema | get_parquet_schema() 类型映射、未知 schema 抛错 | 3 |
| API 接口 | get_schema_for_api() 返回完整 schema | 2 |
| 边界情况 | 空 schema 目录、目录不存在、load_schema 抛 KeyError | 3 |

**Schema 格式验证规则（REQ-003）**:
- 必填字段：name / version / data_schema / storage_rule
- data_schema：dict、非空、key-value 均为 str、value 必须是 12 种合法类型之一
- storage_rule：字符串、必须以 `.parquet` 结尾
- `{schema.xxx}` 引用：name/version 内置免检，其他必须在 data_schema 有定义

**合法数据类型**（12 种）:
string / int / integer / float / double / bool / boolean / date / datetime / time / timestamp / long

### 1.4 StorageManager 模块测试（35/35 通过）

**测试类**: `TestInit` / `TestWriteAndRead` / `TestWriteModes` / `TestReadMultipleFiles` / `TestDelete` / `TestFileExists` / `TestMetadata` / `TestCompression` / `TestFileLock`

**测试场景**:

| 场景类别 | 测试内容 | 用例数 |
|---------|---------|--------|
| 初始化 | 默认/自定义压缩算法，非法压缩不报错 | 3 |
| 写入读取往返 | write → read 数据一致、自动创建父目录、带 schema 写入、读取不存在文件抛错、读取空文件列表 | 5 |
| 写入模式 | overwrite 覆盖、append 首次写入、append 累加、append 文件不存在回退 overwrite、非法模式抛错 | 5 |
| 多文件读取 | read_parquet([path1, path2]) 合并、columns 过滤、缺失列抛错 | 3 |
| 文件删除 | delete_existing_file 成功、delete_nonexistent 返回 False | 2 |
| 文件存在检查 | exists True/False | 2 |
| 元数据读取 | metadata_keys、row_count、file_size、columns_match、不存在文件抛错 | 5 |
| 压缩算法 | SNAPPY/GZIP/NONE 三种压缩测试 | 3 |
| 文件锁 | lock_path 生成、LOCK_EX 写锁、LOCK_SH 读锁、读写互斥、delete 移除锁文件、读时无锁文件、release_lock 可重入 | 7 |

**关键实现**:
- 使用 `fcntl.flock` 实现进程安全锁（advisory lock）
- 支持三种压缩：SNAPPY（默认）、GZIP、NONE
- append 模式读取已有文件后追加新数据

### 1.5 IndexManager 模块测试（14/14 通过）

**测试类**: `TestGetWritePaths` / `TestGetReadPaths` / `TestEdgeCases`

**测试场景**:

| 场景类别 | 测试内容 | 用例数 |
|---------|---------|--------|
| 写入路径 | 单分组写入、多分组按 market 拆分 | 2 |
| 读取路径 | 单日期、日期范围、market 过滤、market 枚举、无匹配文件、filter 键不在 storage_rule 静默忽略 | 6 |
| 边界情况 | 非法 data_type 抛 KeyError、缺少必填列抛 ValueError | 2 |
| Filter 功能 | date 单值/枚举/范围、组合 filter | 4 |

**接口设计**:
- `get_write_paths(data, data_type, version)` → 返回 `{路径: 数据子集}` 映射
- `get_read_paths(data_type, version, **filters)` → 返回文件路径列表

**Filter 支持类型**:
- 单值：`date="2026-05-17"`
- 枚举：`date=["2026-05-15", "2026-05-16"]`
- 范围：`date={"start": "2026-05-15", "end": "2026-05-17"}`

**路径渲染**:
- 从 storage_rule 字符串提取 `{schema.xxx}` 引用
- 动态处理大小写（Year/year 均支持）
- glob 模式扫描实际文件

### 1.6 DataProcessor 模块测试（13/13 通过）

**测试类**: `TestWriteData` / `TestReadData` / `TestValidateSchema`

**测试场景**:

| 场景类别 | 测试内容 | 用例数 |
|---------|---------|--------|
| 写入数据 | 单分组写入、多分组写入、append 模式、overwrite 模式、schema 验证失败、重复检测、重复自动移除 | 7 |
| 读取数据 | 空读取、写入后读取验证、row filter 按 code | 3 |
| Schema 验证 | 合法数据、缺列 | 2 |
| Row Filter | dict 范围类型 `{"start": ..., "end": ...}` 支持 | 1 |

**写入返回结构**:
```python
{
    'success': True,
    'total_rows': int,
    'files_written': int,
    'file_paths': List[str],
    'duplicates_found': int,
    'duplicates_removed': int
}
```

**重复检测逻辑**:
- 从 schema 的 data_schema 中提取主键字段（date/code/time 相关）
- 使用 DataFrame.merge() 做行级重复检测
- 配置 `ALLOW_DELETE=True` 时允许移除重复

---

## 二、集成测试（CT）

### 2.1 测试脚本

| 脚本 | 路径 | 功能 |
|------|------|------|
| test_write.py | CTtest/test_write.py | 多级别/多天/多市场写入验证 |
| test_filters.py | CTtest/test_filters.py | Filter 功能完整测试 |
| 数据完整性验证 | inline 测试 | 写入-读取一致性验证 |

### 2.2 多级别/多天/多市场写入测试

**测试参数**:
- 数据级别：stock_5min / stock_30min / stock_60min / stock_1day
- 日期：2026-05-15 / 16 / 17（3 天）
- 市场：XHKG（港股） / XSHG（沪市） / XSHE（深市）
- 每市场 3 只股票

**测试结果**:

| 级别 | 每日条数 | 3天×3市场总行数 | 生成文件数 |
|------|---------|----------------|-----------|
| stock_5min | 216 条/市场/天 | 1944 行 | 3 文件（按日期拆分） |
| stock_30min | 33 条/市场/天 | 297 行 | 3 文件 |
| stock_60min | 18 条/市场/天 | 162 行 | 3 文件 |
| stock_1day | 3 条/市场/天 | 27 行 | 3 文件 |

**生成文件**:
```
data/stock_5min/2026/05/2026-05-15.parquet  (648行)
data/stock_5min/2026/05/2026-05-16.parquet  (648行)
data/stock_5min/2026/05/2026-05-17.parquet  (648行)
data/stock_30min/2026/05/2026-05-15.parquet (99行)
...
```

### 2.3 Filter 功能测试

**测试脚本**: test_filters.py（11 个场景）

| # | Filter 类型 | 示例 | 结果 |
|---|-------------|------|------|
| 1 | date 单值 | `date="2026-05-15"` | ✅ 648 行 |
| 2 | date 枚举 | `date=["2026-05-15", "2026-05-16"]` | ✅ 1296 行 |
| 3 | date 范围 | `date={"start": "2026-05-15", "end": "2026-05-17"}` | ✅ 1944 行 |
| 4 | market 单值 | `market="XHKG"`（row filter） | ✅ 216 行 |
| 5 | market 枚举 | `market=["XHKG", "XSHG"]` | ✅ 432 行 |
| 6 | stock_code 单值 | `stock_code="00700"`（row filter） | ✅ 72 行 |
| 7 | stock_code 枚举 | `stock_code=["00700", "00941"]` | ✅ 144 行 |
| 8 | 组合：date 范围 + market 枚举 | | ✅ 1296 行 |
| 9 | 组合：date + market + stock_code | | ✅ 72 行 |
| 10 | 无 date filter | `stock_30min` 全月 | ✅ 297 行 |
| 11 | 无任何 filter | `stock_1day` 全量 | ✅ 27 行 |

### 2.4 跨文件写入测试

**场景**: 一次传入 3 天的 5min 数据（720 行），验证自动拆分

**结果**:
```
写入结果: files_written=3, total_rows=720
生成文件:
  2026-05-18.parquet (240行)
  2026-05-19.parquet (240行)
  2026-05-20.parquet (240行)
```

**验证点**: `get_write_paths(data, data_type, version)` 按 `storage_rule` 中的 `{schema.date}` 自动分组

### 2.5 数据完整性验证

**场景**: 写入 480 行数据，立即读取，对比

**验证项目**:

| 检查项 | 原始值 | 读取值 | 结果 |
|--------|--------|--------|------|
| 行数 | 480 | 480 | ✅ |
| 日期列表 | ['2026-05-21', '2026-05-22'] | 同上 | ✅ |
| 市场列表 | ['XHKG', 'XSHG'] | 同上 | ✅ |
| 股票列表 | ['00700', '600519'] | 同上 | ✅ |
| open 总和 | 56232.00 | 56232.00 | ✅ |
| close 总和 | 56712.00 | 56712.00 | ✅ |
| volume 总和 | 6446400 | 6446400 | ✅ |
| 第一行数值 | open=100.0, close=101.0 | 同上 | ✅ |
| 最后一行数值 | open=135.5, close=136.5 | 同上 | ✅ |

**结论**: 写入数据完整读取，无丢失，数值精度一致（float 对比误差 < 0.01）

---

## 三、测试覆盖总结

### 3.1 功能覆盖

| 模块 | 核心功能 | UT 覆盖 | CT 覆盖 |
|------|---------|---------|---------|
| Config | 配置加载优先级 | ✅ 33 用例 | - |
| SchemaManager | Schema 加载/验证/引用检查 | ✅ 54 用例 | ✅ 多级别 schema |
| StorageManager | Parquet 写入/读取/压缩/文件锁 | ✅ 35 用例 | ✅ 多文件写入 |
| IndexManager | 路径计算/分组/filter | ✅ 14 用例 | ✅ 跨文件写入 |
| DataProcessor | 写入协调/读取/验证/重复检测 | ✅ 13 用例 | ✅ 数据完整性 |

### 3.2 边界条件覆盖

- 空 DataFrame / 空文件列表
- 不存在的文件/目录/schema
- 非法参数类型（dict/list 传入错误位置）
- 缺失必填字段/列
- 重复数据检测
- 文件不存在时 append 回退 overwrite

### 3.3 并发安全

- `fcntl.flock` 文件锁测试（LOCK_EX 写锁 / LOCK_SH 读锁）
- 读写互斥验证
- 锁释放可重入

---

## 四、Bug 修复记录

| Bug | 发现时间 | 问题描述 | 修复方案 |
|-----|---------|---------|---------|
| read_parquet 参数类型错误 | 09:47 | `read_parquet(file_path)` 传入 str 导致逐字符迭代 | 修改为 `read_parquet([file_path])` |
| _find_duplicates 硬编码主键 | 11:27 | 硬编码 `["date", "stock_code"]` 与 fixture 不匹配 | 动态从 schema.data_schema 提取主键字段 |
| _render_glob_pattern 大小写问题 | 11:27 | 硬编码小写 year/month 与 schema 大写 Year/Month 不匹配 | 动态处理 placeholder，`field_name.lower()` 匹配 builtin |
| read_data 不支持 dict 范围 filter | 11:41 | `{"start": ..., "end": ...}` 类型 filter 导致 NotImplementedError | 新增 dict 类型检查，使用 DataFrame 范围过滤 |

---

## 五、Schema 文件

### 5.1 已定义 Schema

| 文件 | name | storage_rule | 状态 |
|------|------|--------------|------|
| stock_5min_v1.json | stock_5min | `{schema.name}/{schema.Year}/{schema.Month}/{schema.date}.parquet` | ✅ 已加载 |
| stock_30min_v1.json | stock_30min | 同上 | ✅ 已加载 |
| stock_60min_v1.json | stock_60min | 同上 | ✅ 已加载 |
| stock_1day_v1.json | stock_1day | 同上 | ✅ 已加载 |

### 5.2 data_schema 字段

所有 schema 共用相同字段定义：

| 字段 | 类型 | 说明 |
|------|------|------|
| Year | string | 年份 |
| Month | string | 月份 |
| date | string | 日期 |
| time | string | 时间 |
| market | string | 市场（XHKG/XSHG/XSHE） |
| stock_code | string | 股票代码 |
| stock_name | string | 股票名称 |
| open | float | 开盘价 |
| close | float | 收盘价 |
| high | float | 最高价 |
| low | float | 最低价 |
| volume | int | 成交量 |

---

## 六、结论

**测试结果**: 全部通过

- 单元测试：**144/144 通过**（100%）
- 集成测试：**全部通过**
  - 多级别写入：✅
  - 多天/多市场：✅
  - 跨文件写入：✅
  - Filter 功能：✅
  - 数据完整性：✅

**项目状态**: DataCenter 核心模块（Config / SchemaManager / StorageManager / IndexManager / DataProcessor）开发完成，测试覆盖充分，可进入下一阶段开发（API / Handler / Docker）。

---

**报告生成时间**: 2026-05-18 11:55 GMT+8  
**测试执行**: pytest 9.0.3 / Python 3.13.12