"""
API Integration Tests - DataCenter RESTful API
使用 Flask test client 测试所有 API 端点
"""

import os
import sys
import json
import time
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _make_sample_record(offset_hours=0):
    """创建测试记录，使用时间戳确保唯一性"""
    ts = int(time.time()) + offset_hours * 3600
    date_str = f"2099-{ts % 12 + 1:02d}-{ts % 28 + 1:02d}"
    return {
        "Year": date_str[:4],
        "Month": date_str[5:7],
        "date": date_str,
        "time": f"{ts % 24:02d}:00",
        "market": "XHKG",
        "stock_code": "00700",
        "stock_name": "腾讯控股",
        "open": 500.0,
        "close": 501.0,
        "high": 502.0,
        "low": 499.0,
        "volume": 100000
    }


@pytest.fixture
def client():
    """创建 Flask test client"""
    # 保存原有环境变量
    old_data_dir = os.environ.get('DATACENTER_DATA_DIR')
    old_schemas_dir = os.environ.get('DATACENTER_SCHEMAS_DIR')

    # 设置测试环境变量
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # DataCenter/tests
    _project_root = os.path.dirname(_root)  # DataCenter
    os.environ['DATACENTER_DATA_DIR'] = os.path.join(_project_root, 'CTtest', 'data')
    os.environ['DATACENTER_SCHEMAS_DIR'] = os.path.join(_project_root, 'schemas')

    sys.path.insert(0, os.path.dirname(_root))  # DataCenter

    from run_api import create_app
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

    # 恢复原有环境变量
    if old_data_dir is not None:
        os.environ['DATACENTER_DATA_DIR'] = old_data_dir
    else:
        os.environ.pop('DATACENTER_DATA_DIR', None)

    if old_schemas_dir is not None:
        os.environ['DATACENTER_SCHEMAS_DIR'] = old_schemas_dir
    else:
        os.environ.pop('DATACENTER_SCHEMAS_DIR', None)


@pytest.fixture
def api_base():
    return '/api/v1'


class TestRootAndHealth:
    """根路径和健康检查"""

    def test_root(self, client):
        rv = client.get('/')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['status'] == 'running'
        assert 'version' in data

    def test_health(self, client):
        rv = client.get('/health')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['status'] == 'healthy'


class TestSchemaEndpoint:
    """GET /api/v1/data/{data_type}/schemas"""

    def test_get_schemas_success(self, client, api_base):
        rv = client.get(f'{api_base}/stock_5min/schemas')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['success'] is True
        assert data['data_type'] == 'stock_5min'
        assert len(data['schemas']) >= 1
        schema = data['schemas'][0]
        assert schema['name'] == 'stock_5min'
        assert 'storage_rule' in schema

    def test_get_schemas_not_found(self, client, api_base):
        rv = client.get(f'{api_base}/nonexistent_type/schemas')
        assert rv.status_code == 404
        data = json.loads(rv.data)
        assert data['success'] is False

    def test_get_schemas_all_types(self, client, api_base):
        for dt in ['stock_5min', 'stock_30min', 'stock_60min', 'stock_1day']:
            rv = client.get(f'{api_base}/{dt}/schemas')
            assert rv.status_code == 200, f"{dt} schemas failed"
            data = json.loads(rv.data)
            assert data['count'] >= 1


class TestStatsEndpoint:
    """GET /api/v1/data/{data_type}/stats"""

    def test_get_stats_success(self, client, api_base):
        rv = client.get(f'{api_base}/stock_5min/stats')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['success'] is True
        assert 'total_files' in data['stats']
        assert 'total_rows' in data['stats']
        assert 'total_size_bytes' in data['stats']
        assert 'total_size_mb' in data['stats']

    def test_get_stats_all_types(self, client, api_base):
        for dt in ['stock_5min', 'stock_30min', 'stock_60min', 'stock_1day']:
            rv = client.get(f'{api_base}/{dt}/stats')
            assert rv.status_code == 200, f"{dt} stats failed"
            data = json.loads(rv.data)
            assert data['stats']['data_type'] == dt


class TestGetEndpoint:
    """GET /api/v1/data/{data_type}"""

    def test_get_no_filter(self, client, api_base):
        rv = client.get(f'{api_base}/stock_5min')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['success'] is True
        assert 'data' in data
        assert 'metadata' in data

    def test_get_filter_by_date_single(self, client, api_base):
        rv = client.get(f'{api_base}/stock_5min?date=2026-05-22')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['success'] is True
        # 可能没有数据，但不应该报错
        assert 'data' in data

    def test_get_filter_by_market(self, client, api_base):
        rv = client.get(f'{api_base}/stock_5min?f_market=XHKG')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['success'] is True
        # 验证过滤器被正确应用
        if data['data']:
            for row in data['data']:
                assert row['market'] == 'XHKG'

    def test_get_filter_by_stock_code(self, client, api_base):
        rv = client.get(f'{api_base}/stock_5min?f_stock_code=00700')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['success'] is True
        # 验证过滤器被正确应用
        if data['data']:
            for row in data['data']:
                assert row['stock_code'] == '00700'

    def test_get_filter_combined(self, client, api_base):
        rv = client.get(f'{api_base}/stock_5min?f_market=XHKG&f_stock_code=00700')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert 'data' in data
        assert data['success'] is True

    def test_get_schema_not_found(self, client, api_base):
        rv = client.get(f'{api_base}/nonexistent_type')
        assert rv.status_code == 404
        data = json.loads(rv.data)
        assert data['success'] is False


class TestPostEndpoint:
    """POST /api/v1/data/{data_type}"""

    def test_post_success(self, client, api_base):
        sample = _make_sample_record()
        rv = client.post(
            f'{api_base}/stock_5min',
            json={
                "version": "v1",
                "data": [sample]
            },
            content_type='application/json'
        )
        assert rv.status_code == 201
        data = json.loads(rv.data)
        assert data['success'] is True
        assert data['message'] == 'Data written successfully'
        assert 'file_paths' in data['details']
        assert data['details']['total_rows'] == 1

    def test_post_empty_data(self, client, api_base):
        rv = client.post(
            f'{api_base}/stock_5min',
            json={"version": "v1", "data": []},
            content_type='application/json'
        )
        assert rv.status_code == 400
        data = json.loads(rv.data)
        assert data['success'] is False

    def test_post_empty_body(self, client, api_base):
        rv = client.post(
            f'{api_base}/stock_5min',
            data='',
            content_type='application/json'
        )
        assert rv.status_code == 400

    def test_post_schema_not_found(self, client, api_base):
        rv = client.post(
            f'{api_base}/nonexistent_type',
            json={"version": "v1", "data": [_make_sample_record()]},
            content_type='application/json'
        )
        assert rv.status_code == 404


class TestPutEndpoint:
    """PUT /api/v1/data/{data_type}（受 ALLOW_PUT 控制）"""

    def test_put_disabled_returns_405(self, client, api_base):
        rv = client.put(
            f'{api_base}/stock_5min',
            json={"version": "v1", "data": []},
            content_type='application/json'
        )
        assert rv.status_code == 405
        data = json.loads(rv.data)
        assert data['success'] is False
        assert 'disabled by configuration' in data['error']


class TestDeleteEndpoint:
    """DELETE /api/v1/data/{data_type}（受 ALLOW_DELETE 控制）"""

    def test_delete_disabled_returns_405(self, client, api_base):
        rv = client.delete(f'{api_base}/stock_5min?date=2026-05-15')
        assert rv.status_code == 405
        data = json.loads(rv.data)
        assert data['success'] is False
        assert 'disabled by configuration' in data['error']

    def test_delete_requires_filter(self, client, api_base):
        rv = client.delete(f'{api_base}/stock_5min')
        # ALLOW_DELETE=False 时直接返回 405，不会走到 filter 检查
        assert rv.status_code == 405


class TestFilterEndpoint:
    """Filter 参数测试"""

    def test_filter_date_range(self, client, api_base):
        """日期范围过滤: f_date=2026-05-01~2026-05-31"""
        rv = client.get(f'{api_base}/stock_5min?f_date=2026-05-01~2026-05-31')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['success'] is True

    def test_filter_date_range_open_start(self, client, api_base):
        """开放式过滤（只有 end）: f_date=~2026-05-31"""
        rv = client.get(f'{api_base}/stock_5min?f_date=~2026-05-31')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['success'] is True

    def test_filter_date_range_open_end(self, client, api_base):
        """开放式过滤（只有 start）: f_date=2026-05-01~"""
        rv = client.get(f'{api_base}/stock_5min?f_date=2026-05-01~')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['success'] is True

    def test_filter_enumeration(self, client, api_base):
        """枚举过滤: f_stock_code=00700,09988"""
        rv = client.get(f'{api_base}/stock_5min?f_stock_code=00700,09988')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['success'] is True

    def test_filter_unknown_field(self, client, api_base):
        """未知字段过滤应返回警告"""
        rv = client.get(f'{api_base}/stock_5min?f_unknown_field=value')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['success'] is True
        # metadata 中应包含 warnings
        if 'warnings' in data['metadata']:
            assert len(data['metadata']['warnings']) > 0

    def test_filter_with_version(self, client, api_base):
        """带 version 参数的过滤"""
        rv = client.get(f'{api_base}/stock_5min?version=v1&f_market=XHKG')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['success'] is True
        assert data['metadata']['version'] == 'v1'

    def test_get_file_not_found(self, client, api_base):
        """数据不存在时返回空列表"""
        rv = client.get(f'{api_base}/stock_5min?f_date=2099-01-01')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['success'] is True
        assert data['data'] == []
        assert data['metadata']['total_rows'] == 0


class TestErrorHandling:
    """错误处理测试"""

    def test_get_internal_error(self, client, api_base):
        """内部错误处理"""
        # 这个测试比较难触发，因为我们无法轻易让核心模块抛出异常
        # 暂时跳过
        pass

    def test_post_validation_error(self, client, api_base):
        """数据验证失败"""
        rv = client.post(
            f'{api_base}/stock_5min',
            json={
                "version": "v1",
                "data": [{"invalid": "data"}]  # 缺少必需字段
            },
            content_type='application/json'
        )
        assert rv.status_code == 400
        data = json.loads(rv.data)
        assert data['success'] is False
        assert 'error' in data

    def test_post_multiple_records(self, client, api_base):
        """POST 多条记录"""
        records = [_make_sample_record(i) for i in range(2)]
        rv = client.post(
            f'{api_base}/stock_5min',
            json={
                "version": "v1",
                "data": records
            },
            content_type='application/json'
        )
        assert rv.status_code == 201
        data = json.loads(rv.data)
        assert data['success'] is True
        assert data['details']['total_rows'] == 2
