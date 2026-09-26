"""材料上传业务服务：文件校验、存储、重命名、异步文本解析、AI 检索上下文。

校验流程（design.md 决策 4/6）：
    大小 ≤ 50MB → 读取文件头 magic number → 校验 MIME → 写入磁盘 → 写入 DB → 异步解析
"""

from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

from sqlalchemy.orm import Session

from config import settings
from models import Material, MaterialChunk, MaterialContent

# ---------------------------------------------------------------------------
# 常量：允许的格式、MIME 映射、magic number
# ---------------------------------------------------------------------------

# 扩展名 → 标准 MIME（前端 accept 与后端校验共用）
_EXT_TO_MIME: dict[str, str] = {
    "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
}

# magic number → 通用类别（不信任扩展名，以文件头为准）
_MAGIC_PATTERNS: list[tuple[bytes, str]] = [
    (b"%PDF", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"PK\x03\x04", "zip"),  # PPTX / DOCX 均为 ZIP
]

MAX_FILE_SIZE = settings.max_file_size_mb * 1024 * 1024  # 50MB


# ---------------------------------------------------------------------------
# 文件校验
# ---------------------------------------------------------------------------


def get_file_ext(filename: str) -> str:
    """提取小写扩展名（不含点）。"""
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def detect_category(head: bytes) -> str | None:
    """读取文件头字节判断真实文件类别（不信任扩展名）。"""
    for magic, category in _MAGIC_PATTERNS:
        if head.startswith(magic):
            return category
    return None


def detect_office_mime(file_bytes: bytes) -> str | None:
    """ZIP 文件内部结构区分 PPTX / DOCX（比扩展名更可靠）。"""
    try:
        zf = zipfile.ZipFile(io.BytesIO(file_bytes))
        names = set(zf.namelist())
        if "ppt/presentation.xml" in names:
            return _EXT_TO_MIME["pptx"]
        if "word/document.xml" in names:
            return _EXT_TO_MIME["docx"]
    except Exception:
        return None
    return None


def validate_upload_file(file_bytes: bytes, filename: str) -> tuple[str, str]:
    """校验文件大小 + magic number + MIME，返回 (mime_type, ext)。

    - 大小超限 → ValueError
    - magic number 不匹配扩展名 → ValueError（伪造扩展名拦截）
    - PPTX/DOCX 通过 ZIP 内部结构区分
    """
    size = len(file_bytes)
    if size > MAX_FILE_SIZE:
        raise ValueError(f"文件大小 {size} 字节超过上限 {MAX_FILE_SIZE} 字节（{settings.max_file_size_mb}MB）")

    if size == 0:
        raise ValueError("文件为空")

    ext = get_file_ext(filename)
    if ext not in _EXT_TO_MIME:
        raise ValueError(f"不支持的文件格式：{ext or '无扩展名'}，仅允许 {settings.allowed_extensions}")

    head = file_bytes[:16]
    category = detect_category(head)

    if category is None:
        raise ValueError("无法识别文件类型，文件头不匹配任何允许格式")

    # 交叉校验：扩展名与 magic number 必须一致
    if ext == "pdf" and category != "pdf":
        raise ValueError("文件头不是 PDF 格式（%PDF），疑似伪造扩展名")
    if ext in ("jpg", "jpeg") and category != "jpg":
        raise ValueError("文件头不是 JPEG 格式（\\xFF\\xD8\\xFF），疑似伪造扩展名")
    if ext == "png" and category != "png":
        raise ValueError("文件头不是 PNG 格式（\\x89PNG），疑似伪造扩展名")
    if ext in ("pptx", "docx") and category != "zip":
        raise ValueError("文件头不是 Office OOXML 格式（PK），疑似伪造扩展名")

    # PPTX/DOCX 进一步区分
    if ext in ("pptx", "docx"):
        office_mime = detect_office_mime(file_bytes)
        if office_mime is None:
            raise ValueError("ZIP 文件内部结构不是有效的 PPTX/DOCX")
        return office_mime, ext

    return _EXT_TO_MIME[ext], ext


# ---------------------------------------------------------------------------
# 文件存储
# ---------------------------------------------------------------------------


def get_upload_root() -> Path:
    """上传根目录（绝对路径）。本地 dev：backend/uploads；Docker：/app/uploads。"""
    return Path(settings.upload_dir).resolve()


def build_relative_path(class_id: int, filename: str) -> str:
    """生成存储相对路径：{class_id}/{timestamp}_{filename}（design.md 决策 3）。

    同名文件自动加时间戳前缀，保证全局唯一不覆盖。
    同一秒内多次上传同名文件时追加计数器避免覆盖。
    """
    ts = int(time.time())
    relative = f"{class_id}/{ts}_{filename}"
    # 同秒碰撞检测：若文件已存在则追加计数器
    counter = 1
    while resolve_abs_path(relative).exists():
        relative = f"{class_id}/{ts}_{counter}_{filename}"
        counter += 1
    return relative


def resolve_abs_path(relative_path: str) -> Path:
    """将 DB 中存储的相对路径解析为磁盘绝对路径。"""
    return get_upload_root() / relative_path


def write_physical_file(file_bytes: bytes, relative_path: str) -> Path:
    """写入物理文件到 upload_dir/{class_id}/ 子目录（design.md 决策 2）。

    自动创建 class_id 子目录。返回绝对路径。
    """
    abs_path = resolve_abs_path(relative_path)
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(file_bytes)
    return abs_path


def delete_physical_file(relative_path: str) -> None:
    """回滚时删除物理文件（design.md 决策 6）。文件不存在则静默。"""
    try:
        abs_path = resolve_abs_path(relative_path)
        if abs_path.exists():
            abs_path.unlink()
    except Exception:
        # 回滚清理失败不应阻塞主流程，仅记录
        pass


# ---------------------------------------------------------------------------
# 异步文本解析（design.md 决策 5）
# ---------------------------------------------------------------------------


def _extract_pdf(file_path: Path) -> str:
    """PyMuPDF (fitz) 提取 PDF 纯文本。"""
    import fitz  # type: ignore[import-not-found]

    text_parts: list[str] = []
    doc = fitz.open(str(file_path))
    try:
        for page in doc:
            text_parts.append(page.get_text())
    finally:
        doc.close()
    return "\n".join(text_parts).strip()


def _extract_pptx(file_path: Path) -> str:
    """python-pptx 提取 PPTX 纯文本（每页文本框）。"""
    from pptx import Presentation  # type: ignore[import-not-found]

    parts: list[str] = []
    prs = Presentation(str(file_path))
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                txt = shape.text_frame.text.strip()
                if txt:
                    parts.append(txt)
    return "\n".join(parts).strip()


# OOXML 命名空间：Word 正文(w) 与 数学公式(OMML, m)
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def _qn(tag: str) -> str:
    """取带命名空间元素 tag 的 localname（如 '{ns}oMath' -> 'oMath'）。"""
    return tag.rsplit("}", 1)[-1]


def _omml_to_latex(node) -> str:
    """递归把 OMML 数学节点转为 LaTeX 字符串。

    python-docx 的 .text 忽略 OMML（m:oMath）导致 Word 公式整体丢失。
    这里用 lxml 遍历 m: 节点，覆盖常见结构（分式/上下标/定界符/根式/
    上横线/向量箭头/求和积分等），把公式还原为 KaTeX 可渲染的 LaTeX。
    """
    name = _qn(node.tag)
    children = list(node)
    sub = node.find(f"{{{_M_NS}}}sub")
    sup = node.find(f"{{{_M_NS}}}sup")
    base = node.find(f"{{{_M_NS}}}e")

    if name == "t":
        return node.text or ""
    if name == "r":  # 公式 run
        return "".join(t.text or "" for t in node.findall(f"{{{_M_NS}}}t"))
    if name in ("e", "num", "den", "fName", "nary"):
        pass  # 交由下层分发/通用拼接
    if name == "f":  # 分式
        num = node.find(f"{{{_M_NS}}}num")
        den = node.find(f"{{{_M_NS}}}den")
        n = _omml_to_latex(num) if num is not None else " "
        d = _omml_to_latex(den) if den is not None else " "
        return f"\\frac{{{n}}}{{{d}}}"
    if name == "sSup":
        s = _omml_to_latex(sup) if sup is not None and list(sup) else ""
        b = _omml_to_latex(base) if base is not None else ""
        return f"{b}^{{{s}}}" if s else b
    if name == "sSub":
        s = _omml_to_latex(sub) if sub is not None and list(sub) else ""
        b = _omml_to_latex(base) if base is not None else ""
        return f"{b}_{{{s}}}" if s else b
    if name == "sSubSup":
        sb = _omml_to_latex(sub) if sub is not None and list(sub) else ""
        sp = _omml_to_latex(sup) if sup is not None and list(sup) else ""
        b = _omml_to_latex(base) if base is not None else ""
        return f"{b}_{{{sb}}}^{{{sp}}}" if (sb or sp) else b
    if name == "d":  # 带定界符（括号）
        content = _omml_to_latex(base) if base is not None else ""
        beg, end = "(", ")"
        dpr = node.find(f"{{{_M_NS}}}dPr")
        if dpr is not None:
            b = dpr.find(f"{{{_M_NS}}}begChr")
            en = dpr.find(f"{{{_M_NS}}}endChr")
            if b is not None and b.get(f"{{{_W_NS}}}val"):
                beg = _MATH_DELIM.get(b.get(f"{{{_W_NS}}}val"), b.get(f"{{{_W_NS}}}val"))
            if en is not None and en.get(f"{{{_W_NS}}}val"):
                end = _MATH_DELIM.get(en.get(f"{{{_W_NS}}}val"), en.get(f"{{{_W_NS}}}val"))
        return f"\\left{beg}{content}\\right{end}"
    if name == "rad":  # 根式
        content = _omml_to_latex(base) if base is not None else ""
        deg = node.find(f"{{{_M_NS}}}deg")
        if deg is not None and list(deg):
            return f"\\sqrt[{_omml_to_latex(deg)}]{{{content}}}"
        return f"\\sqrt{{{content}}}"
    if name == "bar":  # 上横线（均值/约等）
        return f"\\overline{{{_omml_to_latex(base)}}}" if base is not None else ""
    if name == "acc":  # 上标注符（向量箭头等）
        content = _omml_to_latex(base) if base is not None else ""
        chr_el = node.find(f"{{{_M_NS}}}accPr/{{{_M_NS}}}chr")
        c = chr_el.get(f"{{{_W_NS}}}val") if chr_el is not None else None
        if c in ("→", "⟶", "↦", "⟹"):
            return f"\\vec{{{content}}}"
        if c not in (None, "̂", "~"):
            return f"\\overset{{{c}}}{{{content}}}"
        return content
    if name == "nary":  # 求和 / 积分 / 连乘
        content = _omml_to_latex(base) if base is not None else ""
        npr = node.find(f"{{{_M_NS}}}naryPr")
        chr_el = npr.find(f"{{{_M_NS}}}chr") if npr is not None else None
        c = chr_el.get(f"{{{_W_NS}}}val") if chr_el is not None else "∫"
        op = {
            "∫": "int", "∮": "oint", "∑": "sum", "∏": "prod",
            "⋃": "bigcup", "⋂": "bigcap", "⊕": "bigoplus", "⋀": "bigwedge",
        }.get(c, "int")
        sb = _omml_to_latex(sub) if sub is not None and list(sub) else ""
        sp = _omml_to_latex(sup) if sup is not None and list(sup) else ""
        s = f"\\{op}"
        if sb:
            s += f"_{{{sb}}}"
        if sp:
            s += f"^{{{sp}}}"
        return f"{s} {content}"
    if name == "func":  # 函数应用（如正余弦）
        fn = node.find(f"{{{_M_NS}}}fName")
        fname = _omml_to_latex(fn) if fn is not None else ""
        body = _omml_to_latex(base) if base is not None else ""
        return f"{fname}{body}"
    # 兜底：非结构节点（mPr/naryPr/dPr/矩阵等）仅透传子节点
    return "".join(_omml_to_latex(c) for c in children)


_MATH_DELIM = {
    "‖": "\\|", "⟨": "\\langle", "⟩": "\\rangle", "{": "\\{", "}": "\\}",
    "⌊": "\\lfloor", "⌋": "\\rfloor", "⌈": "\\lceil", "⌉": "\\rceil",
}


def _docx_element_text(elem) -> str:
    """遍历 w:p 或 w:tc 的 XML 子节点，提取普通文本 + 公式(LaTeX)。

    纯文本取 w:r/w:t；OMML 公式取 _omml_to_latex 并包裹为内联/块级
    LaTeX 定界符，使 Markdown/KaTeX 能渲染。
    """
    parts: list[str] = []
    for child in elem:
        ns = child.tag.split("}", 1)[0].lstrip("{")
        name = _qn(child.tag)
        if ns == _M_NS:
            latex = _omml_to_latex(child)
            if not latex:
                continue
            if name == "oMathPara":
                parts.append(f"\\[{latex}\\]")
            else:
                parts.append(f"\\({latex}\\)")
        elif ns == _W_NS and name == "r":
            txt = "".join(t.text or "" for t in child.findall(f"{{{_W_NS}}}t"))
            if txt:
                parts.append(txt)
        elif name in ("hyperlink", "ins", "del", "smartTag"):
            nested = _docx_element_text(child)
            if nested:
                parts.append(nested)
        # 其它（pPr/bookmarkStart/proofErr/idmap 等）忽略
    return "".join(parts)


def _extract_docx(file_path: Path) -> str:
    """lxml 遍历 DOCX 正文 XML 提取文本；OMML 公式转 LaTeX（保留公式）。

    相比 python-docx 的 para.text（丢弃公式），此实现按 w:p / w:tbl 顺序
    输出段落与表格文本，并让 Word 公式进入可检索/可渲染的文本流。
    """
    import docx  # type: ignore[import-not-found]

    doc = docx.Document(str(file_path))
    parts: list[str] = []
    body = doc.element.body

    def _cell_text(tc) -> str:
        lines: list[str] = []
        for p in tc.iterchildren():
            if _qn(p.tag) == "p":
                txt = _docx_element_text(p).strip()
                if txt:
                    lines.append(txt)
        return "<br>".join(lines)

    for block in body.iterchildren():
        name = _qn(block.tag)
        if name == "p":
            txt = _docx_element_text(block).strip()
            if txt:
                parts.append(txt)
        elif name == "tbl":  # 表格：每行 | 分隔拼成文本
            for row in block.iterchildren():
                if _qn(row.tag) != "tr":
                    continue
                cells = [
                    _cell_text(tc).strip()
                    for tc in row.iterchildren()
                    if _qn(tc.tag) == "tc"
                ]
                if cells and any(cells):
                    parts.append(" | ".join(cells))
    return "\n".join(parts).strip()


def parse_material_text(file_path: Path, file_type: str) -> tuple[str | None, str | None]:
    """根据 MIME 类型提取纯文本。

    返回 (content, error)。content 为 None 表示解析失败。
    JPG/PNG 无文本提取，返回空字符串（成功）。
    """
    try:
        if file_type == "application/pdf":
            text = _extract_pdf(file_path)
            return text or "", None
        if file_type == _EXT_TO_MIME["pptx"]:
            text = _extract_pptx(file_path)
            return text or "", None
        if file_type == _EXT_TO_MIME["docx"]:
            text = _extract_docx(file_path)
            return text or "", None
        if file_type in ("image/jpeg", "image/png"):
            # 图片无文本提取，后续可接入 OCR
            return "", None
        return None, f"不支持的 MIME 类型：{file_type}"
    except Exception as exc:
        return None, f"解析失败：{type(exc).__name__}: {exc}"


def run_indexing(db: Session, material_id: int) -> None:
    """异步文本解析任务（由 BackgroundTasks 调用）。

    解析成功 → 分块 + 逐块向量化写入 MaterialChunk → is_indexed=true
    任一步失败 → is_indexed=false + 写入 MaterialContent.parse_error
    """
    material = db.get(Material, material_id)
    if material is None:
        return

    file_path = resolve_abs_path(material.file_path)
    content, error = parse_material_text(file_path, material.file_type)

    if error is not None:
        _persist_index_result(db, material_id, content=None, error=error)
        _set_indexed(db, material, False)
        return

    # 分块 + 向量化；任一失败则保持未索引
    try:
        from chunk_service import chunk_text
        from embedding_service import embed_text
        from rag_search_service import serialize_vector

        chunks = chunk_text(content or "")
        # 清空旧分块（重索引用）
        db.query(MaterialChunk).filter(MaterialChunk.material_id == material_id).delete()
        # 并发删除竞态防护：解析期间材料可能已被删除，此时不做任何写入，
        # 避免为已删除材料重建孤立的 content/chunk 行
        if db.get(Material, material_id) is None:
            db.rollback()
            return

        indexed = True
        for idx, chunk in enumerate(chunks, start=1):
            vec = embed_text(chunk)
            db.add(
                MaterialChunk(
                    material_id=material_id,
                    class_id=material.class_id,
                    chunk_index=idx,
                    content=chunk,
                    embedding=serialize_vector(vec),
                )
            )
        db.commit()

        if not chunks:
            # 无文本可索引（如纯图片）→ 视为成功但无可检索内容，is_indexed 仍为 true
            # （与旧行为一致：图片解析为空串视为成功）
            indexed = True

        _persist_index_result(db, material_id, content=content, error=None)
        _set_indexed(db, material, indexed)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        _persist_index_result(db, material_id, content=None, error=f"分块/向量化失败：{type(exc).__name__}: {exc}")
        _set_indexed(db, material, False)


def _persist_index_result(
    db: Session, material_id: int, *, content: str | None, error: str | None
) -> None:
    """写入 MaterialContent 解析结果（覆盖已有记录）。"""
    from datetime import datetime, timezone

    # 并发删除竞态防护：材料已被删除则不落任何 content 行
    if db.get(Material, material_id) is None:
        return

    existing = (
        db.query(MaterialContent)
        .filter_by(material_id=material_id)
        .one_or_none()
    )
    if existing is None:
        existing = MaterialContent(material_id=material_id)
        db.add(existing)

    existing.content = content
    existing.parse_error = error
    existing.parsed_at = datetime.now(timezone.utc)
    db.commit()


def _set_indexed(db: Session, material: Material, value: bool) -> None:
    material.is_indexed = value
    db.commit()


# ---------------------------------------------------------------------------
# AI 检索上下文（design.md 决策：仅 is_indexed=true 的材料被检索）
# ---------------------------------------------------------------------------


def get_indexed_contexts(db: Session, class_id: int, limit: int = 10) -> list[str]:
    """检索指定班级已索引材料的纯文本（供 AI 解题助手作为上下文）。

    仅返回 is_indexed=true 的材料文本，is_indexed=false 不被检索。
    """
    rows = (
        db.query(MaterialContent.content)
        .join(Material, Material.id == MaterialContent.material_id)
        .filter(
            Material.class_id == class_id,
            Material.is_indexed.is_(True),
            MaterialContent.content.isnot(None),
        )
        .order_by(Material.created_at.desc())
        .limit(limit)
        .all()
    )
    return [r[0] for r in rows if r[0]]
