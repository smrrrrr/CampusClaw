"""材料相关路由：教师上传、列表查询（班级隔离）、下载、在线预览。

端点分布：
    POST /api/teacher/upload-material  — 教师上传（Depends(get_current_teacher)）
    GET  /api/materials                 — 列表（学生/教师按 class_id 隔离）
    GET  /api/materials/{id}/download    — 下载（class_id 鉴权）
    GET  /api/materials/{id}/preview     — 在线预览（class_id 鉴权，inline）
"""

import json
from datetime import datetime
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from deps import CurrentUser, get_current_teacher, get_current_user
from material_service import (
    MAX_FILE_SIZE,
    build_relative_path,
    delete_physical_file,
    get_indexed_contexts,
    resolve_abs_path,
    run_indexing,
    validate_upload_file,
    write_physical_file,
)
from models import Class, Material, MaterialContent
from services import require_student_class_id, require_teacher_classes, write_audit_log

router = APIRouter(tags=["materials"])


# ---------------------------------------------------------------------------
# Pydantic 模型
# ---------------------------------------------------------------------------


class UploadResponse(BaseModel):
    id: int
    filename: str
    file_type: str
    file_size: int
    class_id: int
    is_indexed: bool
    created_at: datetime
    message: str


class MaterialItem(BaseModel):
    id: int
    class_id: int
    uploader_id: int
    filename: str
    file_type: str
    file_size: int
    description: str | None = None
    tags: list[str] = []
    is_indexed: bool
    created_at: datetime
    class_name: str | None = None


class MaterialListResponse(BaseModel):
    items: list[MaterialItem]
    total: int


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _parse_tags(raw: str) -> str:
    """逗号分隔字符串 → JSON 数组字符串（存 DB）。"""
    items = [t.strip() for t in raw.split(",") if t.strip()] if raw else []
    return json.dumps(items, ensure_ascii=False)


def _load_tags(raw: str | None) -> list[str]:
    """JSON 数组字符串 → list。"""
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


def _check_material_access(material: Material | None, current: CurrentUser) -> None:
    """校验当前用户是否有权访问该材料（class_id 隔离）。

    学生：material.class_id == current.class_id
    教师：material.class_id IN current.teaching_classes
    不匹配 → 403（由全局中间件记录审计日志）
    """
    if material is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="材料不存在")

    if current.role == "student":
        if current.class_id is None or material.class_id != current.class_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="无权访问非本班材料",
            )
    elif current.role == "teacher":
        tc = current.teaching_classes or []
        if material.class_id not in tc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="无权访问非任教班级材料",
            )


# ---------------------------------------------------------------------------
# 教师上传
# ---------------------------------------------------------------------------


@router.post("/api/teacher/upload-material", response_model=UploadResponse)
async def upload_material(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    class_id: int = Form(...),
    description: str = Form(""),
    tags: str = Form(""),
    current: CurrentUser = Depends(get_current_teacher),
    db: Session = Depends(get_db),
):
    """教师上传学习材料。

    校验链（design.md 决策 4/6）：
        1. class_id 在 teaching_classes 范围内（403）
        2. 文件大小 ≤ 50MB（400）
        3. magic number + MIME 校验，不信任扩展名（400）
        4. 写入物理文件 → 写入 DB → 失败回滚删文件
        5. 异步文本解析（is_indexed 标记）
    """
    # 1. 班级选择校验：class_id 必须在教师 teaching_classes 范围内
    tc = require_teacher_classes(current.teaching_classes)
    if class_id not in tc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权向非任教班级上传材料",
        )

    # 2. 读取文件内容
    file_bytes = await file.read()
    original_filename = file.filename or "unnamed"

    # 3. 文件校验：大小 + magic number + MIME
    try:
        mime_type, ext = validate_upload_file(file_bytes, original_filename)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    # 4. 生成存储路径（按 class_id 分子目录 + 时间戳前缀）
    relative_path = build_relative_path(class_id, original_filename)

    # 5. 写入物理文件
    try:
        write_physical_file(file_bytes, relative_path)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="文件写入磁盘失败",
        )

    # 6. 写入 Material 表（失败回滚删物理文件）
    material = Material(
        class_id=class_id,
        uploader_id=current.user_id,
        filename=original_filename,
        file_path=relative_path,
        file_type=mime_type,
        file_size=len(file_bytes),
        description=description.strip() or None,
        tags=_parse_tags(tags),
        is_indexed=False,
    )
    db.add(material)
    try:
        db.commit()
        db.refresh(material)
    except Exception:
        db.rollback()
        # 回滚：删除已写入的物理文件
        delete_physical_file(relative_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="材料记录写入数据库失败，已清理物理文件",
        )

    # 7. 异步文本解析（is_indexed 标记更新）
    background.add_task(_run_indexing_async, material.id)

    return UploadResponse(
        id=material.id,
        filename=material.filename,
        file_type=material.file_type,
        file_size=material.file_size,
        class_id=material.class_id,
        is_indexed=material.is_indexed,
        created_at=material.created_at,
        message="上传成功，正在异步解析为知识库素材",
    )


def _run_indexing_async(material_id: int) -> None:
    """BackgroundTasks 调用的异步解析入口（独立 DB session）。"""
    db = SessionLocal()
    try:
        run_indexing(db, material_id)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 材料列表查询（班级隔离）
# ---------------------------------------------------------------------------


@router.get("/api/materials", response_model=MaterialListResponse)
def list_materials(
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    class_id: int | None = Query(None),
    search: str | None = Query(None, description="按描述/标签模糊搜索"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """查询材料列表（数据隔离）。

    学生：WHERE class_id = :current_class_id（不信任请求中的 class_id）
    教师：WHERE class_id IN (teaching_classes)
    支持按 description/tags 模糊搜索、按 created_at DESC 排序、分页。
    """
    # 构建隔离条件
    if current.role == "student":
        # 学生：以 JWT 中的 class_id 为准，不信任请求参数
        student_class_id = require_student_class_id(current.class_id)
        target_classes = [student_class_id]
        # 学生传入 class_id 参数即视为篡改尝试 → 403
        if class_id is not None and class_id != student_class_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="无权查看非本班材料",
            )
    elif current.role == "teacher":
        tc = require_teacher_classes(current.teaching_classes)
        # 教师：class_id 参数必须在 teaching_classes 中
        if class_id is not None and class_id not in tc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="无权查看非任教班级材料",
            )
        target_classes = [class_id] if class_id is not None else tc
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问材料",
        )

    q = (
        db.query(Material, Class.name)
        .outerjoin(Class, Material.class_id == Class.id)
        .filter(Material.class_id.in_(target_classes))
    )

    # 模糊搜索：description 或 tags
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(
            (Material.description.like(like)) | (Material.tags.like(like))
        )

    total = q.count()
    rows = (
        q.order_by(Material.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return MaterialListResponse(
        items=[
            MaterialItem(
                id=m.id,
                class_id=m.class_id,
                uploader_id=m.uploader_id,
                filename=m.filename,
                file_type=m.file_type,
                file_size=m.file_size,
                description=m.description,
                tags=_load_tags(m.tags),
                is_indexed=m.is_indexed,
                created_at=m.created_at,
                class_name=cname,
            )
            for m, cname in rows
        ],
        total=total,
    )


# ---------------------------------------------------------------------------
# 下载与预览
# ---------------------------------------------------------------------------


def _get_material_or_404(db: Session, material_id: int) -> Material:
    m = db.get(Material, material_id)
    if m is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="材料不存在")
    return m


@router.get("/api/materials/{material_id}/download")
def download_material(
    material_id: int,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """下载材料（attachment）。校验 class_id 匹配，不匹配 403 + 审计日志。"""
    material = _get_material_or_404(db, material_id)
    _check_material_access(material, current)

    abs_path = resolve_abs_path(material.file_path)
    if not abs_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件不存在或已被删除",
        )

    return FileResponse(
        path=str(abs_path),
        media_type=material.file_type,
        filename=material.filename,
        content_disposition_type="attachment",
    )


@router.get("/api/materials/{material_id}/preview")
def preview_material(
    material_id: int,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """在线预览材料（inline）。校验 class_id 匹配，不匹配 403 + 审计日志。"""
    material = _get_material_or_404(db, material_id)
    _check_material_access(material, current)

    abs_path = resolve_abs_path(material.file_path)
    if not abs_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="文件不存在或已被删除",
        )

    return FileResponse(
        path=str(abs_path),
        media_type=material.file_type,
        filename=material.filename,
        content_disposition_type="inline",
    )


# ---------------------------------------------------------------------------
# 教师手动重建索引（可选辅助端点）
# ---------------------------------------------------------------------------


@router.post("/api/teacher/materials/{material_id}/reindex")
def reindex_material(
    material_id: int,
    current: CurrentUser = Depends(get_current_teacher),
    db: Session = Depends(get_db),
):
    """手动重新解析材料文本（教师补救解析失败的材料）。"""
    material = _get_material_or_404(db, material_id)
    tc = current.teaching_classes or []
    if material.class_id not in tc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权操作非任教班级材料",
        )

    run_indexing(db, material_id)
    material = db.get(Material, material_id)
    return {
        "id": material_id,
        "is_indexed": material.is_indexed if material else False,
        "message": "重新解析完成" if material and material.is_indexed else "解析失败，请检查文件",
    }
