"""
Tests for DataHandler (Flask API handler)

这些测试需要完整的环境来测试 DataHandler 类。
"""
import json
import pytest
from unittest.mock import MagicMock, patch


class TestDataHandlerMethods:
    """测试 DataHandler 的方法"""

    def test_get_schema_fields(self):
        """测试 _get_schema_fields 方法"""
        from app.handlers.handler_factory import DataHandler

        handler = object.__new__(DataHandler)

        # Mock schema_manager
        handler.sm = MagicMock()
        handler.sm.get_data_schema.return_value = {
            'date': 'string',
            'code': 'string',
            'open': 'double'
        }

        result = handler._get_schema_fields('stock_5min', 'v1')
        assert result == {'date', 'code', 'open'}

    def test_get_schema_fields_error(self):
        """测试 _get_schema_fields 异常情况"""
        from app.handlers.handler_factory import DataHandler

        handler = object.__new__(DataHandler)
        handler.sm = MagicMock()
        handler.sm.get_data_schema.side_effect = Exception("Schema not found")

        result = handler._get_schema_fields('invalid', 'v1')
        assert result is None

    def test_refresh_known_types(self):
        """测试 _refresh_known_types 方法"""
        from app.handlers.handler_factory import DataHandler

        handler = object.__new__(DataHandler)

        handler.sm = MagicMock()
        handler.sm.list_schemas.return_value = [
            {'name': 'stock_5min'},
            {'name': 'stock_1day'},
        ]

        handler.KNOWN_TYPES = []  # 初始为空
        handler._refresh_known_types()

        assert 'stock_5min' in handler.KNOWN_TYPES
        assert 'stock_1day' in handler.KNOWN_TYPES

    def test_refresh_known_types_error(self):
        """测试 _refresh_known_types 异常情况"""
        from app.handlers.handler_factory import DataHandler

        handler = object.__new__(DataHandler)
        handler.sm = MagicMock()
        handler.sm.list_schemas.side_effect = Exception("Scan error")

        handler.KNOWN_TYPES = ['old_type']
        handler._refresh_known_types()

        # 应该保留默认值
        assert 'old_type' in handler.KNOWN_TYPES


class TestParseFiltersIntegration:
    """集成测试：parse_filters 与 DataHandler 配合"""

    def test_parse_filters_with_valid_fields(self):
        """测试与 DataHandler 配合使用"""
        from app.handlers.handler_factory import parse_filters

        # Mock request args
        args = MagicMock()
        args.items.return_value = [
            ('f_date', '2026-05-19'),
            ('f_market', 'XHKG'),
        ]

        # 合法字段
        valid_fields = {'date', 'market', 'code'}

        filters, warnings = parse_filters(args, valid_fields=valid_fields)

        assert filters['date'] == '2026-05-19'
        assert filters['market'] == 'XHKG'
        assert len(warnings) == 0

    def test_parse_filters_rejects_invalid(self):
        """测试拒绝非法字段"""
        from app.handlers.handler_factory import parse_filters

        args = MagicMock()
        args.items.return_value = [
            ('f_invalid', 'value'),
        ]

        filters, warnings = parse_filters(args, valid_fields={'date'})

        assert len(filters) == 0
        assert len(warnings) == 1
