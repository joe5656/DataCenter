"""
API Integration Tests - DataCenter RESTful API
使用 Flask test client 测试所有 API 端点
"""

import os
import sys
import json
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 设置环境变量
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # DataCenter/tests
_project_root = os.path.dirname(_root)  # DataCenter
os.environ['DATACENTER_DATA_DIR'] = os.path.join(_project_root, 'CTtest', 'data')
os.environ['DATACENTER_SCHEMAS_DIR'] = os.path.join(_project_root, 'schemas')


@pytest.fixture
def client():
    """创建 Flask test client"""
    # 直接导入并创建 app（不启动服务器）
    # tests/api/test_api.py → DataCenter/tests/api → DataCenter/tests → DataCenter
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # DataCenter/tests
    sys.path.insert(0, os.path.dirname(_root))  # DataCenter
    from run_api import create_app
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


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
        rv = client.get(f'{api_base}/stock_5min?market=XHKG')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        for row in data['data']:
            assert row['market'] == 'XHKG'

    def test_get_filter_by_stock_code(self, client, api_base):
        rv = client.get(f'{api_base}/stock_5min?stock_code=00700')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        for row in data['data']:
            assert row['stock_code'] == '00700'

    def test_get_filter_combined(self, client, api_base):
        rv = client.get(f'{api_base}/stock_5min?market=XHKG&stock_code=00700')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert 'data' in data

    def test_get_schema_not_found(self, client, api_base):
        rv = client.get(f'{api_base}/nonexistent_type')
        assert rv.status_code == 404
        data = json.loads(rv.data)
        assert data['success'] is False


class TestPostEndpoint:
    """POST /api/v1/data/{data_type}"""

    SAMPLE_RECORD = {
        "Year": "2026",
        "Month": "05",
        "date": "2026-05-22",
        "time": "09:00",
        "market": "XHKG",
        "stock_code": "00700",
        "stock_name": "腾讯控股",
        "open": 500.0,
        "close": 501.0,
        "high": 502.0,
        "low": 499.0,
        "volume": 100000
    }

    def test_post_success(self, client, api_base):
        rv = client.post(
            f'{api_base}/stock_5min',
            json={
                "version": "v1",
                "data": [self.SAMPLE_RECORD]
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
            json={"version": "v1", "data": [self.SAMPLE_RECORD]},
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
