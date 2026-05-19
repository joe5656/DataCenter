"""
parse_filters 单元测试 — 验证 f_ 前缀解析、值格式、字段校验
"""

import pytest
from unittest.mock import MagicMock


# 直接导入 parse_filters（无需 Flask app）
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'app', 'handlers'))
from handler_factory import parse_filters


class TestParseFiltersBasic:
    """基础解析：f_ 前缀识别"""

    def test_no_f_prefix_ignored(self):
        """无 f_ 前缀的参数被忽略"""
        args = MagicMock()
        args.items.return_value = [('version', 'v1'), ('date', '2026-05-19')]
        filters, warnings = parse_filters(args)
        assert filters == {}
        assert warnings == []

    def test_f_prefix_extracted(self):
        """f_ 前缀参数被提取，字段名去掉前缀"""
        args = MagicMock()
        args.items.return_value = [('f_date', '2026-05-19')]
        filters, warnings = parse_filters(args)
        assert 'date' in filters
        assert filters['date'] == '2026-05-19'

    def test_multiple_filters(self):
        """多个 filter 参数"""
        args = MagicMock()
        args.items.return_value = [
            ('f_date', '2026-05-19'),
            ('f_market', 'XHKG'),
            ('f_stock_code', '00700'),
        ]
        filters, warnings = parse_filters(args)
        assert len(filters) == 3
        assert filters['date'] == '2026-05-19'
        assert filters['market'] == 'XHKG'
        assert filters['stock_code'] == '00700'


class TestParseFiltersSingleValue:
    """单值格式"""

    def test_single_string(self):
        args = MagicMock()
        args.items.return_value = [('f_date', '2026-05-19')]
        filters, _ = parse_filters(args)
        assert filters['date'] == '2026-05-19'
        assert isinstance(filters['date'], str)

    def test_single_numeric_string(self):
        args = MagicMock()
        args.items.return_value = [('f_close', '490.5')]
        filters, _ = parse_filters(args)
        assert filters['close'] == '490.5'


class TestParseFiltersEnum:
    """枚举格式：逗号分隔"""

    def test_two_values(self):
        args = MagicMock()
        args.items.return_value = [('f_stock_code', '00700,09988')]
        filters, _ = parse_filters(args)
        assert filters['stock_code'] == ['00700', '09988']

    def test_three_values(self):
        args = MagicMock()
        args.items.return_value = [('f_stock_code', '00700,09988,00941')]
        filters, _ = parse_filters(args)
        assert filters['stock_code'] == ['00700', '09988', '00941']

    def test_enum_with_spaces(self):
        """枚举值两端空格被 trim"""
        args = MagicMock()
        args.items.return_value = [('f_stock_code', '00700 , 09988 , 00941')]
        filters, _ = parse_filters(args)
        assert filters['stock_code'] == ['00700', '09988', '00941']

    def test_enum_empty_segments_skipped(self):
        """空段被跳过"""
        args = MagicMock()
        args.items.return_value = [('f_stock_code', '00700,,09988,')]
        filters, _ = parse_filters(args)
        assert filters['stock_code'] == ['00700', '09988']


class TestParseFiltersRange:
    """范围格式：波浪线分隔"""

    def test_full_range(self):
        args = MagicMock()
        args.items.return_value = [('f_date', '2026-05-01~2026-05-19')]
        filters, _ = parse_filters(args)
        assert filters['date'] == {'start': '2026-05-01', 'end': '2026-05-19'}

    def test_open_start(self):
        """小于等于：~value"""
        args = MagicMock()
        args.items.return_value = [('f_volume', '~1000000')]
        filters, _ = parse_filters(args)
        assert filters['volume'] == {'end': '1000000'}
        assert 'start' not in filters['volume']

    def test_open_end(self):
        """大于等于：value~"""
        args = MagicMock()
        args.items.return_value = [('f_close', '400~')]
        filters, _ = parse_filters(args)
        assert filters['close'] == {'start': '400'}
        assert 'end' not in filters['close']

    def test_numeric_range(self):
        args = MagicMock()
        args.items.return_value = [('f_close', '400~500')]
        filters, _ = parse_filters(args)
        assert filters['close'] == {'start': '400', 'end': '500'}


class TestParseFiltersValidation:
    """字段校验：valid_fields 参数"""

    def test_valid_field_accepted(self):
        args = MagicMock()
        args.items.return_value = [('f_date', '2026-05-19')]
        filters, warnings = parse_filters(args, valid_fields={'date', 'market', 'stock_code'})
        assert 'date' in filters
        assert warnings == []

    def test_invalid_field_rejected(self):
        """非法字段被过滤掉"""
        args = MagicMock()
        args.items.return_value = [('f_ticker', '00700')]
        filters, warnings = parse_filters(args, valid_fields={'date', 'market', 'stock_code'})
        assert 'ticker' not in filters
        assert len(warnings) == 1
        assert 'ticker' in warnings[0]

    def test_mixed_valid_invalid(self):
        """混合合法/非法字段：合法保留，非法过滤"""
        args = MagicMock()
        args.items.return_value = [
            ('f_date', '2026-05-19'),
            ('f_ticker', '00700'),
            ('f_foo', 'bar'),
            ('f_market', 'XHKG'),
        ]
        filters, warnings = parse_filters(args, valid_fields={'date', 'market', 'stock_code'})
        assert 'date' in filters
        assert 'market' in filters
        assert 'ticker' not in filters
        assert 'foo' not in filters
        assert len(warnings) == 2

    def test_no_validation(self):
        """valid_fields=None 时不校验，全部接受"""
        args = MagicMock()
        args.items.return_value = [
            ('f_date', '2026-05-19'),
            ('f_anything', 'value'),
        ]
        filters, warnings = parse_filters(args, valid_fields=None)
        assert len(filters) == 2
        assert warnings == []

    def test_empty_valid_fields(self):
        """valid_fields 为空集合时所有 f_ 参数都非法"""
        args = MagicMock()
        args.items.return_value = [('f_date', '2026-05-19')]
        filters, warnings = parse_filters(args, valid_fields=set())
        assert filters == {}
        assert len(warnings) == 1


class TestParseFiltersEdgeCases:
    """边界情况"""

    def test_empty_args(self):
        args = MagicMock()
        args.items.return_value = []
        filters, warnings = parse_filters(args)
        assert filters == {}
        assert warnings == []

    def test_only_system_params(self):
        args = MagicMock()
        args.items.return_value = [('version', 'v1'), ('page', '1')]
        filters, warnings = parse_filters(args)
        assert filters == {}

    def test_value_with_special_chars(self):
        """值含 URL 编码字符"""
        args = MagicMock()
        args.items.return_value = [('f_stock_name', '%E8%85%BE%E8%AE%AF')]
        filters, _ = parse_filters(args)
        assert filters['stock_name'] == '%E8%85%BE%E8%AE%AF'

    def test_tilde_priority_over_comma(self):
        """值同时含 ~ 和 , 时，~ 优先（范围格式）"""
        args = MagicMock()
        args.items.return_value = [('f_date', '2026-05-01~2026-05-02,2026-05-03')]
        filters, _ = parse_filters(args)
        assert 'start' in filters['date']  # 解析为范围，非枚举
