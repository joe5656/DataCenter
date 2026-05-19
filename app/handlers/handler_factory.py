"""
Handler factory — DataCenter RESTful API Handler

接口约定（供 DynamicLoader 导入）：
    handlers.handler_factory:DataHandler

Filter 参数格式（v1.1）：
    所有 filter 参数使用 f_ 前缀，无前缀的为系统参数。
    值格式：
        单值:  f_date=2026-05-19
        枚举:  f_stock_code=00700,09988
        范围:  f_date=2026-05-01~2026-05-19
        大于等于: f_close=400~
        小于等于: f_volume=~1000000
"""
import os
import re
import logging
from flask import jsonify, request, Flask

logger = logging.getLogger(__name__)


def parse_filters(args, valid_fields: set = None) -> tuple:
    """从 request.args 解析 f_ 前缀的 filter 参数。

    参数:
        args: Flask request.args
        valid_fields: 合法字段集合，None 时不校验

    返回: (filters, warnings)
        filters: dict，值为三种格式之一：
            str              — 单值
            list[str]        — 枚举
            dict(start,end)  — 范围（start/end 可缺省）
        warnings: list[str]，被过滤掉的非法字段
    """
    filters = {}
    warnings = []

    for key, raw in args.items(multi=True):
        if not key.startswith('f_'):
            continue
        field = key[2:]  # 去掉 f_ 前缀

        # 校验字段是否合法
        if valid_fields is not None and field not in valid_fields:
            warnings.append(f"Unknown filter field '{field}', ignored")
            logger.warning(f"Unknown filter field '{field}', ignored")
            continue

        if '~' in raw:
            # 范围格式
            parts = raw.split('~', 1)
            start = parts[0] if parts[0] else None
            end = parts[1] if parts[1] else None
            filters[field] = {}
            if start is not None:
                filters[field]['start'] = start
            if end is not None:
                filters[field]['end'] = end
        elif ',' in raw:
            # 枚举格式
            filters[field] = [v.strip() for v in raw.split(',') if v.strip()]
        else:
            # 单值
            filters[field] = raw

    return filters, warnings


# ----------------------------------------------------------------
# Handler 类 — 供 DynamicLoader 实例化
# ----------------------------------------------------------------
class DataHandler:
    """DataCenter 数据读写 Handler

    每个 HTTP 方法内部从 request.path 解析 data_type：
        /api/v1/stock_5min        → stock_5min
        /api/v1/stock_5min/schemas → stock_5min
        /api/v1/stock_5min/stats  → stock_5min
    """

    # 预注册的数据类型（运行时从 schemas/ 目录扫描得到）
    KNOWN_TYPES = ['stock_5min', 'stock_30min', 'stock_60min', 'stock_1day']

    def __init__(self):
        """初始化 DataCenter 核心模块（仅执行一次）"""
        import sys
        _base_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _base_root not in sys.path:
            sys.path.insert(0, _base_root)

        from DataCenter.app.config import Config
        from DataCenter.app.schema_manager import SchemaManager
        from DataCenter.app.index_manager import IndexManager
        from DataCenter.app.storage_manager import StorageManager
        from DataCenter.app.data_processor import DataProcessor

        schemas_dir = os.environ.get('DATACENTER_SCHEMAS_DIR', '/app/schemas')
        data_dir = os.environ.get('DATACENTER_DATA_DIR', '/app/data')

        self.config = Config()
        self.sm = SchemaManager(schemas_dir)
        self.st = StorageManager(compression=self.config.COMPRESSION)
        self.im = IndexManager(self.sm)
        self.dp = DataProcessor(self.sm, self.im, self.st)

        self._refresh_known_types()

    def _refresh_known_types(self):
        """从 SchemaManager 动态获取已注册的数据类型"""
        try:
            schemas = self.sm.list_schemas()
            self.KNOWN_TYPES = [s['name'] for s in schemas]
            logger.info(f"DataHandler initialized, known types: {self.KNOWN_TYPES}")
        except Exception:
            logger.warning("Could not scan schemas, using defaults")

    def _get_schema_fields(self, data_type: str, version: str = 'v1') -> set:
        """从 SchemaManager 获取指定 data_type 的合法字段集合"""
        try:
            data_schema = self.sm.get_data_schema(data_type, version)
            if data_schema:
                return set(data_schema.keys())
        except Exception:
            pass
        return None  # 无法获取 schema 时不校验

    def _extract_data_type(self) -> str:
        """从 request.path 提取 data_type（如 stock_5min）"""
        path = request.path.rstrip('/')
        for dt in self.KNOWN_TYPES:
            if path == f'/api/v1/{dt}' or path.startswith(f'/api/v1/{dt}/'):
                return dt
        m = re.match(r'^/api/v1/([^/]+)', path)
        if m:
            return m.group(1)
        return ''

    # ----------------------------------------------------------------
    # HTTP 方法
    # ----------------------------------------------------------------

    def get(self):
        """GET /api/v1/<data_type> — 查询数据
        GET /api/v1/<data_type>/schemas — Schema 版本信息
        GET /api/v1/<data_type>/stats — 存储统计
        """
        data_type = self._extract_data_type()
        path = request.path.rstrip('/')

        if path.endswith('/schemas'):
            return self.schemas()
        if path.endswith('/stats'):
            return self.stats()

        import pandas as pd
        if not data_type or data_type not in self.KNOWN_TYPES:
            return jsonify({'success': False, 'error': f'Schema not found: {data_type}'}), 404

        version = request.args.get('version', 'v1')
        valid_fields = self._get_schema_fields(data_type, version)
        filters, warnings = parse_filters(request.args, valid_fields)

        try:
            df = self.dp.read_data(data_type, version, **filters)
            result = {
                'success': True,
                'data': df.to_dict(orient='records'),
                'metadata': {
                    'data_type': data_type,
                    'version': version,
                    'total_rows': len(df),
                    'filters': filters
                }
            }
            if warnings:
                result['metadata']['warnings'] = warnings
            return jsonify(result)
        except FileNotFoundError:
            return jsonify({
                'success': True,
                'data': [],
                'metadata': {
                    'data_type': data_type,
                    'version': version,
                    'total_rows': 0,
                    'filters': filters,
                    'message': 'No matching data found'
                }
            })
        except Exception as e:
            logger.error(f"GET error: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    def post(self):
        """POST /api/v1/<data_type> — 写入数据"""
        import pandas as pd
        data_type = self._extract_data_type()
        if not data_type or data_type not in self.KNOWN_TYPES:
            return jsonify({'success': False, 'error': f'Schema not found: {data_type}'}), 404

        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

        version = payload.get('version', 'v1')
        data_list = payload.get('data', [])
        if not data_list:
            return jsonify({'success': False, 'error': '"data" field is required and must not be empty'}), 400

        try:
            df = pd.DataFrame(data_list)
            result = self.dp.write_data(df, data_type, version)
            if not result.get('success', True):
                return jsonify({
                    'success': False,
                    'error': 'Data validation failed',
                    'details': result.get('errors', [])
                }), 400
            return jsonify({
                'success': True,
                'message': 'Data written successfully',
                'details': {
                    'data_type': data_type,
                    'version': version,
                    'total_rows': result.get('total_rows', len(df)),
                    'files_written': result.get('files_written', 0),
                    'file_paths': result.get('file_paths', []),
                    'duplicates_found': result.get('duplicates_found', 0),
                    'duplicates_removed': result.get('duplicates_removed', 0),
                }
            }), 201
        except ValueError as e:
            return jsonify({'success': False, 'error': f'Validation error: {e}'}), 400
        except Exception as e:
            logger.error(f"POST error: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    def put(self):
        """PUT /api/v1/<data_type> — 全量覆盖（受 ALLOW_PUT 控制）"""
        import pandas as pd
        data_type = self._extract_data_type()
        if not data_type or data_type not in self.KNOWN_TYPES:
            return jsonify({'success': False, 'error': f'Schema not found: {data_type}'}), 404

        if not self.config.ALLOW_PUT:
            return jsonify({'success': False, 'error': 'PUT operation is disabled by configuration'}), 405

        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({'success': False, 'error': 'Request body is required'}), 400

        version = payload.get('version', 'v1')
        data_list = payload.get('data', [])
        if not data_list:
            return jsonify({'success': False, 'error': '"data" field is required'}), 400

        try:
            df = pd.DataFrame(data_list)
            result = self.dp.write_data(df, data_type, version, mode='overwrite')
            if not result.get('success', True):
                return jsonify({
                    'success': False,
                    'error': 'Data validation failed',
                    'details': result.get('errors', [])
                }), 400
            return jsonify({
                'success': True,
                'message': 'Data updated successfully',
                'details': {
                    'data_type': data_type,
                    'version': version,
                    'total_rows': result.get('total_rows', len(df)),
                    'files_written': result.get('files_written', 0),
                    'file_paths': result.get('file_paths', []),
                }
            })
        except Exception as e:
            logger.error(f"PUT error: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    def delete(self):
        """DELETE /api/v1/<data_type> — 删除文件（受 ALLOW_DELETE 控制）"""
        data_type = self._extract_data_type()
        if not data_type or data_type not in self.KNOWN_TYPES:
            return jsonify({'success': False, 'error': f'Schema not found: {data_type}'}), 404

        if not self.config.ALLOW_DELETE:
            return jsonify({'success': False, 'error': 'DELETE operation is disabled by configuration'}), 405

        version = request.args.get('version', 'v1')
        valid_fields = self._get_schema_fields(data_type, version)
        filters, warnings = parse_filters(request.args, valid_fields)
        if not filters:
            return jsonify({'success': False, 'error': 'At least one valid filter parameter (f_*) is required'}), 400

        try:
            paths = self.im.get_read_paths(data_type, version, **filters)
            deleted_files = 0
            errors = []
            for rel_path in paths:
                try:
                    abs_path = self.im.to_absolute_path(rel_path)
                    if self.st.delete_parquet(abs_path):
                        deleted_files += 1
                except Exception as e:
                    errors.append({'file': rel_path, 'error': str(e)})
            return jsonify({
                'success': True,
                'message': f'Deleted {deleted_files} file(s)',
                'details': {
                    'data_type': data_type,
                    'version': version,
                    'files_deleted': deleted_files,
                    'filters': filters,
                    'errors': errors if errors else None,
                }
            })
        except Exception as e:
            logger.error(f"DELETE error: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    def schemas(self):
        """GET /api/v1/<data_type>/schemas — Schema 版本信息"""
        data_type = self._extract_data_type()
        if not data_type or data_type not in self.KNOWN_TYPES:
            return jsonify({'success': False, 'error': f'Schema not found: {data_type}'}), 404

        try:
            matching = [s for s in self.sm.list_schemas() if s.get('name') == data_type]
            if not matching:
                return jsonify({'success': False, 'error': f'No schema found: {data_type}'}), 404
            return jsonify({'success': True, 'data_type': data_type, 'schemas': matching, 'count': len(matching)})
        except Exception as e:
            logger.error(f"Schema error: {e}", exc_info=True)
            return jsonify({'success': False, 'error': str(e)}), 500

    def stats(self):
        """GET /api/v1/<data_type>/stats — 存储统计"""
        import pyarrow.parquet as pq
        from glob import glob

        data_type = self._extract_data_type()
        if not data_type or data_type not in self.KNOWN_TYPES:
            return jsonify({'success': False, 'error': f'Schema not found: {data_type}'}), 404

        version = request.args.get('version', 'v1')
        pattern = os.path.join(self.config.DATA_DIR, data_type, '**', '*.parquet')
        files = glob(pattern, recursive=True)
        total_size = 0
        total_rows = 0
        for f in files:
            try:
                pf = pq.ParquetFile(f)
                total_rows += pf.metadata.num_rows
                total_size += os.path.getsize(f)
            except Exception:
                pass
        return jsonify({
            'success': True,
            'stats': {
                'data_type': data_type,
                'version': version,
                'total_files': len(files),
                'total_rows': total_rows,
                'total_size_bytes': total_size,
                'total_size_mb': round(total_size / (1024 * 1024), 2),
            }
        })


# ----------------------------------------------------------------
# 本地独立测试入口
# ----------------------------------------------------------------
def create_standalone_app() -> Flask:
    """创建 DataCenter 独立 Flask 应用（用于本地开发测试）"""
    app = Flask(__name__)
    app.config['JSON_AS_ASCII'] = False
    app.config['JSON_SORT_KEYS'] = False
    app.config['JSONIFY_PRETTYPRINT_REGULAR'] = True

    handler = DataHandler()

    for dt in handler.KNOWN_TYPES:
        base = f'/api/v1/{dt}'
        app.add_url_rule(base, f'get_{dt}', handler.get, methods=['GET'])
        app.add_url_rule(base, f'post_{dt}', handler.post, methods=['POST'])
        app.add_url_rule(base, f'put_{dt}', handler.put, methods=['PUT'])
        app.add_url_rule(base, f'delete_{dt}', handler.delete, methods=['DELETE'])
        app.add_url_rule(f'{base}/schemas', f'schemas_{dt}', handler.schemas, methods=['GET'])
        app.add_url_rule(f'{base}/stats', f'stats_{dt}', handler.stats, methods=['GET'])
        logger.info(f"Registered routes for schema: {dt}")

    @app.route('/')
    def root():
        return jsonify({'message': 'DataCenter RESTful API', 'version': '1.1.0', 'status': 'running'})

    @app.route('/health')
    def health():
        return jsonify({'status': 'healthy', 'data_dir': handler.config.DATA_DIR})

    @app.errorhandler(404)
    def handle_404(e):
        return jsonify({'success': False, 'error': 'Not found'}), 404

    return app
