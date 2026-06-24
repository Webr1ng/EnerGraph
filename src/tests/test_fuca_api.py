"""test_fuca_api — 福加 API 工具现场接口手动检查脚本

所属层：tests
依赖：json, os, pytest, src.tools.java_backend
对接算法层：N/A（福加 REST API）
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

# 添加项目根目录到 Python 路径
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from src.tools.java_backend import fetch_energy_summary

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_FUCA_API_TESTS") != "1",
    reason="需要可访问福加真实 API；默认测试集跳过现场接口测试",
)


def test_energy_api():
    """测试能耗查询接口"""
    site_id = "FJJB000001"
    date = datetime.now().strftime("%Y-%m-%d")

    print(f"🔍 测试福加 API - 能耗查询")
    print(f"   站点: {site_id}")
    print(f"   日期: {date}")
    print("-" * 60)

    result = fetch_energy_summary(site_id=site_id, date=date)

    if "error" in result:
        print(f"❌ 调用失败: {result['error']}")
        assert False, result["error"]

    print("✅ 调用成功！返回数据：")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    assert result["site_id"] == site_id

if __name__ == "__main__":
    try:
        test_energy_api()
    except AssertionError:
        sys.exit(1)
    sys.exit(0)
