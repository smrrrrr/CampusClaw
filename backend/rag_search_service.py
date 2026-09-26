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


def _char_bigrams(text: str) -> set[str]:
    """字符二元组集合（用于轻量标题预筛，中文无需分词）。"""
    s = text.strip()
    return {s[i : i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else ({s} if s else set())


def _prefilter_materials(query_text: str, candidates: list[tuple[int, str]]) -> set[int]:
    """轻量标题预筛：仅让与问题共享实质关键词的材料参与向量排序。

    由于字符 n-gram 哈希向量对"字面重叠但不同章节"的材料可能误排高分
    （如 3D 空间几何问题把"平面解析几何"排到前面），在向量排序前按
    材料标题与问题的字符二元组重叠做一个粗筛，排除明确不相关的章节。

    兜底：若按重叠筛选后没有任何材料保留（如班级只有统练/期中/月考等
    泛化标题材料），则回退为保留全部候选，避免检索结果为空。
    """
    q_bigrams = _char_bigrams(query_text)
    if not q_bigrams or not candidates:
        return {mid for mid, _ in candidates}

    keep = {mid for mid, filename in candidates if q_bigrams & _char_bigrams(filename)}
    if not keep:
        return {mid for mid, _ in candidates}  # 兜底：全保留
    return keep


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

    # 材料标题预筛（轻量关键词），减少跨章节误排
    materials = (
        db.query(Material.id, Material.filename)
        .filter(
            Material.class_id.in_(class_ids),
            Material.is_indexed.is_(True),
        )
        .all()
    )
    eligible_material_ids = _prefilter_materials(query_text, materials)

    q_vec = embed_text(query_text)
    rows = (
        db.query(MaterialChunk, Material.filename)
        .join(Material, Material.id == MaterialChunk.material_id)
        .filter(
            MaterialChunk.class_id.in_(class_ids),
            Material.is_indexed.is_(True),
            MaterialChunk.material_id.in_(eligible_material_ids),
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