"""
config.py - DataCenter 独立配置模块

功能：
  - 读取 DataCenter/config.xml 获得 data_dir 配置
  - 仅支持 data_dir 属性（其他路径在 DataManager 初始化时传入）
  - 支持 ~ 展开（tilde expansion）
"""

import os

# 配置默认值：data 目录相对于本文件的路径
DEFAULT_DATA_DIR = "data"


class Config:
    """
    DataCenter 专用配置类。
    提供 data_dir 快捷访问，模拟 stockdata/config.py 的 get() 接口子集。
    """

    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), "config.xml")
        self._config_path = config_path
        self._data_dir = self._load_data_dir()

    def _load_data_dir(self) -> str:
        """从 config.xml 读取 data_dir，无配置则返回默认值"""
        if not os.path.exists(self._config_path):
            return DEFAULT_DATA_DIR
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse(self._config_path)
            root = tree.getroot()
            storage = root.find("storage")
            if storage is not None:
                data_dir = storage.find("dataDir")
                if data_dir is not None:
                    path = data_dir.text.strip()
                    # tilde expansion
                    return os.path.expanduser(path)
        except Exception:
            pass
        return DEFAULT_DATA_DIR

    @property
    def data_dir(self) -> str:
        """返回 data_dir 路径（已做 tilde 展开）"""
        return self._data_dir

    def get(self, section: str, key: str, default=None):
        """通用读取接口（模拟 stockdata/config.py）"""
        if section == "data" and key == "data_dir":
            return self._data_dir
        return default