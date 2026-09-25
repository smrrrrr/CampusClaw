"""教师相关路由：CSV 批量导入学生、重置学生密码、审计日志查询、班级/学生列表。"""

import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from deps import CurrentUser, get_current_teacher
from models import AuditLog, Class, Role, User
from security import generate_initial_password, hash_password
from services import require_teacher_classes, write_audit_log

router = APIRouter(prefix="/api/teacher", tags=["teacher"])

REQUIRED_COLUMN = "学号"
NAME_COLUMNS = ("学生姓名", "姓名")
PHONE_COLUMN = "手机号"
CLASS_COLUMN = "班级"


class ImportResult(BaseModel):
    total_rows: int
    created: int
    updated: int
    message: str


class ResetPasswordRequest(BaseModel):
    student_id: int


class ResetPasswordResponse(BaseModel):
    message: str
    initial_password: str


@router.post("/import-students", response_model=ImportResult)
async def import_students(
    file: UploadFile = File(...),
    current: CurrentUser = Depends(get_current_teacher),
    db: Session = Depends(get_db),
):
    # Excel 导出的 CSV 常带 BOM，使用 utf-8-sig 兼容
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件编码不支持，请使用 UTF-8 编码的 CSV 文件",
        )

    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    if REQUIRED_COLUMN not in headers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='CSV 格式错误：缺少必需的"学号"列',
        )

    name_column = next((c for c in NAME_COLUMNS if c in headers), None)
    created = 0
    updated = 0
    total_rows = 0

    # 全部操作在单事务中执行，任一行失败则整体回滚
    try:
        for line_no, row in enumerate(reader, start=2):  # 表头为第 1 行
            identifier = (row.get(REQUIRED_COLUMN) or "").strip()
            if not identifier:
                raise ValueError(f"第 {line_no} 行：学号不能为空")

            name = (row.get(name_column) or "").strip() if name_column else None
            phone = (row.get(PHONE_COLUMN) or "").strip() if PHONE_COLUMN in headers else ""
            class_name = (
                (row.get(CLASS_COLUMN) or "").strip() if CLASS_COLUMN in headers else ""
            )

            class_id = None
            if class_name:
                clazz = db.query(Class).filter_by(name=class_name).one_or_none()
                if clazz is None:
                    clazz = Class(name=class_name)
                    db.add(clazz)
                    db.flush()
                class_id = clazz.id

            student = (
                db.query(User)
                .filter_by(role=Role.student, identifier=identifier)
                .one_or_none()
            )
            if student is None:
                student = User(
                    role=Role.student,
                    identifier=identifier,
                    password_hash=hash_password(generate_initial_password(identifier)),
                    phone=phone or None,
                    name=name or None,
                    class_id=class_id,
                    must_change_password=True,
                )
                db.add(student)
                created += 1
            else:
                # 复用已有账号：更新手机号（含绑定）、姓名、班级
                if phone:
                    student.phone = phone
                if name:
                    student.name = name
                if class_id is not None:
                    student.class_id = class_id
                updated += 1

            total_rows += 1

        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="导入失败，所有数据已回滚",
        )

    return ImportResult(
        total_rows=total_rows,
        created=created,
        updated=updated,
        message=f"导入完成：新建 {created} 个账号，更新 {updated} 个账号",
    )


# ---------------------------------------------------------------------------
# 班级与学生列表（数据隔离：仅返回 teaching_classes 范围内数据）
# ---------------------------------------------------------------------------


class ClassItem(BaseModel):
    id: int
    name: str


class StudentItem(BaseModel):
    id: int
    identifier: str
    name: str | None = None
    class_id: int | None = None
    class_name: str | None = None
    phone: str | None = None


class StudentListResponse(BaseModel):
    items: list[StudentItem]
    total: int


@router.get("/classes", response_model=list[ClassItem])
def list_classes(
    current: CurrentUser = Depends(get_current_teacher),
    db: Session = Depends(get_db),
):
    """返回教师任教班级列表（仅 teaching_classes 范围内）。

    无班级边界处理：teaching_classes 为空时返回 403。
    """
    tc = require_teacher_classes(current.teaching_classes)
    rows = db.query(Class).filter(Class.id.in_(tc)).all()
    return [ClassItem(id=c.id, name=c.name) for c in rows]


@router.get("/students", response_model=StudentListResponse)
def list_students(
    current: CurrentUser = Depends(get_current_teacher),
    db: Session = Depends(get_db),
    class_id: int | None = Query(None),
):
    """返回教师任教班级的学生列表（数据隔离：WHERE class_id IN teaching_classes）。

    无班级边界处理：teaching_classes 为空时返回 403。
    跨班访问拦截：请求参数 class_id 不在 teaching_classes 中时返回 403。
    """
    tc = require_teacher_classes(current.teaching_classes)
    # 不信任请求体中的 class_id：即使传入也必须 IN teaching_classes
    if class_id is not None and class_id not in tc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权查看非任教班级的学生",
        )
    target_classes = [class_id] if class_id is not None else tc

    rows = (
        db.query(User, Class.name)
        .outerjoin(Class, User.class_id == Class.id)
        .filter(
            User.role == Role.student,
            User.class_id.in_(target_classes),
        )
        .all()
    )
    return StudentListResponse(
        items=[
            StudentItem(
                id=u.id,
                identifier=u.identifier,
                name=u.name,
                class_id=u.class_id,
                class_name=cname,
                phone=u.phone,
            )
            for u, cname in rows
        ],
        total=len(rows),
    )


@router.post("/reset-password", response_model=ResetPasswordResponse)
def reset_password(
    body: ResetPasswordRequest,
    current: CurrentUser = Depends(get_current_teacher),
    db: Session = Depends(get_db),
):
    """将学生密码重置为初始密码，并重新置 must_change_password=True。

    校验目标学生所在班级是否在教师 teaching_classes 范围内。
    """
    student = db.get(User, body.student_id)
    if student is None or student.role != Role.student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="学生账号不存在",
        )

    # 数据隔离：校验学生所在班级是否在教师任教范围内
    tc = current.teaching_classes or []
    if student.class_id not in tc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权操作非任教班级的学生",
        )

    initial_password = generate_initial_password(student.identifier)
    student.password_hash = hash_password(initial_password)
    student.must_change_password = True
    db.commit()

    return ResetPasswordResponse(
        message="密码已重置为初始密码，学生首次登录需修改密码",
        initial_password=initial_password,
    )


# ---------------------------------------------------------------------------
# 审计日志查询
# ---------------------------------------------------------------------------


class AuditLogItem(BaseModel):
    id: int
    user_id: int | None = None
    role: str | None = None
    request_path: str
    method: str
    status_code: int
    ip_address: str | None = None
    created_at: datetime


class AuditLogListResponse(BaseModel):
    items: list[AuditLogItem]
    total: int


@router.get("/audit-logs", response_model=AuditLogListResponse)
def query_audit_logs(
    current: CurrentUser = Depends(get_current_teacher),
    db: Session = Depends(get_db),
    user_id: int | None = Query(None),
    request_path: str | None = Query(None),
    role: str | None = Query(None),
    status_code: int | None = Query(None),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """查询审计日志（按 user_id / request_path / role / status_code / 时间范围筛选）。"""
    q = db.query(AuditLog)
    if user_id is not None:
        q = q.filter(AuditLog.user_id == user_id)
    if request_path is not None:
        q = q.filter(AuditLog.request_path.contains(request_path))
    if role is not None:
        q = q.filter(AuditLog.role == role)
    if status_code is not None:
        q = q.filter(AuditLog.status_code == status_code)
    if start is not None:
        q = q.filter(AuditLog.created_at >= start)
    if end is not None:
        q = q.filter(AuditLog.created_at <= end)

    total = q.count()
    rows = q.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()
    return AuditLogListResponse(
        items=[
            AuditLogItem(
                id=r.id,
                user_id=r.user_id,
                role=r.role,
                request_path=r.request_path,
                method=r.method,
                status_code=r.status_code,
                ip_address=r.ip_address,
                created_at=r.created_at,
            )
            for r in rows
        ],
        total=total,
    )
