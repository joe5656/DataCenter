import os
import xml.etree.ElementTree as ET
from typing import Any, Dict


class Config:
    """集中式配置管理
    
    优先级（从高到低）：
    1. 运行时 override（**overrides）
    2. 环境变量（DATACENTER_*）
    3. XML 配置文件（config.xml）
    4. 代码默认值
    """
    
    def __init__(self, **overrides: Any) -> None:
        # 1. 代码默认值
        self.DATA_DIR: str = "./data"
        self.COMPRESSION: str = "SNAPPY"
        self.ALLOW_DELETE: bool = False
        self.ALLOW_PUT: bool = False

        # 2. 加载 XML 配置文件
        config_file = os.getenv("DATACENTER_CONFIG_FILE", "./config.xml")
        self._load_xml_config(config_file)

        # 3. 加载环境变量（优先级高于 XML）
        self.DATA_DIR = os.getenv("DATACENTER_DATA_DIR", self.DATA_DIR)
        self.COMPRESSION = os.getenv("DATACENTER_COMPRESSION", self.COMPRESSION)
        allow_delete_env = os.getenv("DATACENTER_ALLOW_DELETE")
        if allow_delete_env is not None:
            self.ALLOW_DELETE = allow_delete_env.lower() == "true"
        allow_put_env = os.getenv("DATACENTER_ALLOW_PUT")
        if allow_put_env is not None:
            self.ALLOW_PUT = allow_put_env.lower() == "true"

        # 4. 运行时 override（最高优先级）
        for key, value in overrides.items():
            if hasattr(self, key):
                setattr(self, key, value)

    def _load_xml_config(self, config_file: str) -> None:
        """从 XML 文件加载配置（文件不存在或解析失败时跳过，不报错）"""
        if not os.path.exists(config_file):
            return
        try:
            tree = ET.parse(config_file)
            root = tree.getroot()
            for elem in root:
                if elem.tag == "DATA_DIR":
                    self.DATA_DIR = (elem.text or self.DATA_DIR).strip()
                elif elem.tag == "COMPRESSION":
                    self.COMPRESSION = (elem.text or self.COMPRESSION).strip()
                elif elem.tag == "ALLOW_DELETE":
                    self.ALLOW_DELETE = ((elem.text or "false").strip().lower() == "true")
                elif elem.tag == "ALLOW_PUT":
                    self.ALLOW_PUT = ((elem.text or "false").strip().lower() == "true")
        except Exception:
            # XML 解析失败不报错，继续使用已有配置
            pass

    def to_dict(self) -> Dict[str, Any]:
        """导出当前配置（用于调试/健康检查）"""
        return {
            "DATA_DIR": self.DATA_DIR,
            "COMPRESSION": self.COMPRESSION,
            "ALLOW_DELETE": self.ALLOW_DELETE,
            "ALLOW_PUT": self.ALLOW_PUT,
        }


# 全局配置实例（单例模式）
_default_config: Any = None


def get_config(**overrides: Any) -> Config:
    """获取配置实例（单例）"""
    global _default_config
    if _default_config is None:
        _default_config = Config()

    if overrides:
        return Config(**overrides)

    return _default_config
