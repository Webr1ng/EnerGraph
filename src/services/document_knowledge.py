"""document_knowledge — 用户文件解析、登记、向量入库和检索服务

所属层：services
依赖：chromadb, sqlite3, src.schemas.document_knowledge, src.config.settings
对接算法层：N/A（本地 ChromaDB 文档检索）
"""
import hashlib
import json
import logging
import shutil
import sqlite3
import subprocess
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, List, Optional, Sequence, Tuple

from src.config.settings import settings
from src.schemas.document_knowledge import (
    DocumentKnowledgeResult,
    DocumentRecord,
    DocumentSource,
    DocumentStatus,
    DocumentUploadResult,
)
from src.tools.query_hvac_knowledge import _get_embedding_function

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STORAGE_DIR = PROJECT_ROOT / "data" / "knowledge_uploads"
DEFAULT_CHROMA_DIR = PROJECT_ROOT / "data" / "hvac_knowledge"
COLLECTION_NAME = "uploaded_documents"
SUPPORTED_SUFFIXES = {".doc", ".docx", ".txt", ".json", ".pdf"}


class DocumentProcessingError(ValueError):
    """可安全展示给用户的文档处理异常。"""


class DocumentKnowledgeService:
    """管理全局共享上传文档的生命周期和 RAG 检索。"""

    def __init__(
        self,
        storage_dir: Optional[Path] = None,
        chroma_dir: Optional[Path] = None,
        embedding_function: Optional[Any] = None,
    ) -> None:
        """初始化文档登记和向量库访问配置。

        Args:
            storage_dir: 原文件与 SQLite 登记目录，测试可注入临时目录。
            chroma_dir: Chroma 持久化目录，默认复用项目本地向量库目录。
            embedding_function: 可选的 Chroma Embedding Function，供测试注入。
        """
        self.storage_dir = Path(storage_dir or DEFAULT_STORAGE_DIR)
        self.chroma_dir = Path(chroma_dir or DEFAULT_CHROMA_DIR)
        self.registry_path = self.storage_dir / "registry.sqlite3"
        self.embedding_function = embedding_function
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._initialize_registry()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """打开登记 SQLite 连接并确保事务正确关闭。"""
        connection = sqlite3.connect(self.registry_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize_registry(self) -> None:
        """创建可重入的文档登记表。"""
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    document_id TEXT PRIMARY KEY,
                    file_name TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE,
                    file_size INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    failure_reason TEXT,
                    uploaded_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    knowledge_base_id TEXT NOT NULL DEFAULT 'global'
                )
                """
            )

    @staticmethod
    def _utc_now() -> datetime:
        """返回带时区的当前 UTC 时间。"""
        return datetime.now(timezone.utc)

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> DocumentRecord:
        """将 SQLite 行转换为强类型文档记录。"""
        return DocumentRecord(
            document_id=row["document_id"],
            file_name=row["file_name"],
            file_type=row["file_type"],
            content_hash=row["content_hash"],
            file_size=row["file_size"],
            status=DocumentStatus(row["status"]),
            failure_reason=row["failure_reason"],
            uploaded_at=datetime.fromisoformat(row["uploaded_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            chunk_count=row["chunk_count"],
            retry_count=row["retry_count"],
            knowledge_base_id=row["knowledge_base_id"],
        )

    def list_documents(self) -> List[DocumentRecord]:
        """按最近更新时间倒序列出已登记文档。

        Returns:
            所有文档登记记录。
        """
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM knowledge_documents ORDER BY updated_at DESC"
            ).fetchall()
        return [self._record_from_row(row) for row in rows]

    def get_document(self, document_id: str) -> Optional[DocumentRecord]:
        """读取一个文档登记记录。

        Args:
            document_id: 文档唯一 ID。

        Returns:
            存在时返回记录，否则返回 None。
        """
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM knowledge_documents WHERE document_id = ?", (document_id,)
            ).fetchone()
        return self._record_from_row(row) if row else None

    def upload_bytes(self, file_name: str, content: bytes) -> DocumentUploadResult:
        """保存上传文件并同步完成解析、切块和向量入库。

        Args:
            file_name: 客户端提供的原始文件名。
            content: 完整文件二进制内容。

        Returns:
            上传结果；解析失败时记录状态并返回 failed 文档。

        Raises:
            DocumentProcessingError: 文件格式或内容不符合第一期支持范围。
        """
        normalized_name = Path(file_name or "").name
        suffix = Path(normalized_name).suffix.lower()
        if not normalized_name or suffix not in SUPPORTED_SUFFIXES:
            supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
            raise DocumentProcessingError(f"暂不支持该文件类型，仅支持：{supported}")
        if not content:
            raise DocumentProcessingError("文件为空，无法入库")

        content_hash = hashlib.sha256(content).hexdigest()
        with self._connect() as connection:
            existing_row = connection.execute(
                "SELECT * FROM knowledge_documents WHERE content_hash = ?", (content_hash,)
            ).fetchone()
        if existing_row:
            existing = self._record_from_row(existing_row)
            return DocumentUploadResult(
                document=existing,
                duplicate=True,
                message="检测到相同文件，已复用已有文档。",
            )

        document_id = uuid.uuid4().hex
        now = self._utc_now()
        target_dir = self.storage_dir / document_id
        target_dir.mkdir(parents=True, exist_ok=False)
        raw_path = target_dir / normalized_name
        raw_path.write_bytes(content)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO knowledge_documents (
                    document_id, file_name, file_type, content_hash, file_size, status,
                    uploaded_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    normalized_name,
                    suffix.lstrip("."),
                    content_hash,
                    len(content),
                    DocumentStatus.UPLOADED.value,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return self.reprocess(document_id, increment_retry=False)

    def reprocess(self, document_id: str, increment_retry: bool = True) -> DocumentUploadResult:
        """从原文件重新解析并覆盖该文档的所有向量 chunks。

        Args:
            document_id: 待重解析的文档 ID。
            increment_retry: 手动重试时是否累加 retry_count。

        Returns:
            重解析后的文档状态。

        Raises:
            DocumentProcessingError: 文档不存在或原文件丢失。
        """
        record = self.get_document(document_id)
        if record is None:
            raise DocumentProcessingError("文档不存在")
        raw_path = self.storage_dir / document_id / record.file_name
        if not raw_path.is_file():
            self._set_status(document_id, DocumentStatus.FAILED, "原文件不存在，无法重新解析")
            return DocumentUploadResult(document=self.get_document(document_id), message="原文件不存在")

        self._set_status(
            document_id,
            DocumentStatus.PROCESSING,
            None,
            retry_increment=1 if increment_retry else 0,
            chunk_count=0,
        )
        try:
            sections = self._parse_file(raw_path, record.file_type)
            chunks = self._chunk_sections(sections)
            if not chunks:
                raise DocumentProcessingError("未提取到可入库的有效文本")
            self._delete_chunks(document_id)
            self._upsert_chunks(record, chunks)
            self._set_status(
                document_id, DocumentStatus.READY, None, chunk_count=len(chunks)
            )
            return DocumentUploadResult(
                document=self.get_document(document_id),
                message=f"已完成解析并入库，共 {len(chunks)} 个文本片段。",
            )
        except Exception as exc:
            logger.warning("文档 %s 入库失败: %s", document_id, exc)
            self._delete_chunks(document_id)
            self._set_status(document_id, DocumentStatus.FAILED, str(exc), chunk_count=0)
            return DocumentUploadResult(
                document=self.get_document(document_id),
                message=f"解析失败：{exc}",
            )

    def delete_document(self, document_id: str) -> bool:
        """删除一个文档及其 Chroma chunks 和原文件。

        Args:
            document_id: 待删除文档 ID。

        Returns:
            文档存在并删除时为 True；不存在时为 False。
        """
        record = self.get_document(document_id)
        if record is None:
            return False
        self._delete_chunks(document_id)
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM knowledge_documents WHERE document_id = ?", (document_id,)
            )
        shutil.rmtree(self.storage_dir / document_id, ignore_errors=True)
        return True

    def search(self, question: str) -> DocumentKnowledgeResult:
        """从已就绪上传文档检索与问题相关的文本 chunks。

        Args:
            question: 用户提出的文档问题。

        Returns:
            包含文本、距离和文件级来源的强类型检索结果。
        """
        normalized = question.strip()
        if not normalized:
            return DocumentKnowledgeResult(query=question, low_confidence=True)
        try:
            collection = self._get_collection(create=False)
        except Exception as exc:
            logger.info("文档知识库尚不可查询: %s", exc)
            return DocumentKnowledgeResult(query=question, low_confidence=True)
        if collection is None or collection.count() == 0:
            return DocumentKnowledgeResult(query=question, low_confidence=True)
        try:
            result = collection.query(
                query_texts=[normalized],
                n_results=settings.document_knowledge.top_k,
                include=["documents", "distances", "metadatas"],
            )
            documents = result.get("documents", [[]])[0] or []
            distances = [float(value) for value in (result.get("distances", [[]])[0] or [])]
            metadatas = result.get("metadatas", [[]])[0] or []
            sources = [
                DocumentSource(
                    document_id=str(meta.get("document_id", "")),
                    file_name=str(meta.get("file_name", "未知文件")),
                    page=int(meta["page"]) if meta.get("page") else None,
                    section=meta.get("section") or None,
                    chunk_index=int(meta.get("chunk_index", 0)),
                    snippet=document.strip().replace("\n", " ")[:160],
                )
                for document, meta in zip(documents, metadatas)
            ]
            low_confidence = (
                not distances
                or distances[0] > settings.document_knowledge.confidence_threshold
            )
            return DocumentKnowledgeResult(
                query=normalized,
                results=[] if low_confidence else documents,
                distances=distances,
                sources=[] if low_confidence else sources,
                low_confidence=low_confidence,
            )
        except Exception as exc:
            logger.error("文档知识库检索失败: %s", exc)
            return DocumentKnowledgeResult(query=normalized, low_confidence=True)

    def _set_status(
        self,
        document_id: str,
        status: DocumentStatus,
        failure_reason: Optional[str],
        retry_increment: int = 0,
        chunk_count: Optional[int] = None,
    ) -> None:
        """更新文档处理状态及附属字段。"""
        now = self._utc_now().isoformat()
        assignments = ["status = ?", "failure_reason = ?", "updated_at = ?"]
        params: List[Any] = [status.value, failure_reason, now]
        if retry_increment:
            assignments.append("retry_count = retry_count + ?")
            params.append(retry_increment)
        if chunk_count is not None:
            assignments.append("chunk_count = ?")
            params.append(chunk_count)
        params.append(document_id)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE knowledge_documents SET {', '.join(assignments)} WHERE document_id = ?",
                params,
            )

    def _parse_file(self, path: Path, file_type: str) -> List[Tuple[str, Optional[int], str]]:
        """按格式提取文本段，保留章节或页码来源。"""
        parsers = {
            "docx": self._parse_docx,
            "doc": self._parse_doc,
            "txt": self._parse_txt,
            "json": self._parse_json,
            "pdf": self._parse_pdf,
        }
        parser = parsers.get(file_type)
        if parser is None:
            raise DocumentProcessingError(f"暂不支持解析 .{file_type}")
        return parser(path)

    @staticmethod
    def _clean_text(text: str) -> str:
        """归一化文档文本，避免空白字符影响切块。"""
        lines = [" ".join(line.split()) for line in text.replace("\u00a0", " ").splitlines()]
        return "\n".join(line for line in lines if line).strip()

    def _parse_docx(self, path: Path) -> List[Tuple[str, Optional[int], str]]:
        """提取 DOCX 段落并以标题切分章节。"""
        try:
            from docx import Document
        except ImportError as exc:
            raise DocumentProcessingError("缺少 python-docx，无法解析 DOCX") from exc
        try:
            document = Document(path)
        except Exception as exc:
            raise DocumentProcessingError(f"DOCX 文件损坏或无法读取：{exc}") from exc
        sections: List[Tuple[str, Optional[int], str]] = []
        current_heading = "正文"
        buffer: List[str] = []
        for paragraph in document.paragraphs:
            text = self._clean_text(paragraph.text)
            if not text:
                continue
            style_name = (paragraph.style.name if paragraph.style else "").lower()
            if "heading" in style_name or "标题" in style_name:
                if buffer:
                    sections.append((current_heading, None, "\n".join(buffer)))
                    buffer = []
                current_heading = text
            else:
                buffer.append(text)
        if buffer:
            sections.append((current_heading, None, "\n".join(buffer)))
        if not sections:
            raise DocumentProcessingError("DOCX 中未提取到可用文本")
        return sections

    def _parse_doc(self, path: Path) -> List[Tuple[str, Optional[int], str]]:
        """通过 antiword 提取旧版 DOC 文本。"""
        try:
            completed = subprocess.run(
                ["antiword", str(path)], capture_output=True, text=True, timeout=30, check=False
            )
        except FileNotFoundError as exc:
            raise DocumentProcessingError("服务器未安装 antiword，暂无法解析 .doc 文件") from exc
        except subprocess.TimeoutExpired as exc:
            raise DocumentProcessingError("DOC 解析超时") from exc
        text = self._clean_text(completed.stdout)
        if completed.returncode != 0 or not text:
            detail = self._clean_text(completed.stderr) or "未提取到可用文本"
            raise DocumentProcessingError(f"DOC 解析失败：{detail}")
        return [("正文", None, text)]

    def _parse_txt(self, path: Path) -> List[Tuple[str, Optional[int], str]]:
        """按常见中文编码提取 TXT 文本。"""
        raw = path.read_bytes()
        for encoding in ("utf-8-sig", "utf-16", "gb18030", "gbk"):
            try:
                text = self._clean_text(raw.decode(encoding))
                if text:
                    return [("正文", None, text)]
            except UnicodeDecodeError:
                continue
        raise DocumentProcessingError("TXT 编码无法识别或未提取到有效文本")

    def _parse_json(self, path: Path) -> List[Tuple[str, Optional[int], str]]:
        """将 JSON 的字段路径和值展开为可检索文本。"""
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DocumentProcessingError(f"JSON 文件无效：{exc}") from exc
        lines: List[str] = []

        def flatten(value: Any, prefix: str = "") -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    flatten(item, f"{prefix}.{key}" if prefix else str(key))
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    flatten(item, f"{prefix}[{index}]")
            else:
                lines.append(f"{prefix}: {value}")

        flatten(data)
        text = self._clean_text("\n".join(lines))
        if not text:
            raise DocumentProcessingError("JSON 中未提取到可用字段")
        return [("JSON 数据", None, text)]

    def _parse_pdf(self, path: Path) -> List[Tuple[str, Optional[int], str]]:
        """逐页提取文字型 PDF；扫描件交由后续 OCR 能力处理。"""
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
        except Exception as exc:
            raise DocumentProcessingError(f"PDF 文件损坏或无法读取：{exc}") from exc
        sections: List[Tuple[str, Optional[int], str]] = []
        for index, page in enumerate(reader.pages, start=1):
            try:
                text = self._clean_text(page.extract_text() or "")
            except Exception as exc:
                raise DocumentProcessingError(f"PDF 第 {index} 页解析失败：{exc}") from exc
            if text:
                sections.append((f"第 {index} 页", index, text))
        if not sections:
            raise DocumentProcessingError("PDF 未提取到文字，扫描件 OCR 将在后续版本支持")
        return sections

    def _chunk_sections(
        self, sections: Sequence[Tuple[str, Optional[int], str]]
    ) -> List[Tuple[str, Optional[int], str]]:
        """按章节或页码生成带重叠窗口的文本 chunks。"""
        chunks: List[Tuple[str, Optional[int], str]] = []
        chunk_size = settings.document_knowledge.chunk_size
        overlap = settings.document_knowledge.chunk_overlap
        step = max(1, chunk_size - overlap)
        for section, page, raw_text in sections:
            text = self._clean_text(raw_text)
            for start in range(0, len(text), step):
                part = text[start:start + chunk_size].strip()
                if part:
                    chunks.append((section, page, part))
                if start + chunk_size >= len(text):
                    break
        return chunks

    def _get_collection(self, create: bool) -> Optional[Any]:
        """获取独立的上传文档 Chroma collection。"""
        import chromadb

        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        embedding_function = self.embedding_function or _get_embedding_function(
            settings.rag.embedding_local_files_only
        )
        client = chromadb.PersistentClient(path=str(self.chroma_dir))
        names = {collection.name for collection in client.list_collections()}
        if COLLECTION_NAME not in names and not create:
            return None
        if create:
            return client.get_or_create_collection(
                COLLECTION_NAME, embedding_function=embedding_function
            )
        return client.get_collection(COLLECTION_NAME, embedding_function=embedding_function)

    def _upsert_chunks(
        self, record: DocumentRecord, chunks: Sequence[Tuple[str, Optional[int], str]]
    ) -> None:
        """将切块文本及可追溯 metadata 写入 Chroma。"""
        collection = self._get_collection(create=True)
        uploaded_at = record.uploaded_at.isoformat()
        collection.upsert(
            ids=[f"{record.document_id}:{index}" for index in range(len(chunks))],
            documents=[text for _, _, text in chunks],
            metadatas=[
                {
                    "document_id": record.document_id,
                    "file_name": record.file_name,
                    "file_type": record.file_type,
                    "page": page or 0,
                    "section": section,
                    "chunk_index": index,
                    "uploaded_at": uploaded_at,
                    "knowledge_base_id": record.knowledge_base_id,
                }
                for index, (section, page, _text) in enumerate(chunks)
            ],
        )

    def _delete_chunks(self, document_id: str) -> None:
        """删除指定 document_id 的全部 Chroma chunks。"""
        try:
            collection = self._get_collection(create=False)
            if collection is not None:
                collection.delete(where={"document_id": document_id})
        except Exception as exc:
            logger.warning("删除文档 %s 的向量片段失败: %s", document_id, exc)
