# DataCenter Release Notes

## v0.2.0 (2026-05-19)

### 新功能
- **index_constituents 数据类型**：新增指数成分股存储，扁平化 schema（index_code, index_name_en, index_name_cn, date, stock_code, stock_name），按 index_code 分文件存储
- **YAML 路由**：data_interface.yaml 新增 index_constituents 的 GET/POST/PUT/DELETE/schemas/stats 全套路由

### 改进
- **Dockerfile 构建清理**：构建时先 `rm -rf` 清除 base 镜像残留的 interfaces/handlers 文件，再拷贝 DataCenter 的版本，避免旧文件干扰

### 修复
- **开放式范围过滤**：IndexManager 和 DataProcessor 中 `f_field=value~` 格式（仅有 start 无 end）不再报 KeyError
- **SchemaManager 方法调用**：handler_factory.py 中修正为 `get_data_schema()` 方法

### 测试
- 新增 test_index_constituents.py（6 个测试用例）
- Docker 镜像构建验证：interfaces/handlers 目录无残留文件

---

## v0.1.0 (2026-05-19)

### 新功能
- **f_ 前缀过滤系统**：支持 `f_field=value` 单值、`f_field=a,b` 枚举、`f_field=start~end` 范围、`f_field=start~` 开放式范围四种过滤格式
- **RESTful API 完整实现**：GET/POST/PUT/DELETE + schemas/stats 子路由
- **Parquet 存储**：pyarrow + Parquet 格式，按日期路径自动分片
- **DynamicLoader 路由加载**：从 YAML 文件动态注册路由
- **版本化 Schema**：JSON 格式定义，支持多版本共存

### 架构
- Flask + Nginx + uWSGI + Supervisor
- Docker 分层构建：baseOS → restfulapi-interface → DataCenter
