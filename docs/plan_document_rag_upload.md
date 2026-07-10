# 文件上传自动入库 RAG 实施任务书

> 状态：实施中  
> 创建日期：2026-07-10  
> 负责人：魏博源

## 1. 目标与边界

在不改变现有 HVAC `hvac_qa` 知识库和实时数据工具的前提下，新增全局共享的用户文档知识库。用户可在 Streamlit 上传 `.doc`、`.docx`、`.txt`、`.json`、`.pdf`；系统维护原文件、文档登记信息和可追溯 Chroma chunks，并让 Agent 基于检索结果回答文档问题。

第一期只解析可直接提取文字的 PDF；扫描件或无法提取文字的 PDF 标记失败并说明 OCR 后续支持。重复上传按 SHA-256 内容哈希复用已完成的文档，不重复生成向量。本期不引入 OCR、杀毒扫描或复杂权限体系；metadata 预留用户、站点与知识库字段。

## 2. 架构与数据流

```text
Streamlit / FastAPI 上传
  → DocumentKnowledgeService（保存、登记、解析、切块）
  → 现有 BGE embedding + Chroma collection: uploaded_documents
  → DocumentKnowledgeResult（片段、距离、文件/页码/章节来源）
  → Agent Tool + DocumentKnowledgeSkill
  → 回答与 SSE rag_sources
```

- 原文件保存于 `data/knowledge_uploads/<document_id>/`。
- 本地登记使用 `data/knowledge_uploads/registry.sqlite3`，不与 LangGraph PostgreSQL checkpoint/store 耦合；后续可迁移到 PostgreSQL。
- Chroma 沿用 `data/hvac_knowledge/`，但新建 `uploaded_documents` collection，所有 chunks 都有 `document_id` metadata。
- 生命周期：`uploaded → processing → ready | failed`；重新解析重新进入 processing；删除同步清理 Chroma、登记和原文件，重复操作保持幂等。

## 3. 实施任务

1. 新建 Pydantic 模型与文档知识库服务：解析、清洗、按标题/页码优先的重叠切块、入库、检索、状态查询、重试和删除。
2. 接入 Tool 注册、AgentState、DocumentKnowledgeSkill 和主图路由：明确上传资料、报告、规范、手册、文档等请求必须检索；低置信度不允许模型补写文档事实；实时数据和 HVAC 流程不变。
3. 扩展 Streamlit 知识库管理与独立问答测试；完成后提供 `/knowledge/documents` 上传、列表、详情、重解析与删除 API。
4. 增加 `python-docx`、`pypdf`；DOC 依赖系统 `antiword`，服务器部署说明补充安装与验收。
5. 覆盖五格式、空/损坏/扫描 PDF、重复上传、检索引用、删除、重解析、RAG 路由及既有 HVAC/实时数据回归。

## 4. 验收与发布

- 本地：`pytest src/tests/` 和 Streamlit 完整走通上传、状态、问答、删除、重解析。
- GitLab：从 `feature/document-rag-upload` 发起 MR，经审查合入 `main`。
- 服务器：在 `energraph` 环境安装依赖和 `antiword`，先验证 vLLM `8001`，再重启 Agent `8000`，使用 Streamlit `8501` 内网验收。
- 官网：最后由福加前端接入稳定 FastAPI，并展示 `rag_sources` 来源。

## 5. 已知限制

扫描 PDF/OCR、恶意文件扫描和细粒度用户/站点隔离不在第一期。文档问答只以命中的 chunks 为依据；无可靠召回时必须说明知识库未找到，不输出推测性文档答案。
