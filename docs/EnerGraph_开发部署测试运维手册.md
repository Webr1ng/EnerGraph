# EnerGraph 开发、部署、测试与运维手册

> 统一记录本地开发、GitLab 协作、服务器部署、内网 LLM、Streamlit 验收和福加官网接入流程。
>
> 最后更新：2026-07-10

## 1. 总体交付链路

```text
本地 feature/fix 分支开发 → 本地 Streamlit 测试
→ 推送 GitLab → Review → merge main
→ 服务器拉取 main → 服务器 Streamlit 内网联调
→ FastAPI Agent API 验收 → 福加官网接入测试
```

Agent 是编排层，运行在服务器上；本地 LLM 由同一台服务器上的 vLLM 提供 OpenAI 兼容接口。

| 服务 | 地址/端口 | 作用 | 管理方式 |
|---|---|---|---|
| EnerGraph Agent API | `192.168.128.15:8000` | FastAPI、SSE、供前端或官网调用 | `systemctl --user`，自动重启 |
| vLLM 本地模型 | `192.168.128.15:8001/v1` | OpenAI 兼容 LLM 推理接口 | 启动脚本或人工进程管理 |
| Streamlit Demo | `192.168.128.15:8501` | 服务器内网联调和演示 | 当前手动启动，不自动恢复 |

## 2. 服务器连接信息

服务器：`192.168.128.15`，SSH 端口：`22`，用户：`user`，用户具备 sudo 权限。

```bash
ssh -p 22 user@192.168.128.15
```

按要求，连接信息可放入本机 `.env`；密码不复制到 Git 管理的 Markdown 文档、Issue、MR 或日志：

```env
SERVER_HOST=192.168.128.15
SERVER_PORT=22
SERVER_USER=user
SERVER_PASSWORD=<服务器登录密码>
```

`.env` 已被 `.gitignore` 忽略，禁止 `git add .`。如果密码曾进入 Git 或共享日志，应立即修改密码并清理副本。

## 3. GitLab 分支与发布流程

GitLab 远程仓库：`git@172.16.3.160:ai-group/energraph.git`。服务器项目目录：`/home/user/ai_department/EnerGraph`。服务器使用 `~/.ssh/id_ed25519` 访问 GitLab。

本地开发与测试：

```bash
git switch main
git pull --rebase origin main
git switch -c feature/<功能名>   # 修复使用 fix/<问题名>
conda activate energraph
pytest src/tests/
streamlit run src/frontend/app.py
```

提交并发起 MR：

```bash
git add <明确的文件路径>
git commit -m "[docs] 更新服务器部署与测试流程"
git push -u origin feature/<功能名>
```

完成 Review 后合并到 `main`。服务器发布：

```bash
ssh -p 22 user@192.168.128.15
cd /home/user/ai_department/EnerGraph
git switch main
git pull --rebase origin main
```

不要用服务器直接改代码替代 GitLab 合并流程；依赖变更先在服务器 `energraph` 环境安装或更新，再重启服务。

## 4. 服务器环境与额外配置

| 项目 | 配置 |
|---|---|
| 操作系统 | Ubuntu 22.04，x86_64 |
| Python / Conda | Python 3.11；`~/miniconda3` |
| Agent 环境 | `energraph` |
| vLLM 环境 | `vllm_serving` |
| vLLM 目录 | `/home/user/ai_department/llm_serving` |
| HuggingFace 镜像 | `https://hf-mirror.com` |

服务器额外依赖包括 `pycryptodome`（福加 Token RSA 刷新）、`sentence-transformers`（RAG embedding）、`python-docx` / `pypdf`（上传文档解析）和系统 `antiword`（旧版 `.doc` 解析）：

```bash
source ~/miniconda3/etc/profile.d/conda.sh
conda activate energraph
pip install -r requirements.txt
pip install pycryptodome sentence-transformers
sudo apt-get update
sudo apt-get install -y antiword
```

服务器 `.env` 需保留：`HF_ENDPOINT=https://hf-mirror.com`。`git pull` 后若被覆盖，应恢复该配置。部署上传文档 RAG 后，分别上传一个文字型 `.pdf` 和一个 `.doc` 进行内网验证；扫描 PDF 会显示「OCR 后续支持」，属于第一期预期行为。

## 5. Agent API 的 systemd 持久化

服务文件：`~/.config/systemd/user/energraph.service`

```ini
[Unit]
Description=EnerGraph Agent API
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/user/ai_department/EnerGraph
ExecStart=/home/user/miniconda3/envs/energraph/bin/python /home/user/ai_department/EnerGraph/run.py --prod
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
Environment=HF_ENDPOINT=https://hf-mirror.com

[Install]
WantedBy=default.target
```

启用：

```bash
systemctl --user daemon-reload
systemctl --user enable energraph
systemctl --user start energraph
loginctl enable-linger user
```

运维：

```bash
systemctl --user status energraph
systemctl --user restart energraph
systemctl --user stop energraph
systemctl --user start energraph
journalctl --user -u energraph -f
journalctl --user -u energraph -n 50
curl -s http://localhost:8000/health
```

`Restart=always` 和 `RestartSec=5` 会在进程异常退出后自动重启。重启后先确认 vLLM 8001 就绪，再检查 Agent 8000。

## 6. vLLM 本地 LLM 服务

服务目录：`/home/user/ai_department/llm_serving`。模型以服务器当前 `config.yaml` 为准。历史记录使用过 `qwen3.6-27b`，项目最新验证记录使用 `qwen3.6-35b-a3b` / `Qwen3.6-35B-A3B-AWQ`；切换时同步 `served_model_name`、Agent `LOCAL_MODEL` 和测试命令中的 `model`。

启动：

```bash
cd /home/user/ai_department/llm_serving
bash start.sh
```

或手动启动：

```bash
source /home/user/miniconda3/etc/profile.d/conda.sh
conda activate vllm_serving
export CUDA_HOME=/usr/local/cuda-12.8
export VLLM_USE_FLASHINFER_SAMPLER=0
vllm serve --config /home/user/ai_department/llm_serving/config.yaml
```

检查：

```bash
curl http://192.168.128.15:8001/health
curl http://192.168.128.15:8001/v1/models
tail -f /home/user/ai_department/llm_serving/logs/vllm.log
nvidia-smi
ps aux | grep vllm
```

基础对话：

```bash
curl http://192.168.128.15:8001/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "<served_model_name>",
    "messages": [{"role": "user", "content": "你好"}],
    "max_tokens": 512,
    "temperature": 0.25,
    "chat_template_kwargs": {"enable_thinking": false}
  }'
```

Qwen 联调默认关闭思考模式，避免大量 token 消耗在 reasoning 上。首次 CUDA Graph 编译可能较慢；双卡 TP=2 通过 PCIe 通信，高并发前应重新测量吞吐和延迟。

## 7. Agent 接入与切换本地 LLM

服务器 `.env`：

```env
LLM_PROVIDER=local
LOCAL_MODEL=<与 vLLM served_model_name 一致>
LOCAL_BASE_URL=http://localhost:8001/v1
LOCAL_API_KEY=not-needed
```

修改后：

```bash
systemctl --user restart energraph
sleep 3
systemctl --user status energraph
curl -s http://localhost:8000/health
```

切回云端只需将 `LLM_PROVIDER` 改回 `deepseek`，再重启 `energraph`。模型名称、上下文窗口和工具调用解析器以 vLLM 当前配置为准。

## 8. Streamlit 测试

本地电脑：

```bash
conda activate energraph
streamlit run src/frontend/app.py
```

验证页面渲染、输入输出、流式事件、工具调用、错误提示和页面跳转。普通单元测试与福加真实 API 测试要明确区分。

服务器内网：

```bash
cd /home/user/ai_department/EnerGraph
source ~/miniconda3/etc/profile.d/conda.sh
conda activate energraph
nohup streamlit run src/frontend/app.py --server.port 8501 > streamlit.log 2>&1 &
```

访问 `http://192.168.128.15:8501`，检查：

```bash
ps aux | grep streamlit
tail -f streamlit.log
```

8501 当前不是 systemd 服务，重启服务器或进程退出后不会自动恢复；如需持久化，应另建 `streamlit.service`。

## 9. 三阶段验收清单

### 本地 Streamlit

- feature/fix 分支的单元测试通过。
- `.env`、Token、密码和模型权重没有加入 Git。
- 页面、流式输出、工具调用、错误提示和导航正常。
- 修改已提交并推送 GitLab，等待 MR Review。

### 服务器内网 Streamlit

- `main` 已合并，服务器已拉取最新代码。
- vLLM 8001 `/health`、`/v1/models` 正常。
- Agent 8000 `/health` 正常，systemd 日志无启动异常。
- Streamlit 8501 可访问。
- 真实数据核对日期、站点、单位、数值和页面跳转。

### 福加官网接入

- 官网指向 Agent API 8000 的约定接口。
- 验证 Bearer 鉴权、CORS、`/invoke`、`/stream`/SSE。
- 验证流式事件、最终报告、action 和错误恢复。
- 核对官网数据与福加页面一致，不把 LLM 无工具生成的数字当作真实数据。
- 记录 Git commit、模型版本、服务器配置变更和测试时间。

## 10. 故障排查与迁移

排查顺序：

1. `curl http://localhost:8001/health`，确认 vLLM。
2. `curl http://localhost:8000/health`，确认 Agent。
3. 查看 `systemctl --user status energraph` 和 `journalctl --user -u energraph -n 100`。
4. 检查 `.env` 的 LLM、福加 API 和 `HF_ENDPOINT` 配置。
5. 福加大量 401 时检查 `pycryptodome` 和 Token 自动刷新。
6. 检查 `nvidia-smi` 与 `vllm.log`。
7. 确认服务器分支为 `main` 且已完成 `git pull --rebase origin main`。

迁移服务器时依次完成：安装 Miniconda 与 Python 3.11 → 创建环境并安装依赖 → 配置 `.env` 与 GitLab SSH key → 克隆项目 → 配置 systemd 并启用 linger → 部署 vLLM → 检查 8001 → 重启并检查 8000 → 启动 8501 → 完成内网和官网验收。

禁止用随机 Mock 掩盖线上故障；测试记录必须标明 Mock、服务器真实联调和官网真实接入环境。
