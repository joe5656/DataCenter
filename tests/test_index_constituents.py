#!/usr/bin/env python3
"""
测试 index_constituents 数据类型
"""
import requests
import json

BASE_URL = "http://192.168.31.32:8080/api/v1"

# 测试数据：恒生科技指数 2026-05-19 成分股
test_data = {
    "data": [
        {
            "index_code": "hstech",
            "index_name_en": "Hang Seng TECH Index",
            "index_name_cn": "恒生科技指数",
            "date": "2026-05-19",
            "Year": 2026,
            "Month": 5,
            "stock_code": "00700",
            "stock_name": "腾讯控股"
        },
        {
            "index_code": "hstech",
            "index_name_en": "Hang Seng TECH Index",
            "index_name_cn": "恒生科技指数",
            "date": "2026-05-19",
            "Year": 2026,
            "Month": 5,
            "stock_code": "09988",
            "stock_name": "阿里巴巴"
        },
        {
            "index_code": "hstech",
            "index_name_en": "Hang Seng TECH Index",
            "index_name_cn": "恒生科技指数",
            "date": "2026-05-19",
            "Year": 2026,
            "Month": 5,
            "stock_code": "01810",
            "stock_name": "小米集团"
        }
    ]
}

print("=== 测试 1: POST 写入指数成分股数据 ===")
resp = requests.post(
    f"{BASE_URL}/index_constituents",
    json=test_data,
    headers={"Content-Type": "application/json"}
)
print(f"Status: {resp.status_code}")
print(json.dumps(resp.json(), indent=2, ensure_ascii=False))

if resp.status_code == 201:
    print("\n=== 测试 2: GET 查询数据 ===")
    resp2 = requests.get(
        f"{BASE_URL}/index_constituents",
        params={
            "f_index_code": "hstech",
            "f_date": "2026-05-19"
        }
    )
    print(f"Status: {resp2.status_code}")
    print(json.dumps(resp2.json(), indent=2, ensure_ascii=False))

    print("\n=== 测试 3: 验证存储路径 ===")
    # 检查 NAS 上的文件
    import subprocess
    cmd = """expect << 'EOF'
spawn ssh -p 9222 -o StrictHostKeyChecking=no joezhou@192.168.31.32
expect "password:"
send "Badytoy56\\r"
expect "#"
send "ls -lh /volume2/datacenter/index_constituents/\\r"
expect "#"
send "exit\\r"
expect eof
EOF"""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    print(result.stdout)

print("\n=== 测试 4: GET /schemas ===")
resp3 = requests.get(f"{BASE_URL}/index_constituents/schemas")
print(f"Status: {resp3.status_code}")
print(json.dumps(resp3.json(), indent=2, ensure_ascii=False))

print("\n=== 测试 5: GET /stats ===")
resp4 = requests.get(f"{BASE_URL}/index_constituents/stats")
print(f"Status: {resp4.status_code}")
print(json.dumps(resp4.json(), indent=2, ensure_ascii=False))
