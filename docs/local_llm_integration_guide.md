# EnerGraph 本地 LLM 双实例部署指南

> 服务器: 192.168.128.15 | 2x NVIDIA L20 (48GB) | vLLM 0.24.0 + CUDA 12.8
> 最后更新: 2026-07-08

## 架构概览

两个独立 vLLM 实例分别占用一张 L20 GPU，通过 OpenAI 兼容 API 对外提供服务。

```
┌─────────────────────────────────────────────────────┐
│  192.168.128.15                                     │
│                                                     │
│  ┌───────────────────┐  ┌───────────────────┐      │
│  │  GPU 0 (L20 48GB) │  │  GPU 1 (L20 48GB) │      │
│  │  35B-A3B AWQ      │  │  27B Dense FP8    │      │
│  │  ~24GB 显存       │  │  ~29GB 显存       │      │
│  │  端口 8001        │  │  端口 8002        │      │
│  │  systemd: vllm    │  │  systemd: vllm-27b│      │
│  │  111 tok/s        │  │  17 tok/s         │      │
│  └───────────────────┘  └───────────────────┘      │
│          ▲                       ▲                  │
│          │ OpenAI API            │ OpenAI API       │
└──────────┼───────────────────────┼──────────────────┘
           │                       │
     http://192.168.128.15:8001/v1  http://192.168.128.15:8002/v1
```

## 模型对比

| 指标 | 35B-A3B AWQ | 27B Dense FP8 |
|------|-------------|---------------|
| 模型 | Qwen3.6-35B-A3B-AWQ | Qwen3.6-27B-FP8 |
| 架构 | MoE (35B总参/3B激活) | Dense (27B全激活) |
| 量化 | AWQ 4-bit | FP8 (官方发布) |
| 显存占用 | ~24 GB | ~29 GB |
| 推理速度 | **111.4 tok/s** | 17.4 tok/s |
| 首token延迟 | ~66ms | ~180ms |
| 工具调用 | qwen3_coder parser | qwen3_xml parser |
| 适用场景 | 高频工具调用、快速问答 | 复杂推理、长文本生成 |
| GPU | GPU 0 | GPU 1 |
| 端口 | 8001 | 8002 |

## 服务管理

### systemd 服务（开机自启 + 崩溃自动重启）

```bash
# ===== 35B-A3B AWQ (GPU 0, 端口 8001) =====
systemctl --user status vllm          # 查看状态
systemctl --user start vllm           # 启动
systemctl --user stop vllm            # 停止
systemctl --user restart vllm         # 重启

# ===== 27B Dense FP8 (GPU 1, 端口 8002) =====
systemctl --user status vllm-27b      # 查看状态
systemctl --user start vllm-27b       # 启动
systemctl --user stop vllm-27b        # 停止
systemctl --user restart vllm-27b     # 重启
```

### 健康检查

```bash
# 35B-A3B
python3 -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8001/health').status)"

# 27B FP8
python3 -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8002/health').status)"
```

### 查看日志

```bash
# 35B-A3B
tail -f ~/ai_department/llm_serving/logs/vllm_systemd.log

# 27B FP8
tail -f ~/ai_department/llm_serving/logs/vllm_27b.log
```

### GPU 状态

```bash
nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv,noheader
```

## 配置文件

### 目录结构

```
/home/user/ai_department/llm_serving/
├── config_35b_awq.yaml          # 35B-A3B AWQ 配置 (当前活跃)
├── config_27b_fp8.yaml          # 27B FP8 配置 (当前活跃)
├── config_122b_gptq.yaml        # 122B GPTQ 配置 (待创建, 需双卡TP=2)
├── run_vllm.sh                  # 35B 启动脚本 (CUDA_VISIBLE_DEVICES=0)
├── run_vllm_27b.sh              # 27B 启动脚本 (CUDA_VISIBLE_DEVICES=1)
├── logs/
│   ├── vllm_systemd.log         # 35B 日志
│   └── vllm_27b.log             # 27B 日志
└── models/
    ├── Qwen3.6-35B-A3B-AWQ/    # 35B AWQ 模型
    ├── Qwen3.6-27B-FP8/         # 27B FP8 模型
    └── Qwen3.5-122B-A10B-GPTQ/ # 122B GPTQ 模型
```

### 35B-A3B AWQ 配置 (config_35b_awq.yaml)

```yaml
model: /home/user/ai_department/llm_serving/models/Qwen3.6-35B-A3B-AWQ
served_model_name: qwen3.6-35b-a3b
host: 0.0.0.0
port: 8001
tensor-parallel-size: 1
gpu-memory-utilization: 0.92
trust-remote-code: true
enable-auto-tool-choice: true
tool-call-parser: qwen3_coder
reasoning-parser: qwen3
max-model-len: 32768
max-num-seqs: 64
max-num-batched-tokens: 32768
enable-chunked-prefill: true
enforce-eager: false
quantization: awq
```

### 27B Dense FP8 配置 (config_27b_fp8.yaml)

```yaml
model: /home/user/ai_department/llm_serving/models/Qwen3.6-27B-FP8
served_model_name: qwen3.6-27b-fp8
host: 0.0.0.0
port: 8002
tensor-parallel-size: 1
gpu-memory-utilization: 0.92
trust-remote-code: true
enable-auto-tool-choice: true
tool-call-parser: qwen3_xml
reasoning-parser: qwen3
max-model-len: 32768
max-num-seqs: 64
max-num-batched-tokens: 32768
enable-chunked-prefill: true
enforce-eager: false
```

## API 调用示例

两个实例均提供 OpenAI 兼容 API，调用方式完全一致，仅端口和 model 名不同。

### curl 测试

```bash
# 35B-A3B (端口 8001)
curl http://192.168.128.15:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.6-35b-a3b",
    "messages": [{"role": "user", "content": "你好"}],
    "max_tokens": 256,
    "chat_template_kwargs": {"enable_thinking": false}
  }'

# 27B FP8 (端口 8002)
curl http://192.168.128.15:8002/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3.6-27b-fp8",
    "messages": [{"role": "user", "content": "你好"}],
    "max_tokens": 256,
    "chat_template_kwargs": {"enable_thinking": false}
  }'
```

### Python (LangChain) 调用

```python
from langchain_openai import ChatOpenAI

# 35B-A3B (快速)
llm_fast = ChatOpenAI(
    model="qwen3.6-35b-a3b",
    base_url="http://192.168.128.15:8001/v1",
    api_key="not-needed",
    temperature=0.7,
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)

# 27B Dense (高质量)
llm_quality = ChatOpenAI(
    model="qwen3.6-27b-fp8",
    base_url="http://192.168.128.15:8002/v1",
    api_key="not-needed",
    temperature=0.7,
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)

response = llm_fast.invoke("解释什么是COP")
print(response.content)
```

## EnerGraph 集成

在 `.env` 中设置 `LLM_PROVIDER=local` 即可接入本地模型。项目统一 LLM 工厂已内置 `local` 分支，无需修改 `src/config/llm.py`；只需保证模型服务已启动且 `LOCAL_MODEL` 与 vLLM 的 `served_model_name` 一致。

### .env 配置

```bash
# 使用本地 35B-A3B (推荐，速度快)
LLM_PROVIDER=local
LOCAL_BASE_URL=http://192.168.128.15:8001/v1
LOCAL_MODEL=qwen3.6-35b-a3b
LOCAL_API_KEY=not-needed

# 或使用本地 27B FP8 (质量更高)
# LLM_PROVIDER=local
# LOCAL_BASE_URL=http://192.168.128.15:8002/v1
# LOCAL_MODEL=qwen3.6-27b-fp8
# LOCAL_API_KEY=not-needed
```

## 注意事项

1. **严禁使用 `fuser -k /dev/nvidia*`**，会误杀同事的 GPU 进程。停止 vLLM 只用 `systemctl --user stop vllm` 或 `systemctl --user stop vllm-27b`。
2. **思考模式**: 默认关闭（`enable_thinking: false`），开启会消耗大量 token 在推理链上。前端和 API 调用时通过 `chat_template_kwargs` 控制。
3. **CUDA Graph 编译**: 首次启动需要 ~100s 编译 CUDA Graph，后续启动从缓存加载 (~17s)。
4. **FP8 kernel 警告**: L20 GPU缺少预编译 FP8 kernel config，会有性能警告，不影响功能。
5. **前端调试**: 使用 `local_llm_chat.html` 单文件前端，支持双模型切换、流式输出、思考模式开关。

## 122B GPTQ (待部署)

Qwen3.5-122B-A10B-GPTQ 已下载完成 (74GB)，需要双卡 TP=2 部署。部署时需：
- 停止两个单卡服务释放 GPU
- 创建 `config_122b_gptq.yaml`（tensor-parallel-size: 2, port: 8001）
- 修改 `run_vllm.sh` 去除 `CUDA_VISIBLE_DEVICES` 限制
- 测试完成后恢复双实例部署
