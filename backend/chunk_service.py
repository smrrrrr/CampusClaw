"""文本分块服务（design.md 决策 1，本地优化版）。

为避免定长滑动窗口把"概念标题 + 公式"从中间劈开（如"向量夹角公式"
的标题落在上一块、公式体却落到下一块，严重稀释检索信噪比），改为：

1. 先把整份文本按**语义锚点**切成逻辑段（segment）：
   - Markdown 标题（`##` / `### …`）
   - 加粗子标签行（`**向量夹角公式**：`、`**线面角公式**：` 等定义/公式入口）
   这样每个公式、每条定义都尽量自成一段，作为独立可检索单元。

2. 段长 ≤ chunk_size 时整段保留；超长的段再按空白行（段落）贪婪合并，
   用 overlap 保持上下文连续，避免单段被硬性切割。

零外部依赖、纯文本层处理，无需分词。
"""

from __future__ import annotations

import re

from config import settings


def _is_segment_anchor(line: str) -> bool:
    """判断某行是否为"新逻辑段"锚点（标题或加粗子标签）。"""
    s = line.strip()
    # 去掉列表前缀（`* ` / `- ` / `• ` 等），便于识别行内槽点
    s = re.sub(r"^[*+•\-]\s+", "", s)
    if not s:
        return False
    if re.match(r"^#{1,6}\s", s):
        return True
    # 加粗子标签：**xxx** 后紧跟[： :]或换行，如 **向量夹角公式**：
    if re.match(r"\*\*[^*\n]{1,40}\*\*\s*[：:]\s*$", s):
        return True
    return False


def _split_segments(text: str) -> list[str]:
    """按语义锚点切成逻辑段，锚点行归属新段开头。"""
    lines = text.split("\n")
    segments: list[str] = []
    cur: list[str] = []
    for ln in lines:
        if cur and _is_segment_anchor(ln):
            segments.append("\n".join(cur))
            cur = [ln]
        else:
            cur.append(ln)
    if cur:
        segments.append("\n".join(cur))
    return [s.strip() for s in segments if s.strip()]


def _split_paragraphs(segment: str) -> list[str]:
    """将单个逻辑段按空白行分裂为段落块（保留公式完整性）。"""
    return [p.strip() for p in re.split(r"\n\s*\n", segment) if p.strip()]


def _greedy_merge(paras: list[str], chunk_size: int, overlap: int) -> list[str]:
    """贪心合并段落为 ≤ chunk_size 的块，块间带 overlap 保持连续。"""
    if not paras:
        return []
    chunks: list[str] = []
    cur = ""
    for p in paras:
        if not cur:
            cur = p
        elif len(cur) + 1 + len(p) <= chunk_size:
            cur = cur + "\n" + p
        else:
            chunks.append(cur)
            # 携带上一块尾部 overlap 字符，保证概念衔接不被硬断
            cur = cur[-overlap:] + "\n" + p if overlap > 0 else p
    if cur.strip():
        chunks.append(cur)
    return chunks


def _hard_split(s: str, chunk_size: int, overlap: int) -> list[str]:
    """兜底：单段超长时按字符滑动切分（尽量避开公式定界符）。"""
    if len(s) <= chunk_size:
        return [s]
    step = max(1, chunk_size - overlap)
    out: list[str] = []
    start = 0
    n = len(s)
    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            # 优先对齐换行；再尝试对齐空格；都不行则硬切
            nl = s.rfind("\n", start, end)
            if nl > start + chunk_size // 2:
                end = nl + 1
            else:
                sp = s.rfind(" ", start, end)
                if sp > start + chunk_size // 2:
                    end = sp
        out.append(s[start:end].strip())
        if end == start:
            break
        start = max(start + step, end - overlap) if overlap else end
        if start >= n:
            break
    return [c for c in out if c]


def _split_text_chunks(
    text: str, chunk_size: int, overlap: int
) -> list[str]:
    """将文本切分为 list 文本块（不编号，编号由调用方分配）。"""
    text = text.strip()
    if not text:
        return []

    chunks: list[str] = []
    for segment in _split_segments(text):
        if len(segment) <= chunk_size:
            chunks.append(segment)
            continue
        paras = _split_paragraphs(segment)
        if len(paras) <= 1:
            massive = _hard_split(segment, chunk_size, overlap)
            chunks.extend(massive)
        else:
            chunks.extend(_greedy_merge(paras, chunk_size, overlap))
    return chunks


def chunk_text(text: str | None) -> list[str]:
    """公开入口：按配置切分文本，返回无序的文本块列表。"""
    if not text:
        return []
    return _split_text_chunks(text, settings.chunk_size, settings.chunk_overlap)