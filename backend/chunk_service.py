"""文本分块服务（design.md 决策 1）。

按固定长度 + 重叠的滑动窗口将整份纯文本切分为带序号的文本块。
优先在换行 / 段落边界对齐；无自然边界时按字符硬切。
"""

from __future__ import annotations

from config import settings


def _split_text_chunks(
    text: str, chunk_size: int, overlap: int
) -> list[str]:
    """将文本切分为 list 文本块（不编号，编号由调用方分配）。

    - 空文本 → 返回空列表（调用方决定是否跳过索引）
    - 单块：text 长度 ≤ chunk_size → 1 块
    - 多块：滑动窗口，每步前进 (chunk_size - overlap)
    """
    text = text.strip()
    if not text:
        return []

    if len(text) <= chunk_size:
        return [text]

    step = max(1, chunk_size - overlap)
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))

        # 边界对齐：若非最后一段且当前 slice 尾部处于句子/段落中间，
        # 尽量前移 end 到最近换行或空格，避免割裂语义。
        if end < len(text):
            window = text[start:end]
            # 优先对齐换行
            nl = window.rfind("\n")
            if nl > chunk_size // 2:
                end = start + nl + 1
            else:
                sp = window.rfind(" ", chunk_size // 2)
                if sp != -1:
                    end = start + sp

        chunks.append(text[start:end])
        start = start + step

    return chunks


def chunk_text(text: str | None) -> list[str]:
    """公开入口：按配置切分文本，返回无序的文本块列表。"""
    if not text:
        return []
    return _split_text_chunks(text, settings.chunk_size, settings.chunk_overlap)