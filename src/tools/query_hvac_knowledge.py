"""query_hvac_knowledge — HVAC 知识库 RAG 检索工具

所属层：tools
依赖：chromadb, src.schemas.v3_engine, src.config.settings
对接算法层：N/A（本地向量库）

Phase 3 升级：
  - T1: distance 阈值过滤，低置信度标记 low_confidence
  - T2: 不支持主题 guard，覆盖向量近邻造成的域外误命中
  - T4: MMR 去重（相似度 > dedup_similarity 的重复片段剔除）
"""
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

from src.config.settings import settings
from src.schemas.v3_engine import HVACKnowledgeResult

logger = logging.getLogger(__name__)

DB_PATH = str(Path(__file__).resolve().parents[2] / "data" / "hvac_knowledge")
COLLECTION_NAME = "hvac_qa"


def _has_unsupported_topic(question: str, unsupported_terms: List[str]) -> bool:
    """判断问题是否命中知识库明确不支持的主题。

    向量距离只能衡量语义近邻，不能证明知识库能够回答。例如“量子纠缠提高
    COP”会因包含 COP 而召回暖通文档，因此在距离判定前增加可配置的主题 guard。

    Args:
        question: 用户问题。
        unsupported_terms: 明确不支持的主题词。

    Returns:
        命中任一非空主题词时返回 True。
    """
    normalized = question.casefold()
    return any(term.strip().casefold() in normalized for term in unsupported_terms if term.strip())


@lru_cache(maxsize=2)
def _get_embedding_function(local_files_only: bool) -> Any:
    """创建并缓存 HVAC embedding function。

    Args:
        local_files_only: 是否仅使用本地 Hugging Face 缓存。

    Returns:
        ChromaDB SentenceTransformerEmbeddingFunction 实例。

    Raises:
        ImportError: sentence-transformers 未安装。
        OSError: 本地模式下模型缓存不存在或不完整。
    """
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    return SentenceTransformerEmbeddingFunction(
        model_name="BAAI/bge-small-zh-v1.5",
        local_files_only=local_files_only,
    )


def _deduplicate(
    docs: List[str],
    distances: List[float],
    metadatas: List[dict],
    similarity_threshold: float,
    embeddings: List[List[float]] = None,
) -> tuple:
    """对检索结果进行 MMR 风格去重，剔除相似度超过阈值的重复片段。

    使用文档 embedding 计算余弦相似度，而非仅比较 distance 值。
    若未提供 embeddings，则仅用 distance 差值做粗略过滤（放宽阈值）。

    Args:
        docs: 检索文档列表
        distances: 对应的 distance 列表
        metadatas: 对应的 metadata 列表
        similarity_threshold: 相似度阈值（0.95 = cosine_sim > 0.95 视为重复）
        embeddings: 可选，文档的 embedding 向量列表

    Returns:
        (去重后的 docs, distances, metadatas)
    """
    if len(docs) <= 1:
        return docs, distances, metadatas

    selected_docs: List[str] = []
    selected_distances: List[float] = []
    selected_metas: List[dict] = []
    selected_embeddings: List[List[float]] = []

    for idx, (doc, dist, meta) in enumerate(zip(docs, distances, metadatas)):
        is_dup = False

        # 修复：避免对 NumPy 数组直接布尔判断
        if embeddings is not None and len(embeddings) > idx:
            # 精确去重：计算与已选文档的余弦相似度
            emb = embeddings[idx]
            for sel_emb in selected_embeddings:
                cos_sim = _cosine_similarity(emb, sel_emb)
                if cos_sim > similarity_threshold:
                    is_dup = True
                    break
        else:
            # 粗略去重：仅用 distance 差值，放宽阈值避免误删
            for sel_dist in selected_distances:
                if abs(dist - sel_dist) < 0.005:
                    is_dup = True
                    break

        if not is_dup:
            selected_docs.append(doc)
            selected_distances.append(dist)
            selected_metas.append(meta)
            # 修复：避免对 NumPy 数组直接布尔判断
            if embeddings is not None and len(embeddings) > idx:
                selected_embeddings.append(embeddings[idx])

    logger.debug(f"去重前: {len(docs)} 条, 去重后: {len(selected_docs)} 条")
    return selected_docs, selected_distances, selected_metas


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """计算两个向量的余弦相似度。"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _build_source_snippets(docs: List[str], metadatas: List[dict], max_len: int = 50) -> List[str]:
    """从检索结果中提取引用来源摘要（≤50字）。

    优先从 metadata 的 source/title 字段提取，否则截取文档前 50 字符。
    """
    snippets = []
    for doc, meta in zip(docs, metadatas):
        source = meta.get("source") or meta.get("title") or meta.get("file_name") or ""
        if source:
            snippet = source[:max_len]
        else:
            # 取文档第一行（去掉空行）截取 50 字
            first_line = doc.strip().split("\n")[0] if doc.strip() else ""
            snippet = first_line[:max_len]
        snippets.append(snippet)
    return snippets


def query_hvac_knowledge(question: str) -> Dict[str, Any]:
    """从 HVAC 知识库检索与问题最相关的 Q&A。

    Phase 3 升级：
      - 支持 distance 阈值过滤（low_confidence 标记）
      - 支持 MMR 去重（剔除高度相似片段）
      - 生成 source_snippets 供引用来源标注

    Args:
        question: 用户的暖通空调相关问题

    Returns:
        HVACKnowledgeResult 的 dict 表示，或含 error 键的 dict
    """
    try:
        import chromadb

        top_k = settings.rag.top_k
        confidence_threshold = settings.rag.confidence_threshold
        dedup_similarity = settings.rag.dedup_similarity

        try:
            ef = _get_embedding_function(settings.rag.embedding_local_files_only)
        except ImportError as e:
            return {"error": f"query_hvac_knowledge: 需要 sentence-transformers 库: {e}"}

        client = chromadb.PersistentClient(path=DB_PATH)
        existing = [c.name for c in client.list_collections()]
        if COLLECTION_NAME not in existing:
            return {"error": "query_hvac_knowledge: 知识库尚未初始化，请先运行 python -m src.pipelines.rag_ingest"}

        col = client.get_collection(COLLECTION_NAME, embedding_function=ef)

        # 多取几条用于去重后仍有足够结果
        fetch_k = top_k + 2
        res = col.query(
            query_texts=[question],
            n_results=fetch_k,
            include=["documents", "distances", "metadatas", "embeddings"],
        )
        docs = res["documents"][0]
        metas = res["metadatas"][0]
        distances = res["distances"][0]
        # 修复：避免对 NumPy 数组直接布尔判断
        emb_data = res.get("embeddings")
        embeddings = emb_data[0] if emb_data is not None and len(emb_data) > 0 else None

        # T4: MMR 去重（使用文档 embedding 计算余弦相似度）
        docs, distances, metas = _deduplicate(
            docs, distances, metas, dedup_similarity,
            embeddings=embeddings,
        )

        # 截取 top_k
        docs = docs[:top_k]
        distances = distances[:top_k]
        metas = metas[:top_k]

        # T1: 置信度阈值过滤
        # 确保 distances[0] 是标量值（避免 NumPy 数组布尔判断错误）
        first_distance = float(distances[0]) if len(distances) > 0 else float('inf')
        unsupported_topic = _has_unsupported_topic(
            question, settings.rag.unsupported_topic_terms,
        )
        low_confidence = (
            len(distances) == 0
            or first_distance > confidence_threshold
            or unsupported_topic
        )

        # 生成引用来源摘要
        source_snippets = _build_source_snippets(docs, metas)

        return HVACKnowledgeResult(
            query=question,
            results=docs,
            system_types=[m.get("system_type", "general") for m in metas],
            distances=distances,
            low_confidence=low_confidence,
            source_snippets=source_snippets,
        ).model_dump()
    except Exception as e:
        logger.error(f"query_hvac_knowledge 失败: {e}")
        return {"error": f"query_hvac_knowledge: {e}"}


def prewarm_hvac_knowledge() -> Dict[str, Any]:
    """预热当前进程的 embedding 模型、Chroma collection 与首次查询路径。

    Uvicorn 生产模式使用多个独立 Worker，进程内 ``lru_cache`` 无法跨 Worker
    共享。每个 Worker 启动时执行一次稳定查询，可将 20 秒级首次加载移出用户请求。

    Returns:
        预热结果摘要；失败时沿用 query_hvac_knowledge 的 error 字段。
    """
    result = query_hvac_knowledge("冷水机组 COP 的含义")
    if result.get("error"):
        return result
    return {
        "ok": True,
        "result_count": len(result.get("results", [])),
        "low_confidence": bool(result.get("low_confidence")),
    }
