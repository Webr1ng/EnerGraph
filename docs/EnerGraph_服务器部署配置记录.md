## EnerGraph 服务器部署配置记录

> 服务器：192.168.128.15（用户名 user）
> 项目路径：/home/user/ai_department/EnerGraph
> 最后更新：2026-06-23

---

### 一、环境基础

| 项目 | 值 |
|------|-----|
| 操作系统 | Ubuntu 22.04 (内核 6.8.0-111-generic, x86_64) |
| Python 环境管理 | Miniconda3 (`~/miniconda3`) |
| Conda 环境名 | `energraph` (Python 3.11) |
| Git 远程仓库 | `origin` → `git@172.16.3.160:ai-group/energraph.git`（内网 GitLab） |
| SSH 密钥 | `~/.ssh/id_ed25519`（已配置 GitLab 免密） |

---

### 二、服务器独有的配置（本地没有的）

#### 1. systemd 服务文件

路径：`~/.config/systemd/user/energraph.service`

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

关键说明：
- `ExecStart` 直接指向 conda 环境的 Python，不依赖 `conda activate`
- `Restart=always` + `RestartSec=5`：进程崩溃后 5 秒自动重启
- `HF_ENDPOINT` 写在 service 文件里，因为服务器无法直连 huggingface.co，必须走国内镜像
- 已执行 `systemctl --user enable energraph` 设置开机自启
- 已执行 `loginctl enable-linger user` 确保 SSH 断开后服务不停

#### 2. .env 文件额外配置

服务器 `.env` 末尾追加了以下内容（git pull 后可能被覆盖，需重新添加）：

```env
# HuggingFace Mirror (服务器无法直连 huggingface.co)
HF_ENDPOINT=https://hf-mirror.com
```

注意：每次 `git pull` 如果 `.env` 被远程覆盖，需要重新加回这一行。建议将 `.env` 加入 `.gitignore` 或在远程仓库的 `.env` 中也加上此行。

#### 3. conda 环境中额外安装的 pip 包

以下包不在 `requirements.txt` 中，是手动在服务器 conda 环境安装的：

| 包名 | 用途 | 安装原因 |
|------|------|----------|
| `pycryptodome` | RSA 加密（福加 API Token 刷新） | `fuca_token_refresher.py` 依赖 `Crypto` 模块 |
| `sentence-transformers` | 文本向量化（RAG embedding） | `query_hvac_knowledge.py` 和 `rag_ingest.py` 依赖 |

建议将这两个包也加入 `requirements.txt`，避免重新部署时遗漏。

---

### 三、运行中的服务

| 服务 | 端口 | 启动方式 | 用途 |
|------|------|----------|------|
| EnerGraph Agent API | 8000 | systemd（永久） | 后端 API，供前端调用 |
| Streamlit Demo | 8501 | 手动启动（不持久） | 演示前端，非 systemd 管理 |

Streamlit 前端当前是手动启动的（`nohup streamlit run ...`），重启服务器后不会自动拉起。如果也需要持久化，需要另建一个 systemd service。

---

### 四、常用运维命令

```bash
# ── 服务管理 ──
systemctl --user status energraph      # 查看状态
systemctl --user restart energraph     # 重启服务
systemctl --user stop energraph        # 停止服务
systemctl --user start energraph       # 启动服务

# ── 日志查看 ──
journalctl --user -u energraph -f             # 实时日志（Ctrl+C 退出）
journalctl --user -u energraph -n 50          # 最近 50 行日志
journalctl --user -u energraph --since '1 hour ago'  # 最近 1 小时日志

# ── 健康检查 ──
curl http://localhost:8000/health      # 应返回 {"status":"ok"}

# ── 代码更新流程 ──
cd /home/user/ai_department/EnerGraph
git pull origin main
# 检查 .env 是否被覆盖（HF_ENDPOINT 还在不在）
grep HF_ENDPOINT .env || echo 'HF_ENDPOINT=https://hf-mirror.com' >> .env
# 重启服务
systemctl --user restart energraph

# ── 手动刷新福加 Token ──
source ~/miniconda3/etc/profile.d/conda.sh && conda activate energraph
cd /home/user/ai_department/EnerGraph
python -m src.utils.fuca_token_refresher
```

---

### 五、已知问题与注意事项

**1. Token 过期**
福加 API Token 有时效性。代码中有自动刷新机制（401 时自动重新登录获取 Token），但如果 `pycryptodome` 缺失会导致刷新失败。出现大量 `code=401` 日志时，检查 pycryptodome 是否安装。

**2. HuggingFace 镜像**
服务器无法直连 huggingface.co（网络不可达），embedding 模型下载依赖 hf-mirror.com 镜像。如果服务器网络环境变化（可以直连了），可以移除 `HF_ENDPOINT` 配置。

**3. Streamlit 不持久**
8501 端口的 Streamlit Demo 是手动启动的，服务器重启或进程被杀后不会自动恢复。如果需要持久化，参照 energraph.service 再建一个 streamlit.service。

**4. requirements.txt 不完整**
当前 `requirements.txt` 缺少 `pycryptodome` 和 `sentence-transformers`，新环境部署时需要手动补装或更新 requirements.txt。

**5. rag_ingest.py 路径问题**
`JSONL_PATH` 指向项目根目录，但语料文件实际在 `data/` 子目录下。ChromaDB 数据已存在（5605 条），暂时不影响使用，但如果需要重新 ingest 需要修正路径。

---

### 六、服务器变更时需要同步的事项

如果服务器换了、重装了系统、或项目迁移到新服务器，需要按以下顺序操作：

1. 安装 Miniconda3，创建 conda 环境：`conda create -n energraph python=3.11 -y`
2. `pip install -r requirements.txt`
3. `pip install pycryptodome sentence-transformers`（补装缺失依赖）
4. 配置 SSH 密钥，确保能访问 GitLab（`git@172.16.3.160`）
5. `git clone` 项目到服务器
6. 配置 `.env`（确保包含 `HF_ENDPOINT=https://hf-mirror.com`）
7. 创建 systemd service 文件（复制上面第二节的配置）
8. `systemctl --user daemon-reload && systemctl --user enable energraph && systemctl --user start energraph`
9. `loginctl enable-linger user`
