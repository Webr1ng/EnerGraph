"""report_generator — Eval JSON、Markdown、Manifest 与 baseline diff 报告

所属层：tests
依赖：json, benchmarks.shared
对接算法层：N/A
"""
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from benchmarks.shared.case_loader import deterministic_json, sanitize_sensitive
from benchmarks.shared.result_models import EvalResult, RunManifest


def aggregate_results(results: Iterable[EvalResult]) -> Dict[str, Any]:
    """聚合案例数、宏平均指标、门禁和失败案例。"""
    materialized = list(results)
    scores: Dict[str, List[float]] = defaultdict(list)
    gate_counts: Dict[str, int] = defaultdict(int)
    failed_cases: List[str] = []
    for result in materialized:
        for metric in result.metrics:
            scores[metric.name].append(metric.score)
        for gate in result.gates:
            if gate.violated:
                gate_counts[gate.name] += 1
        if result.error or not result.hard_gate_passed:
            failed_cases.append(result.case_id)
    metric_macro = {
        name: round(sum(values) / len(values), 6) for name, values in sorted(scores.items())
    }
    all_metric_values = [score for values in scores.values() for score in values]
    return {
        "case_count": len(materialized),
        "hard_gate_passed": not gate_counts,
        "metric_macro": metric_macro,
        "overall_macro": (
            round(sum(metric_macro.values()) / len(metric_macro), 6) if metric_macro else None
        ),
        "overall_micro": (
            round(sum(all_metric_values) / len(all_metric_values), 6)
            if all_metric_values else None
        ),
        "gate_violations": dict(sorted(gate_counts.items())),
        "failed_cases": sorted(failed_cases),
    }


def compare_baseline(summary: Dict[str, Any], baseline: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """比较当前摘要与 baseline，列出新增/修复失败及指标变化。"""
    if not baseline:
        return {"available": False, "new_failures": [], "fixed_failures": [], "metric_delta": {}}
    current_failed = set(summary.get("failed_cases", []))
    baseline_failed = set(baseline.get("failed_cases", []))
    baseline_metrics = baseline.get("metric_macro", {})
    return {
        "available": True,
        "new_failures": sorted(current_failed - baseline_failed),
        "fixed_failures": sorted(baseline_failed - current_failed),
        "metric_delta": {
            name: round(score - float(baseline_metrics.get(name, score)), 6)
            for name, score in summary.get("metric_macro", {}).items()
        },
    }


def write_report(
    output_dir: Path | str,
    results: List[EvalResult],
    manifest: RunManifest,
    baseline: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """写入脱敏 JSON、Markdown 摘要和 run_manifest.json。"""
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    summary = aggregate_results(results)
    baseline_diff = compare_baseline(summary, baseline)
    payload = sanitize_sensitive({
        "summary": summary,
        "baseline_diff": baseline_diff,
        "results": [result.model_dump(mode="json") for result in results],
    })
    (directory / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    (directory / "run_manifest.json").write_text(
        deterministic_json(manifest) + "\n", encoding="utf-8"
    )
    markdown = [
        f"# EnerGraph Eval — {manifest.run_id}",
        "",
        f"- Mode: `{manifest.mode}`",
        f"- Model: `{manifest.model_id}`",
        f"- Cases: {summary['case_count']}",
        f"- Hard gates: {'PASS' if summary['hard_gate_passed'] else 'FAIL'}",
        "",
        "## Metrics",
        "",
    ]
    markdown.extend(
        f"- `{name}`: {score:.6f}" for name, score in summary["metric_macro"].items()
    )
    markdown.extend(["", "## Gate violations", ""])
    if summary["gate_violations"]:
        markdown.extend(
            f"- `{name}`: {count}" for name, count in summary["gate_violations"].items()
        )
    else:
        markdown.append("- None")
    (directory / "summary.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")
    return payload


def load_baseline(path: Path | str) -> Dict[str, Any]:
    """从 JSON 文件加载 baseline 摘要。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))
