# EnerGraph T13 Performance Baseline

- Model: `qwen3.6-35b-a3b`
- Scope: `model_api`
- Warm-up: 1
- Samples: 36

## Concurrency

| C | Requests | Success | TTFT P50/P95/P99 ms | Total P50/P95/P99 ms |
|---:|---:|---:|---:|---:|
| 1 | 2 | 1.000 | 101.4/143.5/147.2 | 312.0/430.7/441.2 |
| 2 | 4 | 1.000 | 113.1/149.6/153.1 | 392.4/701.2/720.9 |
| 5 | 10 | 1.000 | 172.1/195.5/195.8 | 413.1/1096.0/1217.3 |
| 10 | 20 | 1.000 | 276.9/296.6/322.5 | 586.7/1785.0/1786.3 |

## Full Agent concurrency

| C | Requests | Success | Text P50/P95/P99 ms | Total P50/P95/P99 ms |
|---:|---:|---:|---:|---:|
| 1 | 2 | 1.000 | 10740.1/19465.7/20241.3 | 11062.2/20075.6/20876.8 |
| 2 | 4 | 1.000 | 2968.0/19612.8/21727.2 | 2968.4/20221.1/22421.2 |
| 5 | 10 | 1.000 | 1673.6/17357.4/25449.4 | 1961.6/17808.4/26195.4 |
| 10 | 20 | 1.000 | 1859.5/6192.2/20436.2 | 2094.2/6245.6/21296.2 |

## Component scope

- Model API: measured (streaming TTFT, total latency, tokens).
- Tool latency: not included in this model-only baseline.
- Retrieval latency: not included; use T10 local Chroma report.
- Full Agent overhead: measured separately against `/stream` when agent_url is present.
- Local model request cost: 0 external API charge; GPU telemetry unavailable from the OpenAI endpoint.
