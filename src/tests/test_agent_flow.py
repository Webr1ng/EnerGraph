"""test_agent_flow — Agent 本地服务完整链路手动测试

所属层：tests
依赖：json, os, pytest, requests
对接算法层：N/A（本地 FastAPI 服务）
"""
import json
import os

import pytest
import requests

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_AGENT_TESTS") != "1",
    reason="需要先启动本地 API 服务；默认测试集跳过现场链路测试",
)


def test_agent_stream():
    """测试 Agent SSE 流式响应"""
    url = "http://localhost:8000/stream"

    payload = {
        "user_input": "今天江北工厂的用电量是多少？",
        "page_context": {
            "current_route": "/index/index",
            "site_id": "FJJB000001"
        }
    }

    print("🚀 发送请求到 Agent...")
    print(f"   输入: {payload['user_input']}")
    print(f"   站点: {payload['page_context']['site_id']}")
    print("=" * 60)

    response = requests.post(url, json=payload, stream=True, timeout=60)

    text_parts = []
    actions = []

    for line in response.iter_lines():
        if not line:
            continue

        line = line.decode('utf-8')

        if line.startswith('event:'):
            event_type = line.split(':', 1)[1].strip()
        elif line.startswith('data:'):
            data_str = line.split(':', 1)[1].strip()
            data = json.loads(data_str)

            if event_type == 'text':
                text_parts.append(data['text'])
                print(data['text'], end='', flush=True)

            elif event_type == 'action':
                actions.append(data)
                print(f"\n\n🎯 跳转指令: {data}")

            elif event_type == 'done':
                print("\n\n✅ Agent 响应完成")
                break

    print("=" * 60)
    print(f"📊 汇总:")
    print(f"   - 文本长度: {len(''.join(text_parts))} 字符")
    print(f"   - 跳转指令: {len(actions)} 条")

    if actions:
        action = actions[0]
        print(f"\n🔗 前端应执行:")
        print(f"   router.push({{")
        print(f"     path: '{action['route']}',")
        print(f"     query: {action['params']}")
        print(f"   }})")

if __name__ == "__main__":
    test_agent_stream()
