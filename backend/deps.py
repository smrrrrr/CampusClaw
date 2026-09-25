"""FastAPI 依赖：JWT 校验、当前用户、强制改密拦截。"""

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from database import get_db
from models import User
from security import (
    JWTError,
    TOKEN_TYPE_ACCESS,
    decode_token,
)

_bearer = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    user_id: int
    role: str
    class_id: int | None
    must_change_password: bool
    teaching_classes: list[int] | None = None


_credential_exception = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="认证失效，请重新登录",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """解析 Authorization: Bearer <access_token>，校验有效性并返回当前用户上下文。"""
    if credentials is None or not credentials.credentials:
        raise _credential_exception

    try:
        payload = decode_token(credentials.credentials)
    except JWTError:
        raise _credential_exception

    if payload.get("type") != TOKEN_TYPE_ACCESS:
        raise _credential_exception

    user_id = payload.get("user_id")
    if user_id is None:
        raise _credential_exception

    # 用户必须仍存在
    user = db.get(User, user_id)
    if user is None:
        raise _credential_exception

    return CurrentUser(
        user_id=user_id,
        role=payload.get("role"),
        class_id=payload.get("class_id"),
        must_change_password=bool(payload.get("must_change_password", False)),
        teaching_classes=payload.get("teaching_classes"),
    )


def require_password_changed(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """must_change_password=true 时仅允许改密接口调用；业务接口注入此依赖即被拦截。"""
    if current.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="请先修改初始密码",
        )
    return current


def get_current_teacher(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """教师专用接口拦截：仅 role=teacher 可通过。"""
    if current.role != "teacher":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅教师可执行该操作",
        )
    return current


def get_current_student(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """学生专用接口拦截：仅 role=student 可通过。"""
    if current.role != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅学生可执行该操作",
        )
    return current
