"""
logger.py - 精简日志模块（DataCenter 专用）

功能：
  - info / warn / error 三个函数，打印带时间戳的彩色日志
  - 日志输出到 stderr（不影响 stdout，可重定向到文件）
"""

import sys
from datetime import datetime

# 日志颜色
C_RESET = "\033[0m"
C_INFO = "\033[92m"    # 绿色
C_WARN = "\033[93m"    # 黄色
C_ERROR = "\033[91m"   # 红色
C_GRAY = "\033[90m"    # 灰色


def _timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def info(msg: str):
    print(f"{C_GRAY}[{_timestamp()}]{C_RESET} {C_INFO}INFO{C_RESET}  {msg}", file=sys.stderr)


def warn(msg: str):
    print(f"{C_GRAY}[{_timestamp()}]{C_RESET} {C_WARN}WARN{C_RESET}  {msg}", file=sys.stderr)


def error(msg: str):
    print(f"{C_GRAY}[{_timestamp()}]{C_RESET} {C_ERROR}ERROR{C_RESET} {msg}", file=sys.stderr)