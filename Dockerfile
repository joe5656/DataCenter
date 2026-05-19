# ============================================================
# DataCenter Dockerfile
# 层级：baseOS → restfulapi-interface → DataCenter
# ============================================================
# restfulapi-interface（base）提供：
#   /app/app/         — Flask 框架 + DynamicLoader
#   /app/scripts/     — 启动脚本（entrypoint.sh）
#   /app/nginx/       — nginx 配置
#   /app/supervisor/  — 进程管理
#   /app/uwsgi/       — uWSGI 配置
# DataCenter 添加：
#   /app/DataCenter/  — 核心逻辑代码
#   /app/interfaces/  — DataCenter 接口定义（覆盖 base 的 demo）
#   /app/handlers/    — DataCenter Handler（覆盖 base 的 demo）
# ============================================================
FROM 192.168.31.32:5001/restfulapi-interface:v0.3.2

LABEL maintainer="zhouyi56@hotmail.com"
LABEL description="DataCenter - 金融数据存储微服务（集成 restfulapi-interface）"
LABEL version="1.0.0"

# ============================================================
# 第 1 步：安装 DataCenter 额外依赖
# ============================================================
COPY dependencies/requirements.txt /tmp/datacenter_requirements.txt
RUN pip3 install --break-system-packages --no-cache-dir -r /tmp/datacenter_requirements.txt && \
    rm /tmp/datacenter_requirements.txt

# ============================================================
# 第 2 步：复制 DataCenter 核心逻辑到 /app/DataCenter/
# .dockerignore 已排除：tests/、CTtest/、*.md、sessions/ 等
# ============================================================
COPY . /app/DataCenter/

# ============================================================
# 第 3 步：用 DataCenter 的 interface + handler 覆盖 base 的 demo
# 覆盖后 DynamicLoader 会加载 DataCenter 定义的路由
# ============================================================
COPY interfaces/ /app/restfulapi-interface/interfaces/
COPY app/handlers/ /app/restfulapi-interface/handlers/

# ============================================================
# 第 4 步：环境变量
# ============================================================
ENV PYTHONPATH=/app
ENV DATACENTER_DATA_DIR=/app/data
ENV DATACENTER_SCHEMAS_DIR=/app/DataCenter/schemas

# ============================================================
# 第 5 步：创建数据目录
# ============================================================
RUN mkdir -p /app/data && chown -R dev:dev /app

# ============================================================
# 第 6 步：启动命令（继承 restfulapi-interface 的 entrypoint）
# CMD 不写，继承 base 的 CMD ["/app/scripts/entrypoint.sh"]
# ============================================================
