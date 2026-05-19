#!/usr/bin/env python3
"""
run_api.py - DataCenter RESTful API 本地测试入口

用于本地独立运行测试（不走 restfulapi-interface Docker 环境）。
生产部署时由 restfulapi-interface 的 DynamicLoader 加载 DataHandler。

用法：
    cd ~/JoClawWorkspace/DataCenter
    DATACENTER_DATA_DIR=./CTtest/data DATACENTER_SCHEMAS_DIR=./schemas python run_api.py

环境变量：
    FLASK_HOST       默认 0.0.0.0
    FLASK_PORT       默认 5000
    FLASK_DEBUG      默认 false
    DATACENTER_DATA_DIR       数据目录（默认 CTtest/data）
    DATACENTER_SCHEMAS_DIR    schema 目录（默认 schemas）
"""

import os
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 确保 DataCenter 根目录在 Python 路径
_dc_root = os.path.dirname(os.path.abspath(__file__))
if _dc_root not in sys.path:
    sys.path.insert(0, _dc_root)

from app.handlers.handler_factory import create_standalone_app
# 兼容旧测试
create_app = create_standalone_app

if __name__ == '__main__':
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', '5000'))
    debug = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'

    app = create_standalone_app()
    logger.info(f"Starting DataCenter API on {host}:{port} (debug={debug})")
    app.run(host=host, port=port, debug=debug)
