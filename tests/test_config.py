import os
import pytest
from app.config import Config, get_config


class TestConfigDefaults:
    """测试默认配置值"""
    
    def test_data_dir_default(self):
        cfg = Config()
        assert cfg.DATA_DIR == "./data"
    
    def test_compression_default(self):
        cfg = Config()
        assert cfg.COMPRESSION == "SNAPPY"
    
    def test_allow_delete_default(self):
        cfg = Config()
        assert cfg.ALLOW_DELETE is False
    
    def test_allow_put_default(self):
        cfg = Config()
        assert cfg.ALLOW_PUT is False


class TestConfigEnvOverride:
    """测试环境变量覆盖"""
    
    def test_data_dir_env(self, monkeypatch):
        monkeypatch.setenv("DATACENTER_DATA_DIR", "/custom/data")
        cfg = Config()
        assert cfg.DATA_DIR == "/custom/data"
    
    def test_compression_env(self, monkeypatch):
        monkeypatch.setenv("DATACENTER_COMPRESSION", "GZIP")
        cfg = Config()
        assert cfg.COMPRESSION == "GZIP"
    
    def test_allow_delete_env_true(self, monkeypatch):
        monkeypatch.setenv("DATACENTER_ALLOW_DELETE", "true")
        cfg = Config()
        assert cfg.ALLOW_DELETE is True
    
    def test_allow_delete_env_false(self, monkeypatch):
        monkeypatch.setenv("DATACENTER_ALLOW_DELETE", "false")
        cfg = Config()
        assert cfg.ALLOW_DELETE is False
    
    def test_allow_put_env_true(self, monkeypatch):
        monkeypatch.setenv("DATACENTER_ALLOW_PUT", "True")
        cfg = Config()
        assert cfg.ALLOW_PUT is True
    
    def test_allow_put_env_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("DATACENTER_ALLOW_PUT", "TRUE")
        cfg = Config()
        assert cfg.ALLOW_PUT is True


class TestConfigRuntimeOverride:
    """测试运行时覆盖（构造参数）"""
    
    def test_override_data_dir(self):
        cfg = Config(DATA_DIR="/runtime/data")
        assert cfg.DATA_DIR == "/runtime/data"
    
    def test_override_compression(self):
        cfg = Config(COMPRESSION="NONE")
        assert cfg.COMPRESSION == "NONE"
    
    def test_override_allow_delete(self):
        cfg = Config(ALLOW_DELETE=True)
        assert cfg.ALLOW_DELETE is True
    
    def test_override_allow_put(self):
        cfg = Config(ALLOW_PUT=True)
        assert cfg.ALLOW_PUT is True
    
    def test_override_ignores_unknown_key(self):
        cfg = Config(UNKNOWN_KEY="value")
        assert not hasattr(cfg, "UNKNOWN_KEY")
    
    def test_override_does_not_affect_class_default(self):
        cfg1 = Config(ALLOW_PUT=True)
        cfg2 = Config()
        assert cfg1.ALLOW_PUT is True
        assert cfg2.ALLOW_PUT is False  # 类默认值不变


class TestToDict:
    """测试 to_dict 方法"""
    
    def test_to_dict_returns_all_keys(self):
        cfg = Config()
        d = cfg.to_dict()
        assert set(d.keys()) == {"DATA_DIR", "COMPRESSION", "ALLOW_DELETE", "ALLOW_PUT"}
    
    def test_to_dict_values_match_attributes(self):
        cfg = Config()
        d = cfg.to_dict()
        assert d["DATA_DIR"] == cfg.DATA_DIR
        assert d["COMPRESSION"] == cfg.COMPRESSION
        assert d["ALLOW_DELETE"] == cfg.ALLOW_DELETE
        assert d["ALLOW_PUT"] == cfg.ALLOW_PUT


class TestGetConfigSingleton:
    """测试 get_config 单例行为"""
    
    def test_returns_same_instance(self):
        cfg1 = get_config()
        cfg2 = get_config()
        assert cfg1 is cfg2
    
    def test_with_overrides_returns_new_instance(self):
        cfg1 = get_config()
        cfg2 = get_config(ALLOW_PUT=True)
        assert cfg1 is not cfg2
        assert cfg2.ALLOW_PUT is True
        assert cfg1.ALLOW_PUT is False  # 原实例不受影响
    
    def test_override_does_not_mutate_singleton(self):
        get_config(ALLOW_DELETE=True)
        cfg = get_config()
        assert cfg.ALLOW_DELETE is False  # 单例未被修改


class TestConfigIntegration:
    """集成测试：环境变量 + 运行时覆盖组合"""
    
    def test_env_plus_runtime_override(self, monkeypatch):
        monkeypatch.setenv("DATACENTER_DATA_DIR", "/env/data")
        cfg = Config(DATA_DIR="/runtime/data")
        assert cfg.DATA_DIR == "/runtime/data"
    
    def test_runtime_override_higher_than_env(self, monkeypatch):
        monkeypatch.setenv("DATACENTER_ALLOW_PUT", "false")
        cfg = Config(ALLOW_PUT=True)
        assert cfg.ALLOW_PUT is True


class TestConfigXml:
    """测试 XML 配置文件加载"""

    def test_xml_loads_data_dir(self, tmp_path, monkeypatch):
        xml_file = tmp_path / "config.xml"
        xml_file.write_text(
            "<config><DATA_DIR>/xml/data</DATA_DIR></config>"
        )
        monkeypatch.chdir(tmp_path)
        cfg = Config()
        assert cfg.DATA_DIR == "/xml/data"

    def test_xml_loads_compression(self, tmp_path, monkeypatch):
        xml_file = tmp_path / "my_config.xml"
        xml_file.write_text(
            "<config><COMPRESSION>GZIP</COMPRESSION></config>"
        )
        monkeypatch.setenv("DATACENTER_CONFIG_FILE", str(xml_file))
        cfg = Config()
        assert cfg.COMPRESSION == "GZIP"

    def test_xml_missing_file_does_not_error(self):
        cfg = Config()
        assert cfg.DATA_DIR == "./data"  # 使用默认值

    def test_xml_allow_delete_true(self, tmp_path, monkeypatch):
        xml_file = tmp_path / "config.xml"
        xml_file.write_text(
            "<config><ALLOW_DELETE>true</ALLOW_DELETE></config>"
        )
        monkeypatch.chdir(tmp_path)
        cfg = Config()
        assert cfg.ALLOW_DELETE is True

    def test_xml_allow_put_true(self, tmp_path, monkeypatch):
        xml_file = tmp_path / "config.xml"
        xml_file.write_text(
            "<config><ALLOW_PUT>true</ALLOW_PUT></config>"
        )
        monkeypatch.chdir(tmp_path)
        cfg = Config()
        assert cfg.ALLOW_PUT is True

    def test_xml_invalid_xml_does_not_error(self, tmp_path, monkeypatch):
        xml_file = tmp_path / "config.xml"
        xml_file.write_text("<config><unclosed>")
        monkeypatch.chdir(tmp_path)
        cfg = Config()  # 不应抛异常
        assert cfg.DATA_DIR == "./data"  # 使用默认值


class TestConfigPriority:
    """测试配置优先级：env > XML > defaults"""

    def test_env_overrides_xml(self, tmp_path, monkeypatch):
        xml_file = tmp_path / "config.xml"
        xml_file.write_text(
            "<config><DATA_DIR>/xml/path</DATA_DIR>"
            "<COMPRESSION>SNAPPY</COMPRESSION></config>"
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DATACENTER_DATA_DIR", "/env/path")
        cfg = Config()
        assert cfg.DATA_DIR == "/env/path"  # 环境变量优先

    def test_xml_overrides_defaults(self, tmp_path, monkeypatch):
        xml_file = tmp_path / "config.xml"
        xml_file.write_text(
            "<config><DATA_DIR>/xml/path</DATA_DIR></config>"
        )
        monkeypatch.chdir(tmp_path)
        # 确保环境变量未设置
        monkeypatch.delenv("DATACENTER_DATA_DIR", raising=False)
        cfg = Config()
        assert cfg.DATA_DIR == "/xml/path"

    def test_runtime_overrides_all(self, tmp_path, monkeypatch):
        xml_file = tmp_path / "config.xml"
        xml_file.write_text(
            "<config><DATA_DIR>/xml/path</DATA_DIR></config>"
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DATACENTER_DATA_DIR", "/env/path")
        cfg = Config(DATA_DIR="/runtime/path")
        assert cfg.DATA_DIR == "/runtime/path"  # 运行时覆盖最高优先级

    def test_config_file_env_var(self, tmp_path, monkeypatch):
        xml_file = tmp_path / "custom.xml"
        xml_file.write_text(
            "<config><DATA_DIR>/custom/data</DATA_DIR></config>"
        )
        monkeypatch.setenv("DATACENTER_CONFIG_FILE", str(xml_file))
        # 确保默认 config.xml 不存在
        cfg = Config()
        assert cfg.DATA_DIR == "/custom/data"
