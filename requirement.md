# DataCenter 需求文档

本文档记录 DataCenter 项目的所有需求，由需求方（用户）提供，AI 根据文档实现。

---

## 1 顶层需求列表

### REQ-001 采用 Parquet 进行基础数据存储
数据颗粒度根据具体存储的数据类型定
不同数据类型的存储归类分开
不同数据类型需要建立数据schema，数据读取和写入设计单独的schema模块保障数据格式正确性
设计索引模块，根据不同的数据类型创建不同的索引（管理文件存储多少数据和文件夹结构，读取数据时知道从那个路径读取）
数据存储应该进程安全，同时只能有一个写入操作，且文件被写入时，应该阻塞读取，数据文件是唯一的，可以使用文件级别的访问锁机制，访问文件时必须获得读取锁或者写入锁

### REQ-002 微服务架构，使用restFul API接口进行数据存储和提取 集成restful-interface
按照数据类型定义API的结构和操作
建立restful API文档，定义API
按照restful 基础镜像的要求实现interface和handler

### REQ-003 存储数据类型灵活，支持拓展
不同数据类型注册不同schema
不同版本的schema可以不同
schema的基本格式应该包含: name, version, data_schema {......}, storage_rule这几个标准字段，
load schema时需要做schema合法性检查，要求必须带这几个字段，且data_schema内部必须是key-value的键值对，不允许再有更深的结构
storage_rule是存储路径的原语表示，必须以.parquet结尾（路径详细到文件），用schema.xxx格式表示schema里各个字段， 
当前支持的数据类型：股票数据的5min数据 （日期 股票代码 市场 股票名称 时间 开盘 收盘 最高 最低 成交量）

### REQ-004 依赖关系
集成192.168.31.32:5001/restfulapi-interface项目 （以baseos项目为基础镜像）

### REQ-005 配置管理
实现配置管理目前需要管理的配置有：
allow delete 用于全局控制数据的删除
allow put 用于全局控制数据的修改
支持采用xml文件的方式配置和采用环境变量的方式配置，环境变量优先