"""test_hvac_quality — Phase 3 RAG 质量优化测试

所属层：tests
依赖：pytest, unittest.mock
对接算法层：N/A（Mock ChromaDB）

测试范围：
  - T1: 相关度阈值过滤（low_confidence 标记）
  - T2: 低置信度拒答（HVACExpertSkill.execute）
  - T3: 引用来源（source_snippets + citation prompt）
  - T4: MMR 去重（_deduplicate）
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from src.config.settings import settings
from src.skills.hvac_expert_skill import HVACExpertSkill
from src.tools.query_hvac_knowledge import _deduplicate, _build_source_snippets

# ---------------------------------------------------------------------------
# T4: MMR 去重
# ---------------------------------------------------------------------------


class TestDeduplicate:
    """_deduplicate 函数测试"""

    def test_no_duplicates(self):
        """所有文档 distance 差异明显，不应去重"""
        docs = ["文档A", "文档B", "文档C"]
        distances = [0.2, 0.4, 0.6]
        metas = [{"source": "a"}, {"source": "b"}, {"source": "c"}]

        out_docs, out_dists, out_metas = _deduplicate(docs, distances, metas, 0.95)
        assert len(out_docs) == 3

    def test_removes_near_duplicates(self):
        """两个文档余弦相似度 > 0.95，应去重"""
        docs = ["文档A", "文档A副本", "文档B"]
        distances = [0.20, 0.21, 0.60]
        metas = [{"source": "a"}, {"source": "a_copy"}, {"source": "b"}]
        # 模拟 embedding：文档A和副本几乎相同，文档B完全不同
        emb_a = [1.0, 0.0, 0.0]
        emb_a_dup = [0.99, 0.01, 0.0]  # cosine_sim ≈ 0.999
        emb_b = [0.0, 0.0, 1.0]        # 与 a 正交
        embeddings = [emb_a, emb_a_dup, emb_b]

        out_docs, out_dists, out_metas = _deduplicate(
            docs, distances, metas, 0.95, embeddings=embeddings
        )
        assert len(out_docs) == 2
        assert "文档A" in out_docs
        assert "文档B" in out_docs

    def test_empty_input(self):
        """空输入不崩溃"""
        out_docs, out_dists, out_metas = _deduplicate([], [], [], 0.95)
        assert out_docs == []

    def test_single_doc(self):
        """单条输入直接返回"""
        out_docs, out_dists, out_metas = _deduplicate(["doc"], [0.3], [{"s": "x"}], 0.95)
        assert len(out_docs) == 1


# ---------------------------------------------------------------------------
# T4: source_snippets 生成
# ---------------------------------------------------------------------------


class TestBuildSourceSnippets:
    """_build_source_snippets 函数测试"""

    def test_from_metadata_source(self):
        """优先从 metadata source 字段提取"""
        docs = ["完整文档内容很长的文本..."]
        metas = [{"source": "GB/T 18430.1 冷水机组性能测试规范"}]
        snippets = _build_source_snippets(docs, metas, max_len=50)
        assert len(snippets) == 1
        assert "GB/T 18430.1" in snippets[0]

    def test_fallback_to_doc_text(self):
        """metadata 无 source 时截取文档首行"""
        docs = ["冷水机组 COP 偏低的常见原因包括..."]
        metas = [{}]
        snippets = _build_source_snippets(docs, metas, max_len=50)
        assert len(snippets) == 1
        assert len(snippets[0]) <= 50

    def test_max_length_truncation(self):
        """超长来源被截断到 max_len"""
        docs = ["doc"]
        metas = [{"source": "x" * 100}]
        snippets = _build_source_snippets(docs, metas, max_len=50)
        assert len(snippets[0]) == 50


# ---------------------------------------------------------------------------
# T1: 阈值过滤（Mock ChromaDB）
# ---------------------------------------------------------------------------


def _make_mock_chroma(distances, docs, metas):
    """构造 Mock ChromaDB collection 和 client"""
    mock_col = MagicMock()
    mock_col.query.return_value = {
        "documents": [docs],
        "distances": [distances],
        "metadatas": [metas],
    }
    mock_col.name = "hvac_qa"

    mock_client = MagicMock()
    mock_client.list_collections.return_value = [mock_col]
    mock_client.get_collection.return_value = mock_col
    return mock_client


class TestConfidenceThreshold:
    """query_hvac_knowledge 的置信度阈值逻辑测试"""

    def _query_with_mock(self, distances, docs=None, metas=None):
        """用指定 distances 调用 query_hvac_knowledge，返回结果 dict"""
        n = len(distances)
        if docs is None:
            docs = [f"文档{i}" for i in range(n)]
        if metas is None:
            metas = [{"source": f"来源{i}"} for i in range(n)]

        mock_client = _make_mock_chroma(distances, docs, metas)

        with patch("chromadb.PersistentClient", return_value=mock_client), \
             patch("chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction"):
            from src.tools.query_hvac_knowledge import query_hvac_knowledge
            return query_hvac_knowledge("测试问题")

    def test_high_confidence_hvac_question(self):
        """HVAC 相关问题 distance < 0.6 → low_confidence=False"""
        result = self._query_with_mock([0.2, 0.35, 0.5])
        assert result["low_confidence"] is False
        assert result["query"] == "测试问题"
        assert len(result["results"]) == 3

    def test_low_confidence_irrelevant_question(self):
        """无关问题 distance > 0.6 → low_confidence=True"""
        result = self._query_with_mock([0.75, 0.82, 0.91])
        assert result["low_confidence"] is True

    def test_boundary_distance_exactly_threshold(self):
        """distance 恰好等于阈值 0.6 → 不标记 low_confidence（等于不算超过）"""
        result = self._query_with_mock([0.6, 0.7, 0.8])
        assert result["low_confidence"] is False

    def test_empty_results_low_confidence(self):
        """检索结果为空 → low_confidence=True"""
        result = self._query_with_mock([])
        assert result["low_confidence"] is True

    def test_source_snippets_populated(self):
        """正常检索结果应包含 source_snippets"""
        result = self._query_with_mock(
            [0.2, 0.3],
            docs=["冷水机组 COP 偏低原因分析...", "冷却塔风机故障排查步骤..."],
            metas=[{"source": "GB/T 18430.1"}, {"source": "冷却塔维护手册"}],
        )
        assert len(result["source_snippets"]) == 2
        assert "GB/T 18430.1" in result["source_snippets"][0]

    def test_top_k_respected(self):
        """返回结果数不超过 settings.rag.top_k"""
        result = self._query_with_mock([0.1, 0.2, 0.3, 0.4, 0.5])
        assert len(result["results"]) <= settings.rag.top_k


# ---------------------------------------------------------------------------
# T2: HVACExpertSkill.execute — 拒答逻辑
# ---------------------------------------------------------------------------


class TestHVACExpertSkillExecute:
    """HVACExpertSkill.execute 实例方法测试（BaseSkill 接口）"""

    def _make_prompts(self):
        return {
            "hvac_refusal": {"system": "【拒答指令】知识库中暂无相关信息"},
            "hvac_citation_format": {"system": "【引用格式】回答末尾标注依据"},
        }

    def _execute_skill(self, tool_results):
        """创建 Skill 实例并 Mock prompts 后执行。"""
        skill = HVACExpertSkill()
        with patch("src.skills.hvac_expert_skill.load_prompts", return_value=self._make_prompts()):
            return skill.execute(tool_results, {})

    def test_low_confidence_triggers_refusal(self):
        """low_confidence=True → hvac_context_hint 包含拒答指令"""
        tool_results = [
            ("query_hvac_knowledge", {
                "query": "量子力学在空调中的应用",
                "results": ["不相关内容"],
                "low_confidence": True,
                "source_snippets": ["无关来源"],
            }, {"question": "量子力学在空调中的应用"}),
        ]
        result = self._execute_skill(tool_results)
        hint = result["hvac_context_hint"]
        assert hint["low_confidence"] is True
        assert "拒答" in hint["system_suffix"]
        assert hint["context_override"]["low_confidence"] is True

    def test_normal_confidence_adds_citation(self):
        """low_confidence=False → hvac_context_hint 包含引用格式指令"""
        tool_results = [
            ("query_hvac_knowledge", {
                "query": "冷水机组 COP 偏低",
                "results": ["COP 偏低的常见原因..."],
                "low_confidence": False,
                "source_snippets": ["GB/T 18430.1"],
            }, {"question": "冷水机组 COP 偏低"}),
        ]
        result = self._execute_skill(tool_results)
        hint = result["hvac_context_hint"]
        assert hint["low_confidence"] is False
        assert "引用格式" in hint["system_suffix"]
        assert "GB/T 18430.1" in hint["system_suffix"]
        assert hint["context_override"] is None

    def test_no_hvac_tool_returns_empty(self):
        """没有 query_hvac_knowledge 工具调用 → 返回空 hvac_context_hint"""
        tool_results = [
            ("fetch_cop_data", {"cop": 4.2}, {"site_id": "SH-01"}),
        ]
        result = self._execute_skill(tool_results)
        hint = result["hvac_context_hint"]
        assert hint["system_suffix"] == ""
        assert hint["low_confidence"] is False

    def test_error_result_ignored(self):
        """query_hvac_knowledge 返回 error → 视为无结果"""
        tool_results = [
            ("query_hvac_knowledge", {"error": "知识库未初始化"}, {"question": "test"}),
        ]
        result = self._execute_skill(tool_results)
        hint = result["hvac_context_hint"]
        assert hint["system_suffix"] == ""
        assert hint["low_confidence"] is False


# ---------------------------------------------------------------------------
# T3: 引用来源格式验证
# ---------------------------------------------------------------------------


class TestCitationFormat:
    """验证 prompts/hvac_expert.yaml 中的引用格式配置"""

    def test_citation_prompt_exists(self):
        """prompts/hvac_expert.yaml 中应包含 hvac_citation_format"""
        from src.graph.nodes import _load_prompts
        prompts = _load_prompts()
        assert "hvac_citation_format" in prompts
        content = prompts["hvac_citation_format"]["system"]
        assert "依据" in content

    def test_refusal_prompt_exists(self):
        """prompts/hvac_expert.yaml 中应包含 hvac_refusal"""
        from src.graph.nodes import _load_prompts
        prompts = _load_prompts()
        assert "hvac_refusal" in prompts
        content = prompts["hvac_refusal"]["system"]
        assert "暂无相关信息" in content
