# EnerGraph T13 Performance Baseline

- Model: `qwen3.6-35b-a3b`
- Scope: `model_api`
- Warm-up: 1
- Samples: 36

## Concurrency

| C | Requests | Success | TTFT P50/P95/P99 ms | Total P50/P95/P99 ms |
|---:|---:|---:|---:|---:|
| 1 | 2 | 1.000 | 94.6/130.9/134.1 | 202.9/289.4/297.1 |
| 2 | 4 | 1.000 | 99.9/131.5/136.0 | 338.9/591.4/606.5 |
| 5 | 10 | 1.000 | 151.0/176.4/176.6 | 392.4/895.1/1012.3 |
| 10 | 20 | 1.000 | 265.2/371.9/380.7 | 544.8/1663.8/1665.8 |

## Full Agent concurrency

| C | Requests | Success | First SSE P50/P95/P99 ms | Final text P50/P95/P99 ms | Total P50/P95/P99 ms |
|---:|---:|---:|---:|---:|---:|
| 1 | 2 | 1.000 | 10.4/17.4/18.0 | 1680.5/2074.7/2109.7 | 1680.9/2075.1/2110.2 |
| 2 | 4 | 1.000 | 2.6/5.5/5.9 | 3572.7/4652.9/4785.5 | 5428.6/7308.1/7486.8 |
| 5 | 10 | 1.000 | 3.3/14.3/14.3 | 7082.7/16355.5/16370.2 | 7980.4/19819.1/21066.9 |
| 10 | 20 | 1.000 | 4.9/13.5/13.7 | 10227.8/25821.6/27631.5 | 11023.8/28659.2/33724.3 |

## Component scope

- Model API: measured (streaming TTFT, total latency, tokens).
- Tool latency: not included in this model-only baseline.
- Retrieval latency: not included; use T10 local Chroma report.
- Full Agent overhead: measured separately against `/stream` when agent_url is present.
- Local model request cost: 0 external API charge; GPU telemetry unavailable from the OpenAI endpoint.
