"""test_navigation — 导航动作手动检查脚本

所属层：tests
依赖：src.graph.builder
对接算法层：N/A（通过 graph 间接调用）
"""
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from src.graph.builder import graph


def run_navigation_check() -> None:
    """手动检查能耗查询是否生成跳转动作。"""
    result = graph.invoke({
        "user_input": "今天江北工厂的用电量是多少？",
        "page_context": {
            "current_route": "/index/index",
            "site_id": "FJJB000001",
        },
    })

    print("\n=== AgentState 返回结果 ===")
    print(f"pending_actions: {result.get('pending_actions')}")
    print(f"final_report 长度: {len(result.get('final_report', ''))}")

    if result.get("pending_actions"):
        print("\n✅ 生成了跳转动作:")
        for action in result["pending_actions"]:
            print(f"  类型: {action.type if hasattr(action, 'type') else action.get('type')}")
            print(f"  路由: {action.route if hasattr(action, 'route') else action.get('route')}")
            print(f"  参数: {action.params if hasattr(action, 'params') else action.get('params')}")
    else:
        print("\n❌ 没有生成跳转动作")


if __name__ == "__main__":
    run_navigation_check()
