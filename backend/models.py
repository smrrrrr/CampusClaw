"""SQLAlchemy ORM 模型。

- User：统一存储教师 / 学生两种角色（无独立家长角色）
- VerificationCode：短信验证码与防刷
- LoginAttempt：密码登录失败锁定
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, enum.Enum):
    teacher = "teacher"
    student = "student"


class CodeStatus(str, enum.Enum):
    pending = "pending"
    used = "used"
    invalidated = "invalidated"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role: Mapped[Role] = mapped_column(Enum(Role), nullable=False)
    # 学号 / 工号
    identifier: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # 手机号（非唯一：同一手机号可绑定多个学生）
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # 学生必填，教师为空
    class_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("classes.id"), nullable=True
    )
    # 教师任教班级 ID 列表（JSON 数组，如 "[101, 102]"），仅教师使用
    teaching_classes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("role", "identifier", name="uq_user_role_identifier"),
        Index("ix_user_phone", "phone"),
    )


class Class(Base):
    """班级表（账号预置时引用）。"""

    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class VerificationCode(Base):
    __tablename__ = "verification_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    code: Mapped[str] = mapped_column(String(6), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[CodeStatus] = mapped_column(
        Enum(CodeStatus), default=CodeStatus.pending, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (Index("ix_verification_code_phone", "phone"),)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 学号 / 工号
    identifier: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lock_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditLog(Base):
    """越权行为审计日志。"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    request_path: Mapped[str] = mapped_column(String(256), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (Index("ix_audit_log_created_at", "created_at"),)


class AIQuestionLog(Base):
    """AI 提问记录（用于每日次数限制计数 + 班级数据隔离）。"""

    __tablename__ = "ai_question_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    # 班级数据隔离：记录提问时所在班级，教师查看 AI 历史时按 class_id 过滤
    class_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("classes.id"), nullable=False
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (
        Index("ix_ai_question_student_created", "student_id", "created_at"),
        Index("ix_ai_question_class_id", "class_id"),
    )


# ---------------------------------------------------------------------------
# 班级数据隔离骨架表（class_id 字段规范，业务字段由后续规约扩展）
# ---------------------------------------------------------------------------


class Material(Base):
    """班级资料表：教师上传的学习材料元数据（文件本体存储在挂载卷，不存 SQLite）。"""

    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    class_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("classes.id"), nullable=False
    )
    uploader_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    # 原文件名（展示用）
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # 存储相对路径（如 101/1620000000_lesson1.pdf）
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    # MIME 类型（如 application/pdf）
    file_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 标签 JSON 数组（如 ["数学", "代数"]）
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 是否已解析为纯文本并纳入 AI 检索
    is_indexed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (
        Index("ix_material_class_id", "class_id"),
        # 联合索引：加速"查询某班已索引材料"场景
        Index("ix_material_class_indexed", "class_id", "is_indexed"),
    )


class MaterialContent(Base):
    """材料解析后的纯文本内容（供 AI 解题助手检索作为上下文）。"""

    __tablename__ = "material_contents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    material_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("materials.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    parsed_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (Index("ix_material_content_material_id", "material_id"),)


class MaterialChunk(Base):
    """材料分块与向量（RAG 检索单元）。

    上传材料解析为纯文本后，按 chunk_service 切分为固定长度 + 重叠的文本块，
    每块计算 embedding 向量（BLOB）持久化于此表，供 rag_search_service 按班级检索。
    """

    __tablename__ = "material_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    material_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("materials.id", ondelete="CASCADE"), nullable=False
    )
    # 冗余存储：支持按班隔离检索，避免跨表 join（design.md 决策 2）
    class_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("classes.id"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 稠密向量的字节序列（float32，dtype 转换后持久化）
    embedding: Mapped[bytes] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (
        Index("ix_material_chunk_material_id", "material_id"),
        # 加速"查询某班已索引材料分块"的检索过滤
        Index("ix_material_chunk_class_material", "class_id", "material_id"),
    )


class Homework(Base):
    """作业布置表（骨架）。业务字段由后续作业规约扩展。"""

    __tablename__ = "homeworks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    class_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("classes.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (Index("ix_homework_class_id", "class_id"),)


class HomeworkSubmission(Base):
    """作业提交记录表（骨架）。业务字段由后续作业规约扩展。"""

    __tablename__ = "homework_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    class_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("classes.id"), nullable=False
    )
    student_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (Index("ix_homework_submission_class_id", "class_id"),)


class MistakeNote(Base):
    """错题本表（骨架）。业务字段由后续错题本规约扩展。"""

    __tablename__ = "mistake_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    class_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("classes.id"), nullable=False
    )
    student_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (Index("ix_mistake_note_class_id", "class_id"),)
