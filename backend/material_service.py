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


def _extract_docx(file_path: Path) -> str:
    """python-docx 提取 DOCX 纯文本（段落 + 表格）。"""
    import docx  # type: ignore[import-not-found]

    parts: list[str] = []
    doc = docx.Document(str(file_path))
    for para in doc.paragraphs:
        txt = para.text.strip()
        if txt:
            parts.append(txt)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                txt = cell.text.strip()
                if txt:
                    parts.append(txt)
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
