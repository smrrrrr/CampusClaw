"""限定班级的知识库检索服务（rag-search）。

- 检索仅限指定 class_id 集合内、且所属材料 is_indexed=true 的分块
- 按余弦相似度降序返回 Top-K
- 输出带溯源字段：材料标题 filename、块序号 chunk_index、原文摘要
"""

from __future__ import annotations

import struct

from sqlalchemy.orm import Session

from config import settings
from embedding_service import cosine_similarity, embed_text
from models import Material, MaterialChunk


def _blob_to_vector(blob: bytes) -> list[float]:
    """将持久化的 float32 bytes 解回 list[float]。"""
    if not blob:
        return []
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _vector_to_blob(vec: list[float]) -> bytes:
    """将 list[float] 序列化为 float32 bytes（供持久化）。"""
    return struct.pack(f"{len(vec)}f", *vec)


def serialize_vector(vec: list[float]) -> bytes:
    """公开：供索引流程将向量写为 BLOB。"""
    return _vector_to_blob(vec)


def retrieve_top_k(
    db: Session,
    class_ids: list[int],
    query_text: str,
    k: int | None = None,
) -> list[dict]:
    """在指定班级集合内检索与 query_text 最相关的 Top-K 分块。

    仅查询 is_indexed=true 且 class_id 匹配的 MaterialChunk。
    返回列表按相似度降序，元素含：
        {material_id, filename, chunk_index, content, score}
    """
    k = k or settings.chunk_top_k
    if not class_ids or not query_text or not query_text.strip():
        return []

    q_vec = embed_text(query_text)
    rows = (
        db.query(MaterialChunk, Material.filename)
        .join(Material, Material.id == MaterialChunk.material_id)
        .filter(
            MaterialChunk.class_id.in_(class_ids),
            Material.is_indexed.is_(True),
        )
        .all()
    )

    scored: list[dict] = []
    for chunk, filename in rows:
        v = _blob_to_vector(chunk.embedding)
        if not v:
            continue
        score = cosine_similarity(q_vec, v)
        if score <= 0:
            continue
        excerpt = chunk.content.strip()
        scored.append(
            {
                "material_id": chunk.material_id,
                "filename": filename,
                "chunk_index": chunk.chunk_index,
                "content": excerpt,
                "score": round(score, 4),
            }
        )

    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:k]