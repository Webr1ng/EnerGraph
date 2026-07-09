"""test_performance_benchmark — 验证 T13 性能采样与聚合

所属层：tests
依赖：httpx, benchmarks.runners.run_performance
对接算法层：N/A
"""
import json

import httpx

from benchmarks.runners.run_performance import (
    PerformanceSample,
    percentile,
    run_agent_request,
    run_stream_request,
    summarize,
)


def test_percentile_uses_linear_interpolation() -> None:
    """P50/P95/P99 应使用稳定的线性插值。"""
    assert percentile([10, 20, 30], 0.5) == 20
    assert percentile([], 0.99) == 0


def test_stream_request_records_ttft_total_and_usage() -> None:
    """流式采样应解析首 token 与最终 usage。"""
    chunks = [
        {"choices": [{"delta": {"content": "答"}}]},
        {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 3}},
    ]
    body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, text=body))
    with httpx.Client(transport=transport) as client:
        sample = run_stream_request(
            client, base_url="http://test/v1", model="local", bucket="single_turn",
            prompt="hello", concurrency=1, max_tokens=16,
        )
    assert sample.success is True
    assert sample.total_ms >= sample.ttft_ms >= 0
    assert sample.first_text_ms is not None
    assert (sample.input_tokens, sample.output_tokens) == (12, 3)


def test_summary_groups_concurrency_and_bucket() -> None:
    """报告应同时按并发阶梯和工作负载桶聚合。"""
    samples = [
        PerformanceSample("single_turn", 1, 10, 20, 5, 2, True),
        PerformanceSample("multi_intent", 2, 30, 50, 8, 4, True),
    ]
    result = summarize(samples)
    assert set(result["by_concurrency"]) == {"1", "2"}
    assert result["overall"]["success_rate"] == 1.0
    assert result["by_bucket"]["single_turn"]["input_tokens"] == 5


def test_agent_request_requires_text_and_done_events() -> None:
    """Agent 采样应以首个 text 为 TTFT，并要求流包含 done。"""
    body = "event: thinking\ndata: {}\n\nevent: text\ndata: {\"text\":\"ok\"}\n\nevent: done\ndata: {}\n\n"
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, text=body))
    with httpx.Client(transport=transport) as client:
        sample = run_agent_request(
            client, agent_url="http://test", bucket="single_turn", prompt="hello", concurrency=1,
        )
    assert sample.success is True
    assert sample.total_ms >= sample.ttft_ms >= 0
