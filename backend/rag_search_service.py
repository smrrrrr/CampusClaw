"""限定班级的知识库检索服务（rag-search）。

- 检索仅限指定 class_id 集合内、且所属材料 is_indexed=true 的分块
- 按余弦相似度降序返回 Top-K
- 输出带溯源字段：材料标题 filename、块序号 chunk_index、原文摘要
"""

from __future__ import annotations

import math
import re
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
    """字符二元组集合（用于轻量关键字/标题预筛，中文无需分词）。"""
    s = text.strip()
    return {s[i : i + 2] for i in range(len(s) - 1)} if len(s) >= 2 else ({s} if s else set())


def _idf_weights(query_terms: set[str], doc_counts: dict[str, int], n: int) -> dict[str, float]:
    """给查询词元打 IDF 权重：在一批候选块中出现越普遍的词权重越低。

    反例进"向量（几乎每块都有）"这类泛词，避免纯 TF 让"反复提到泛词的块"
    干扰排序；让"夹角/公式/cos/坐标"这类稀有的判别性词主导排序。
    """
    if n <= 0:
        return {t: 1.0 for t in query_terms}
    weights: dict[str, float] = {}
    for t in query_terms:
        df = doc_counts.get(t, 0)
        weights[t] = math.log(1.0 + n / (df + 1.0)) if df > 0 else 1.0
    return weights


def _keyword_score(query_terms: set[str], content: str, weights: dict[str, float] | None = None) -> float:
    """关键字打分：查询词元（字符二元组）在分块内容中出现的加权次数之和。

    默认按出现次数（TF，旧行为）；提供 weights（IDF 表）时按权重加权，
    让稀有判别词（公式/夹角/cos）主导，抑制高频泛词（向量）。
    """
    if not query_terms or not content:
        return 0.0
    if not weights:
        return float(sum(content.count(t) for t in query_terms))
    return float(sum(content.count(t) * weights.get(t, 1.0) for t in query_terms))


def _rrf_fuse(method_lists: list[list[int]], k: int = 60) -> dict[int, float]:
    """Reciprocal Rank Fusion：将多个检索方法的文档排序融合为单一得分。

    每个方法给出一个按相关度降序的 chunk_id 列表，得分 = SUM(1/(k+rank))。
    """
    fused: dict[int, float] = {}
    for ranking in method_lists:
        if not ranking:
            continue
        for rank, cid in enumerate(ranking, start=1):
            fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + rank)
    return fused


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


def _clamp_to_formulas(content: str, start: int, end: int) -> tuple[int, int]:
    """把摘要截断边界对齐到 `$...$` / `$$...$$` 公式定界符。

    定长窗口截断可能恰好切在某个公式中间，使 `$` 定界符不成对，前后端
    渲染时 KaTeX/remark-math 解析失败、公式源码直显。此函数找到与边界
    重叠的公式区间并向外扩到完整公式，保证追溯摘要中的公式始终闭合。
    """
    if "$" not in content:
        return start, end
    spans = [(m.start(), m.end() - 1) for m in re.finditer(r"\$\$[^$]+?\$\$|\$[^$]+?\$", content)]
    if not spans:
        return start, end
    new_start, new_end = start, end
    for f_start, f_end in spans:  # f_end 为闭合定界符所在索引（含）
        # 起点落在公式中间：公式在 start 之前打开，在 start 之后闭合
        if f_start < start <= f_end:
            new_start = min(new_start, f_start)
            new_end = max(new_end, f_end + 1)
        # 终点落在公式中间：公式在 end 之前打开，在 end 之后闭合
        if f_start <= end < f_end:
            new_start = min(new_start, f_start)
            new_end = max(new_end, f_end + 1)
    return new_start, new_end


def best_snippet(content: str, query: str, window: int = 200) -> str:
    """从分块中提取与查询最相关的连续子片段，作为溯源摘要。

    讲义材料常把「知识点讲解」与【即学即练】练习题段落交错排布，直接
    取分块前 N 字可能截到与问题无关的题干/选项。故滑动窗口找出与查询
    字符二元组重叠最密集的一段作为摘要，优先展示被问到的知识点讲解，
    避免参考资料变成一墙练习题。
    """
    if not query or not content or len(content) <= window:
        snippet = content[:window]
        return snippet + ("…" if len(content) > window else "")

    q_bigrams = _char_bigrams(query)
    if not q_bigrams:
        snippet = content[:window]
        return snippet + ("…" if len(content) > window else "")

    best_start, best_score = 0, -1
    step = max(1, window // 4)
    for start in range(0, len(content) - window + 1, step):
        seg = content[start : start + window]
        score = sum(seg.count(t) for t in q_bigrams)
        if score > best_score:
            best_score, best_start = score, start

    new_start, new_end = _clamp_to_formulas(content, best_start, best_start + window)
    snippet = content[new_start:new_end].strip()
    if new_start > 0:
        snippet = "…" + snippet
    if new_end < len(content):
        snippet += "…"
    return snippet


def retrieve_top_k(
    db: Session,
    class_ids: list[int],
    query_text: str,
    k: int | None = None,
    mode: str | None = None,
    material_ids: list[int] | None = None,
) -> list[dict]:
    """在指定班级集合内检索与 query_text 最相关的 Top-K 分块。

    仅查询 is_indexed=true 且 class_id 匹配的 MaterialChunk。
    检索模式：
      - vector：仅向量余弦相似度
      - keyword：仅关键字符号重叠（TF）
      - hybrid（默认）：向量 + 关键字，RRF 融合排序
    返回列表按相关性降序，元素含：
        {material_id, filename, chunk_index, content, score}
    """
    k = k or settings.chunk_top_k
    mode = (mode or settings.retrieval_mode).lower()
    if not class_ids or not query_text or not query_text.strip():
        return []

    # 材料标题预筛（轻量关键词），减少跨章节误排
    material_query = (
        db.query(Material.id, Material.filename)
        .filter(
            Material.class_id.in_(class_ids),
            Material.is_indexed.is_(True),
        )
    )
    if material_ids is not None:
        material_query = material_query.filter(Material.id.in_(material_ids))
    materials = material_query.all()
    eligible_material_ids = _prefilter_materials(query_text, materials)

    q_vec = embed_text(query_text)
    q_terms = _char_bigrams(query_text)
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

    # 先统计各查询词元在候选块中的文档频率（DF），用于 IDF 加权关键字打分
    all_contents = [chunk.content for chunk, _ in rows]
    doc_counts: dict[str, int] = {}
    for c in all_contents:
        for t in q_terms:
            if t in c:
                doc_counts[t] = doc_counts.get(t, 0) + 1
    kw_weights = _idf_weights(q_terms, doc_counts, len(all_contents))

    # 逐块计算向量相似度与关键字重叠两种独立信号
    chunks: list[dict] = []
    for chunk, filename in rows:
        v = _blob_to_vector(chunk.embedding)
        cosine = cosine_similarity(q_vec, v) if v else 0.0
        kw = _keyword_score(q_terms, chunk.content, kw_weights) if kw_weights else 0.0
        kw_raw = _keyword_score(q_terms, chunk.content)  # 原始重叠数，用于绝对词元门槛
        if cosine <= 0 and kw <= 0:
            continue  # 双信号都无相关，直接排除
        chunks.append(
            {
                "id": chunk.id,
                "material_id": chunk.material_id,
                "filename": filename,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content.strip(),
                "cosine": cosine,
                "kw": kw,
                "kw_raw": kw_raw,
            }
        )

    if not chunks:
        return []

    # 绝对词元门槛：即便余弦因哈希巧合给出正分，只要问题与所有候选块
    # 无实质字符二元组重叠（如问无关的「食堂营业时间」），即视为本班
    # 未找到相关资料，不返回任何引用，避免给「未找到」的回答误标出处。
    if max(c["kw_raw"] for c in chunks) < settings.chunk_min_keyword_hits:
        return []

    if mode == "keyword":
        chunks.sort(key=lambda c: (c["kw"], c["cosine"]), reverse=True)
        for c in chunks:
            c["score"] = round(c["kw"], 4)
    elif mode == "vector":
        chunks.sort(key=lambda c: c["cosine"], reverse=True)
        for c in chunks:
            c["score"] = round(c["cosine"], 4)
    else:  # hybrid：RRF 融合
        vec_ranked = [c["id"] for c in sorted(chunks, key=lambda c: c["cosine"], reverse=True)]
        kw_ranked = [c["id"] for c in sorted(chunks, key=lambda c: c["kw"], reverse=True)]
        fused = _rrf_fuse([vec_ranked, kw_ranked])
        chunks.sort(key=lambda c: fused.get(c["id"], 0.0), reverse=True)
        for c in chunks:
            c["score"] = round(fused.get(c["id"], 0.0), 6)

    # 相关度下限：低于最优命中分数 × 配置比例 的块视为低相关剔除，
    # 避免 Top-K 硬凑条数（如章节总览/跨知识点的弱相关块混入资料列表）
    max_score = chunks[0]["score"] if chunks else 0.0
    if max_score > 0 and settings.chunk_min_relevance > 0:
        floor = max_score * settings.chunk_min_relevance
        chunks = [c for c in chunks if c["score"] >= floor]

    if not chunks:
        return []

    return [
        {
            "material_id": c["material_id"],
            "filename": c["filename"],
            "chunk_index": c["chunk_index"],
            "content": c["content"],
            "score": c["score"],
        }
        for c in chunks[:k]
    ]
