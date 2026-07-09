# EnerGraph T13 Performance Baseline

- Model: `qwen3.6-35b-a3b`
- Scope: `model_api`
- Warm-up: 1
- Samples: 36

## Concurrency

| C | Requests | Success | TTFT P50/P95/P99 ms | Total P50/P95/P99 ms |
|---:|---:|---:|---:|---:|
| 1 | 2 | 1.000 | 59.7/60.4/60.5 | 250.2/367.7/378.1 |
| 2 | 4 | 1.000 | 573.7/898.9/899.8 | 845.5/1355.9/1410.8 |
| 5 | 10 | 1.000 | 184.9/189.5/190.0 | 420.6/1065.0/1176.3 |
| 10 | 20 | 1.000 | 325.5/335.3/336.5 | 602.6/1744.7/1745.3 |

## Component scope

- Model API: measured (streaming TTFT, total latency, tokens).
- Tool latency: not included in this model-only baseline.
- Retrieval latency: not included; use T10 local Chroma report.
- Full Agent overhead: not included; must be measured separately against `/stream`.
- Local model request cost: 0 external API charge; GPU telemetry unavailable from the OpenAI endpoint.
