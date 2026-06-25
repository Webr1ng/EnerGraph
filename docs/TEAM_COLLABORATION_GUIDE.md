# EnerGraph 团队协作开发指南

> **适用对象**：参与 EnerGraph 项目的所有开发者（现有成员 + 未来同事）  
> **最后更新**：2026-06-25
>
> 文档分工：架构状态、目录清单、工具/技能注册表以根目录 `AI_CONTEXT.md` 为准；强制代码规范、Git 提交格式、文档同步规则以根目录 `CLAUDE.md` 为准；本文只保留多人并行开发时最容易冲突的协作流程。

---

## 一、协作边界速览

EnerGraph 采用多智能体 Subgraph 架构。完整目录结构和当前状态见 `AI_CONTEXT.md`；这里仅列多人并行开发的边界：

- **目录隔离**：每个 Agent 独占 `src/graph/agents/<name>/`，优先在自己的子图内完成开发。
- **Prompt 隔离**：每个 Agent 独立维护 `src/config/prompts/<name>.yaml`；共享 Prompt 需提前沟通。
- **注册点集中**：新增 Agent 只在 `src/graph/agents/__init__.py` 注册，避免修改主图。
- **测试隔离**：Agent 专属测试放 `src/graph/agents/<name>/tests/`，公共回归测试放 `src/tests/`。

---

## 二、快速上手：新增 Agent 完整流程

### 场景：你负责开发"碳管理 Agent"

#### Step 1: 创建 Agent 目录结构

```bash
mkdir -p src/graph/agents/carbon_mgmt/{nodes,tests}
touch src/graph/agents/carbon_mgmt/{__init__.py,agent.py,state.py}
```

#### Step 2: 定义 Agent State

```python
# src/graph/agents/carbon_mgmt/state.py
from typing_extensions import TypedDict
from src.graph.agents.base_agent import BaseAgentState

class CarbonState(BaseAgentState):
    """碳管理 Agent 专属状态"""
    carbon_forecast: dict      # 碳排放预测结果
    cbam_compliance: dict      # CBAM 合规评估
    esg_report: str            # ESG 报告
```

#### Step 3: 实现 Agent 子图

```python
# src/graph/agents/carbon_mgmt/agent.py
from typing import Type
from typing_extensions import TypedDict
from langgraph.graph import StateGraph

from src.graph.agents.base_agent import BaseAgent
from .state import CarbonState

class CarbonAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "carbon_mgmt"

    @property
    def description(self) -> str:
        return "碳排放管理（碳足迹核算、CBAM 合规、ESG 报告）"

    @property
    def state_schema(self) -> Type[TypedDict]:
        return CarbonState

    def build_graph(self) -> StateGraph:
        graph = StateGraph(CarbonState)

        def carbon_forecast_node(state: CarbonState):
            # 调用 MCP Server 的 predict_carbon 模型
            # 或调用现有 Skill 的 execute 方法
            return {"carbon_forecast": {...}}

        def cbam_report_node(state: CarbonState):
            # 生成 CBAM 合规报告
            return {"final_report": "..."}

        graph.add_node("forecast", carbon_forecast_node)
        graph.add_node("report", cbam_report_node)
        graph.add_edge("forecast", "report")
        graph.set_entry_point("forecast")
        graph.set_finish_point("report")

        return graph.compile()
```

#### Step 4: 创建专属 Prompt

```yaml
# src/config/prompts/carbon_mgmt.yaml
carbon_forecast_hint:
  system: |
    根据能耗数据和排放因子，预测未来 7 天碳排放趋势。
    调用 MCP Server 的 predict_carbon 模型。

cbam_compliance_hint:
  system: |
    评估 CBAM（碳边境调节机制）合规性，生成合规报告。
```

#### Step 5: 注册到 Agent Registry

```python
# src/graph/agents/__init__.py（在文件末尾的 _register_all_agents 函数中添加）
def _register_all_agents():
    # ... 现有 Agent 注册 ...
    
    try:
        from src.graph.agents.carbon_mgmt.agent import CarbonAgent
        register_agent(CarbonAgent())
    except ImportError:
        pass
```

#### Step 6: 编写测试

```python
# src/graph/agents/carbon_mgmt/tests/test_carbon.py
import pytest
from src.graph.agents.carbon_mgmt.agent import CarbonAgent

def test_carbon_agent_build_graph():
    agent = CarbonAgent()
    graph = agent.build_graph()
    assert graph is not None

def test_carbon_forecast():
    agent = CarbonAgent()
    graph = agent.build_graph()
    result = graph.invoke({"user_input": "预测本周碳排"})
    assert "carbon_forecast" in result
```

运行测试：
```bash
pytest src/graph/agents/carbon_mgmt/tests/ -v
```

#### Step 7: 提交代码（Git 工作流见下文）

```bash
git checkout -b feature/carbon-agent
git add src/graph/agents/carbon_mgmt/ src/config/prompts/carbon_mgmt.yaml
git commit -m "[graph] 新增碳管理 Agent 子图"
git push origin feature/carbon-agent
```

---

## 三、Git 协作规范

### 3.1 分支策略

分支类型与提交格式以 `CLAUDE.md` 为准。协作时建议把 Agent 名或文档范围写进分支名，方便 Code Review：

- `feature/powerai-mcp-integration` — PowerAI 接入 MCP Server
- `feature/carbon-cbam-compliance` — 碳管理 CBAM 合规模块
- `fix/hvac-citation-format` — 修复 HVAC 引用格式
- `refactor/prompts-optimization` — Prompt 优化重构

### 3.2 开发工作流

```bash
# 1. 从 main 拉取最新代码
git checkout main
git pull origin main

# 2. 创建特性分支（以你负责的 Agent 命名）
git checkout -b feature/<agent>-<feature>

# 3. 开发（优先修改你负责的 Agent 目录和 Prompt 文件）
# 修改文件...

# 4. 本地测试
pytest src/graph/agents/<agent>/ -v
pytest src/tests/ -v  # 全量测试确保无回归

# 5. 提交（遵循 CLAUDE.md 的 git add / commit 规范）
git add src/graph/agents/<agent>/ src/config/prompts/<agent>.yaml
git commit -m "[graph] 简短描述变更内容"

# 6. 推送到远程
git push origin feature/<agent>-<feature>

# 7. 在 GitLab/GitHub 创建 Merge Request / Pull Request
# 标题：[Agent名/模块名] 简短功能描述
# 描述：参照"MR 模板"（见下文）
```

### 3.3 Merge Request (MR) / Pull Request (PR) 模板

在 GitLab/GitHub 创建 MR/PR 时，使用以下模板填写描述：

```markdown
## 功能描述
[简述本次变更的业务功能，1-2 句话]

## 变更清单
- [ ] 新增 Agent: `agents/<name>/`
- [ ] 修改 Prompt: `prompts/<name>.yaml`
- [ ] 新增/修改 Tools: `tools/<name>.py`
- [ ] 新增/修改 Schemas: `schemas/<name>.py`
- [ ] 更新文档: `CHANGELOG.md`, `AI_CONTEXT.md`

## 测试情况
- [ ] 单元测试通过（`pytest agents/<name>/tests/`）
- [ ] 集成测试通过（`pytest src/tests/`）
- [ ] 手动测试场景：
  - 场景 1: [描述输入和预期输出]
  - 场景 2: [描述输入和预期输出]

## 依赖检查
- [ ] 是否修改了公共模块（Tools / 主图 / Schemas）？如是，说明原因：[填写]
- [ ] 是否新增了依赖包？如是，已更新 `requirements.txt`
- [ ] 是否修改了 Prompt？如是，Prompt 已独立 commit

## 性能影响
- [ ] 是否引入了阻塞调用（如同步 HTTP）？如是，已改为异步
- [ ] 是否增加了 LLM 调用次数？如是，预估 token 成本：[填写]

## 文档更新
- [ ] 已更新 `CHANGELOG.md`（变更日期 + 描述 + 作者）
- [ ] 已更新 `AI_CONTEXT.md`（如涉及架构变更）
- [ ] 已更新 `MCP_INTERFACE_SPEC.md`（如新增 MCP 工具）

## Reviewers
@项目Owner @算法团队负责人
```

### 3.4 公共依赖冲突解决

**场景**：两个开发者都需要修改 `src/tools/__init__.py`

**策略 1：通信协调（优先）**
- 在团队群/Slack/飞书协调："我正在改 `tools/__init__.py` 的 XXX，预计 1h 内 push"
- 开发者 A 先 merge，开发者 B rebase 后再 merge

**策略 2：最小化共享修改**
- Agent 专属工具移入子图目录：`agents/<agent>/tools/<tool>.py`
- `src/tools/` 仅保留真正共享的工具（如 `navigate_to_page`, `query_hvac_knowledge`）

**策略 3：Rebase 解决冲突**
```bash
# 开发者 B 发现 main 已更新（开发者 A 已 merge）
git checkout feature/<agent>-<feature>
git fetch origin
git rebase origin/main

# 如有冲突
# 1. 手动解决冲突
# 2. git add <冲突文件>
# 3. git rebase --continue
# 4. git push -f origin feature/<agent>-<feature>
```

### 3.5 分支保护规则（GitLab/GitHub 设置）

在项目设置中启用：
- ✅ `main` 分支受保护（Protected branch）
- ✅ 禁止直接 push（Allowed to push: No one）
- ✅ Merge 前必须通过 CI（Pipelines must succeed）
- ✅ Merge 前至少 1 人 Approve（Approvals required: 1）
- ✅ 不允许 force push

---

## 四、Prompt 协作约定

### 4.1 Prompt 拆分规则

| Prompt 文件 | 内容 | 修改频率 | 谁负责 |
|------------|------|---------|-------|
| `_shared.yaml` | 共享片段（回答原则/跳转规则） | 低 | 项目 Owner |
| `main_graph.yaml` | 主图节点 Prompt（cognitive_parser, interpreter_generator） | 低 | 项目 Owner |
| `hvac_expert.yaml` | HVAC Agent 专属 Prompt | 中 | HVAC Agent 负责人 |
| `ui_router.yaml` | UI Router Agent 专属 Prompt | 低 | UI Router Agent 负责人 |
| `powerai.yaml` | PowerAI Agent 专属 Prompt | 高 | PowerAI Agent 负责人 |
| `carbon_mgmt.yaml` | 碳管理 Agent 专属 Prompt | 高 | 碳管理 Agent 负责人 |

### 4.2 Prompt 修改流程

Prompt 的强制规则以 `CLAUDE.md` 为准。协作时额外注意：

1. 修改共享文件 `_shared.yaml` / `main_graph.yaml` 前先告知团队。
2. 修改 Agent 专属 Prompt 时，在 MR 描述里写清 prompt key 与预期行为变化。
3. Prompt 变更必须单独提交，避免和代码行为变更混在同一条提交里。

## 五、测试规范

### 5.1 测试目录结构

```
src/graph/agents/<agent>/tests/    # Agent 专属测试（快速迭代）
src/tests/                          # 全量集成测试（保证无回归）
```

### 5.2 测试要求

- ✅ **新增 Agent 必须写测试**：至少覆盖子图的主流程
- ✅ **新增 Tool 必须写测试**：正常输入、边界值、非法输入
- ✅ **修 Bug 先写复现测试**，再修复，确保不复现

### 5.3 测试运行

```bash
# 开发阶段：只运行你负责的 Agent 测试（快）
pytest src/graph/agents/powerai/tests/ -v

# 提交前：运行全量测试（确保无回归）
pytest src/tests/ -v

# CI 自动运行：所有测试
pytest src/ -v --cov=src --cov-report=html
```

---

## 六、文档更新规则

具体更新时机和日志格式以 `CLAUDE.md` 的"文档维护规则"为准。团队协作时只需记住：

- `CHANGELOG.md` 记录完整历史。
- `AI_CONTEXT.md` 记录当前状态和最近 5 条摘要。
- `PRD.md` 只在产品需求、用户场景、产品红线变化时更新。
- `TEAM_COLLABORATION_GUIDE.md` 只在协作流程变化时更新。

---

## 七、常见问题 FAQ

### Q1: 我需要修改主图（`builder.py` / `nodes.py`）吗？

**A**: **通常不需要**。新增 Agent 只需：
1. 在 `agents/<name>/` 创建子图
2. 在 `agents/__init__.py` 注册
3. 主图会通过 `AGENT_REGISTRY` 自动加载

**例外**：需要修改主图的场景（需与项目 Owner 讨论）：
- 修改意图识别逻辑（`cognitive_parser` 节点）
- 修改子图调度逻辑（`agent_dispatcher` 节点，当前为 Skill 调度，未来升级为 Subgraph 调度）

### Q2: 我可以在 Agent 内部调用其他 Agent 吗？

**A**: **当前架构暂不支持 Agent 间直接调用**。如需跨 Agent 协作：
- **方案 1**：在主图层编排多个 Agent 的串行/并行执行
- **方案 2**（未来）：实现 A2A（Agent-to-Agent）协议，通过消息传递协作

### Q3: 我修改了 `prompts/<agent>.yaml`，需要重启服务吗？

**A**: **需要**。当前 Prompt 在服务启动时加载（`settings.py`），修改后需重启 FastAPI 服务：
```bash
pkill -f "uvicorn src.frontend.app:app"
python run.py
```

未来优化：实现 Prompt 热重载（监听文件变化自动重新加载）。

### Q4: 我需要接入新的算法模型（MCP Server），怎么做？

**A**: 参考 `MCP_INTERFACE_SPEC.md`：
1. 在 `src/tools/` 创建 MCP Client 工具（如 `predict_carbon.py`）
2. 在 `agents/<agent>/nodes.py` 的节点函数中调用该工具
3. 在 `prompts/<agent>.yaml` 添加对应的 Prompt hint
4. 更新 `MCP_INTERFACE_SPEC.md` 补充接口契约

### Q5: 测试失败了，但本地运行正常，可能是什么原因？

**A**: 常见原因：
1. **环境变量缺失**：CI 环境缺少 `.env` 文件，需在 GitLab CI Variables 配置
2. **LLM API Key 失效**：检查 `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` 是否有效
3. **依赖版本不一致**：运行 `pip install -r requirements.txt` 确保依赖同步

### Q6: 我想重构一个已有 Agent，需要怎么做？

**A**: 重构流程：
1. **先写测试**：确保现有功能有测试覆盖（如果没有，先补测试）
2. **创建重构分支**：`git checkout -b refactor/<agent>-<desc>`
3. **小步迭代**：每次改动后运行测试，确保无回归
4. **更新文档**：重构完成后更新 `AI_CONTEXT.md` 和 `CHANGELOG.md`
5. **Code Review**：重构 PR 必须有至少 1 人 Review

---

## 八、Code Review 检查清单

作为 Reviewer，审查 PR 时请检查以下项：

### 代码质量
- [ ] 文件头 docstring 完整（模块名 / 职责 / 依赖 / 对接算法层）
- [ ] 函数有 Type Hints + Docstring（Args / Returns / Raises）
- [ ] 命名规范（`snake_case` / `PascalCase` / `UPPER_SNAKE_CASE`）
- [ ] 错误处理完整（Tool 函数必须 try-except）

### 架构规范
- [ ] Agent 目录隔离（`agents/<name>/`）
- [ ] Prompt 配置外部化（`prompts/<name>.yaml`），无硬编码
- [ ] 新增 Agent 已注册到 `AGENT_REGISTRY`
- [ ] 禁止在 Agent 内部硬编码算法逻辑（必须通过 MCP / Tools 调用）

### 测试覆盖
- [ ] 新增 Agent / Tool 有对应测试
- [ ] 测试通过（CI 绿灯）
- [ ] 手动测试场景清晰

### 文档更新
- [ ] `CHANGELOG.md` 已更新
- [ ] `AI_CONTEXT.md` 已同步（如涉及架构变更）
- [ ] Commit message 符合规范

---

## 九、联系方式与协作平台

| 事项 | 平台/渠道 |
|------|----------|
| 技术讨论 | 团队 Slack / 飞书群 |
| Code Review | GitLab Merge Request |
| Bug 跟踪 | GitLab Issues |
| 架构决策 | 技术例会（每周） / GitLab Wiki |
| 紧急问题 | @项目Owner（魏博源） |

---

## 十、推荐开发工具

- **IDE**: VS Code + Python Extension + Pylance
- **Git GUI**: GitKraken / SourceTree（可视化分支管理）
- **API 测试**: Postman / HTTPie（测试 FastAPI 端点）
- **Prompt 调优**: LangSmith（LangChain 官方调试平台）

---

**祝开发愉快！有问题随时在团队群提问。**
