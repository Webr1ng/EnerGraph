"""run_performance — 本地模型性能、token 与并发阶梯基线

所属层：tests
依赖：httpx, concurrent.futures
对接算法层：本地 OpenAI 兼容 LLM API
"""
import argparse
import json
import math
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import httpx


WORKLOADS: Dict[str, str] = {
    "single_turn": "用一句话说明冷水机组 COP 的含义。",
    "multi_turn": "上下文：用户先问今日能耗，助手回答128.5 kWh。现在简洁复述该数值和单位。",
    "long_context": "请阅读以下上下文并只回答结论：" + "冷站运行数据正常。" * 200,
    "multi_intent": "分别用两点回答：COP 是什么；能耗单位是什么。",
}


@dataclass
class PerformanceSample:
    """一次流式模型请求的性能观测。"""

    bucket: str
    concurrency: int
    ttft_ms: float
    total_ms: float
    input_tokens: int
    output_tokens: int
    success: bool
    error: Optional[str] = None
    first_text_ms: Optional[float] = None


def percentile(values: Iterable[float], quantile: float) -> float:
    """使用线性插值计算小样本可重复分位数。"""
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def run_stream_request(
    client: httpx.Client,
    *,
    base_url: str,
    model: str,
    bucket: str,
    prompt: str,
    concurrency: int,
    max_tokens: int,
) -> PerformanceSample:
    """执行一次 OpenAI SSE 请求并记录 TTFT、总延迟和 token。"""
    started = time.perf_counter()
    first_token_at: Optional[float] = None
    input_tokens = 0
    output_tokens = 0
    try:
        with client.stream(
            "POST",
            f"{base_url.rstrip('/')}/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": max_tokens,
                "stream": True,
                "stream_options": {"include_usage": True},
                "chat_template_kwargs": {"enable_thinking": False},
            },
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                payload = json.loads(line[6:])
                choices = payload.get("choices") or []
                content = choices[0].get("delta", {}).get("content") if choices else None
                if content and first_token_at is None:
                    first_token_at = time.perf_counter()
                usage = payload.get("usage") or {}
                input_tokens = int(usage.get("prompt_tokens") or input_tokens)
                output_tokens = int(usage.get("completion_tokens") or output_tokens)
        ended = time.perf_counter()
        return PerformanceSample(
            bucket=bucket, concurrency=concurrency,
            ttft_ms=((first_token_at or ended) - started) * 1000,
            total_ms=(ended - started) * 1000,
            input_tokens=input_tokens, output_tokens=output_tokens, success=True,
            first_text_ms=((first_token_at or ended) - started) * 1000,
        )
    except Exception as exc:
        ended = time.perf_counter()
        return PerformanceSample(
            bucket=bucket, concurrency=concurrency, ttft_ms=0,
            total_ms=(ended - started) * 1000, input_tokens=0, output_tokens=0,
            success=False, error=f"{type(exc).__name__}: {exc}",
        )


def run_agent_request(
    client: httpx.Client,
    *,
    agent_url: str,
    bucket: str,
    prompt: str,
    concurrency: int,
) -> PerformanceSample:
    """调用 EnerGraph `/stream`，记录首个正文事件与唯一 done 的总延迟。"""
    started = time.perf_counter()
    first_text_at: Optional[float] = None
    first_event_at: Optional[float] = None
    done_seen = False
    current_event = ""
    try:
        with client.stream(
            "POST", f"{agent_url.rstrip('/')}/stream",
            json={"user_input": prompt, "thread_id": f"perf-{uuid.uuid4().hex}"},
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line.startswith("event: "):
                    current_event = line[7:]
                elif line.startswith("data: "):
                    if current_event in {"thinking", "text"} and first_event_at is None:
                        first_event_at = time.perf_counter()
                    if current_event == "text" and first_text_at is None:
                        first_text_at = time.perf_counter()
                    if current_event == "done":
                        done_seen = True
        ended = time.perf_counter()
        if not done_seen:
            raise RuntimeError("Agent SSE 未收到 done")
        return PerformanceSample(
            bucket=bucket, concurrency=concurrency,
            ttft_ms=((first_event_at or first_text_at or ended) - started) * 1000,
            total_ms=(ended - started) * 1000, input_tokens=0, output_tokens=0,
            success=True, first_text_ms=((first_text_at or ended) - started) * 1000,
        )
    except Exception as exc:
        ended = time.perf_counter()
        return PerformanceSample(
            bucket=bucket, concurrency=concurrency, ttft_ms=0,
            total_ms=(ended - started) * 1000, input_tokens=0, output_tokens=0,
            success=False, error=f"{type(exc).__name__}: {exc}",
        )


def summarize(samples: Sequence[PerformanceSample]) -> Dict[str, Any]:
    """按并发和负载桶汇总成功率及 P50/P95/P99。"""
    def aggregate(group: Sequence[PerformanceSample]) -> Dict[str, Any]:
        successful = [sample for sample in group if sample.success]
        return {
            "requests": len(group),
            "success_rate": len(successful) / len(group) if group else 0.0,
            "ttft_ms": {f"p{p}": percentile((s.ttft_ms for s in successful), p / 100) for p in (50, 95, 99)},
            "total_ms": {f"p{p}": percentile((s.total_ms for s in successful), p / 100) for p in (50, 95, 99)},
            "first_text_ms": {
                f"p{p}": percentile(
                    (s.first_text_ms for s in successful if s.first_text_ms is not None), p / 100,
                ) for p in (50, 95, 99)
            },
            "input_tokens": sum(s.input_tokens for s in successful),
            "output_tokens": sum(s.output_tokens for s in successful),
        }

    return {
        "overall": aggregate(samples),
        "by_concurrency": {
            str(level): aggregate([sample for sample in samples if sample.concurrency == level])
            for level in sorted({sample.concurrency for sample in samples})
        },
        "by_bucket": {
            bucket: aggregate([sample for sample in samples if sample.bucket == bucket])
            for bucket in WORKLOADS
        },
    }


def write_performance_report(output_dir: Path, payload: Dict[str, Any]) -> None:
    """写入机器可读 JSON 和简洁 Markdown 报告。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# EnerGraph T13 Performance Baseline", "",
        f"- Model: `{payload['model']}`", f"- Scope: `{payload['scope']}`",
        f"- Warm-up: {payload['warmup_requests']}", f"- Samples: {len(payload['samples'])}",
        "", "## Concurrency", "",
        "| C | Requests | Success | TTFT P50/P95/P99 ms | Total P50/P95/P99 ms |",
        "|---:|---:|---:|---:|---:|",
    ]
    for level, stats in payload["summary"]["by_concurrency"].items():
        ttft = stats["ttft_ms"]
        total = stats["total_ms"]
        lines.append(
            f"| {level} | {stats['requests']} | {stats['success_rate']:.3f} | "
            f"{ttft['p50']:.1f}/{ttft['p95']:.1f}/{ttft['p99']:.1f} | "
            f"{total['p50']:.1f}/{total['p95']:.1f}/{total['p99']:.1f} |"
        )
    if payload.get("agent_summary"):
        lines.extend(["", "## Full Agent concurrency", "", "| C | Requests | Success | First SSE P50/P95/P99 ms | Final text P50/P95/P99 ms | Total P50/P95/P99 ms |", "|---:|---:|---:|---:|---:|---:|"])
        for level, stats in payload["agent_summary"]["by_concurrency"].items():
            ttft = stats["ttft_ms"]
            first_text = stats["first_text_ms"]
            total = stats["total_ms"]
            lines.append(
                f"| {level} | {stats['requests']} | {stats['success_rate']:.3f} | "
                f"{ttft['p50']:.1f}/{ttft['p95']:.1f}/{ttft['p99']:.1f} | "
                f"{first_text['p50']:.1f}/{first_text['p95']:.1f}/{first_text['p99']:.1f} | "
                f"{total['p50']:.1f}/{total['p95']:.1f}/{total['p99']:.1f} |"
            )
    lines.extend([
        "", "## Component scope", "",
        "- Model API: measured (streaming TTFT, total latency, tokens).",
        "- Tool latency: not included in this model-only baseline.",
        "- Retrieval latency: not included; use T10 local Chroma report.",
        "- Full Agent overhead: measured separately against `/stream` when agent_url is present.",
        "- Local model request cost: 0 external API charge; GPU telemetry unavailable from the OpenAI endpoint.",
    ])
    (output_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """执行 warm-up 和并发 1/2/5/10 的本地模型性能基线。"""
    parser = argparse.ArgumentParser(description="EnerGraph local LLM performance baseline")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--base-url", default=os.getenv("LOCAL_BASE_URL", ""))
    parser.add_argument("--model", default=os.getenv("LOCAL_MODEL", ""))
    parser.add_argument("--agent-url", default="")
    parser.add_argument("--concurrency", default="1,2,5,10")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args(argv)
    if not args.base_url or not args.model:
        raise ValueError("必须提供 LOCAL_BASE_URL/LOCAL_MODEL 或对应参数")
    levels = [int(value) for value in args.concurrency.split(",")]
    samples: List[PerformanceSample] = []
    agent_samples: List[PerformanceSample] = []
    with httpx.Client(timeout=args.timeout, headers={"Authorization": "Bearer not-needed"}) as client:
        for _ in range(args.warmup):
            run_stream_request(client, base_url=args.base_url, model=args.model, bucket="warmup", prompt=WORKLOADS["single_turn"], concurrency=1, max_tokens=args.max_tokens)
        buckets = list(WORKLOADS)
        for level in levels:
            jobs = max(level, args.repeats * level)
            with ThreadPoolExecutor(max_workers=level) as executor:
                futures = []
                for index in range(jobs):
                    bucket = buckets[index % len(buckets)]
                    futures.append(executor.submit(
                        run_stream_request, client, base_url=args.base_url, model=args.model,
                        bucket=bucket, prompt=WORKLOADS[bucket], concurrency=level,
                        max_tokens=args.max_tokens,
                    ))
                samples.extend(future.result() for future in as_completed(futures))
        if args.agent_url:
            for level in levels:
                jobs = max(level, args.repeats * level)
                with ThreadPoolExecutor(max_workers=level) as executor:
                    futures = []
                    for index in range(jobs):
                        bucket = buckets[index % len(buckets)]
                        futures.append(executor.submit(
                            run_agent_request, client, agent_url=args.agent_url,
                            bucket=bucket, prompt=WORKLOADS[bucket], concurrency=level,
                        ))
                    agent_samples.extend(future.result() for future in as_completed(futures))
    payload = {
        "schema_version": "0.1", "created_at": datetime.now(timezone.utc).isoformat(),
        "scope": "model_api", "model": args.model, "base_url": args.base_url,
        "warmup_requests": args.warmup, "repeats": args.repeats,
        "concurrency_levels": levels, "max_tokens": args.max_tokens,
        "samples": [asdict(sample) for sample in samples], "summary": summarize(samples),
        "agent_url": args.agent_url or None,
        "agent_samples": [asdict(sample) for sample in agent_samples],
        "agent_summary": summarize(agent_samples) if agent_samples else None,
    }
    write_performance_report(Path(args.output_dir), payload)
    return 0 if all(sample.success for sample in samples + agent_samples) else 1


if __name__ == "__main__":
    raise SystemExit(main())
