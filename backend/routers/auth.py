"""认证相关路由：密码登录、Token 刷新、改密、登出。

验证码登录（send-code / verify-code / select-student / switch-student）
见本文件后半部分。
"""

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from deps import CurrentUser, get_current_user
from models import Class, CodeStatus, Role, User
from schemas import (
    ChangePasswordRequest,
    LoginRequest,
    MessageResponse,
    RefreshResponse,
    SelectStudentRequest,
    SendCodeRequest,
    SendCodeResponse,
    StudentBrief,
    TokenResponse,
    UserInfo,
    VerifyCodeRequest,
    VerifyCodeResponse,
)
from security import (
    JWTError,
    REFRESH_COOKIE_NAME,
    TOKEN_TYPE_REFRESH,
    TOKEN_TYPE_TEMP,
    create_access_token,
    create_refresh_token,
    create_temp_token,
    decode_token,
    hash_password,
    validate_password_policy,
    verify_password,
)
from services import (
    _as_aware,
    _utcnow,
    check_send_allowed,
    create_verification_code,
    get_latest_pending_code,
    is_locked,
    register_code_failure,
    register_failure,
    reset_failures,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

_REFRESH_COOKIE_MAX_AGE = settings.refresh_token_expire_days * 24 * 60 * 60


def _user_info(user: User) -> UserInfo:
    return UserInfo(
        id=user.id,
        role=user.role.value,
        name=user.name,
        class_id=user.class_id,
        must_change_password=user.must_change_password,
        teaching_classes=_parse_teaching_classes(user.teaching_classes),
    )


def _parse_teaching_classes(raw: str | None) -> list[int] | None:
    """从 User.teaching_classes JSON 字段解析出整数列表。"""
    if not raw:
        return None
    try:
        import json
        result = json.loads(raw)
        return result if isinstance(result, list) else None
    except (ValueError, TypeError):
        return None


def _issue_tokens(response: Response, user: User) -> str:
    """签发 Access Token（返回）+ Refresh Token（写入 HttpOnly Cookie）。"""
    tc = _parse_teaching_classes(user.teaching_classes)
    access_token = create_access_token(
        user_id=user.id,
        role=user.role.value,
        class_id=user.class_id,
        must_change_password=user.must_change_password,
        teaching_classes=tc,
    )
    refresh_token = create_refresh_token(
        user_id=user.id,
        role=user.role.value,
        class_id=user.class_id,
        must_change_password=user.must_change_password,
        phone=user.phone,
        teaching_classes=tc,
    )
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=_REFRESH_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/api/auth",
    )
    return access_token


# ---------------------------------------------------------------------------
# 3.1-3.3 密码登录
# ---------------------------------------------------------------------------


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    identifier = body.identifier.strip()

    # 锁定期间即使密码正确也拒绝
    if is_locked(db, identifier):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="账号已锁定，请15分钟后重试",
        )

    # identifier 在 (role, identifier) 维度唯一；同号跨角色时逐个验密
    candidates = db.query(User).filter(User.identifier == identifier).all()
    matched: User | None = None
    for user in candidates:
        if verify_password(body.password, user.password_hash):
            matched = user
            break

    if matched is None:
        # 账号不存在与密码错误返回完全相同的提示，防止账号枚举
        register_failure(db, identifier)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账号或密码错误",
        )

    reset_failures(db, identifier)
    access_token = _issue_tokens(response, matched)
    return TokenResponse(
        access_token=access_token,
        must_change_password=matched.must_change_password,
        role=matched.role.value,
        user=_user_info(matched),
    )


# ---------------------------------------------------------------------------
# 3.4 刷新 Access Token
# ---------------------------------------------------------------------------


@router.post("/refresh", response_model=RefreshResponse)
def refresh_token(
    response: Response,
    db: Session = Depends(get_db),
    refresh_token_cookie: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
):
    if not refresh_token_cookie:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未提供刷新令牌")

    try:
        payload = decode_token(refresh_token_cookie)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="刷新令牌已失效，请重新登录")

    if payload.get("type") != TOKEN_TYPE_REFRESH:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌类型错误")

    # 以数据库当前状态重新签发，确保权限 / 改密标记及时生效
    user = db.get(User, payload.get("user_id"))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号不存在")

    access_token = create_access_token(
        user_id=user.id,
        role=user.role.value,
        class_id=user.class_id,
        must_change_password=user.must_change_password,
        teaching_classes=_parse_teaching_classes(user.teaching_classes),
    )
    # 滑动续期：同时更新 Refresh Cookie
    new_refresh = create_refresh_token(
        user_id=user.id,
        role=user.role.value,
        class_id=user.class_id,
        must_change_password=user.must_change_password,
        phone=user.phone,
        teaching_classes=_parse_teaching_classes(user.teaching_classes),
    )
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=new_refresh,
        max_age=_REFRESH_COOKIE_MAX_AGE,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/api/auth",
    )
    return RefreshResponse(
        access_token=access_token,
        must_change_password=user.must_change_password,
        role=user.role.value,
        teaching_classes=_parse_teaching_classes(user.teaching_classes),
    )


# ---------------------------------------------------------------------------
# 3.5 修改密码（改密端点不受 require_password_changed 限制）
# ---------------------------------------------------------------------------


@router.post("/change-password", response_model=TokenResponse)
def change_password(
    body: ChangePasswordRequest,
    response: Response,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.get(User, current.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号不存在")

    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="旧密码错误")

    valid, reason = validate_password_policy(body.new_password)
    if not valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=reason)

    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    db.commit()
    db.refresh(user)

    access_token = _issue_tokens(response, user)
    return TokenResponse(
        access_token=access_token,
        must_change_password=False,
        role=user.role.value,
        user=_user_info(user),
    )


# ---------------------------------------------------------------------------
# 3.6 登出（清除 HttpOnly Cookie；Access Token 由前端内存清除）
# ---------------------------------------------------------------------------


@router.post("/logout", response_model=MessageResponse)
def logout(
    response: Response,
    current: CurrentUser = Depends(get_current_user),
):
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path="/api/auth",
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
    )
    return MessageResponse(message="已登出")


# ---------------------------------------------------------------------------
# 验证码登录
# ---------------------------------------------------------------------------


def _students_bound_to_phone(db: Session, phone: str) -> list[tuple[User, str | None]]:
    """查询手机号绑定的所有学生账号（含班级名称）。"""
    rows = (
        db.query(User, Class.name)
        .outerjoin(Class, User.class_id == Class.id)
        .filter(User.role == Role.student, User.phone == phone)
        .all()
    )
    return [(u, class_name) for u, class_name in rows]


@router.post("/send-code", response_model=SendCodeResponse)
def send_code(body: SendCodeRequest, db: Session = Depends(get_db)):
    allowed, reason = check_send_allowed(db, body.phone)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=reason)

    code = create_verification_code(db, body.phone)

    # 生产环境调用短信服务发送；Mock 模式直接在响应中返回验证码
    if settings.sms_mock:
        return SendCodeResponse(message="验证码已发送", code=code)
    return SendCodeResponse(message="验证码已发送")


@router.post("/verify-code", response_model=VerifyCodeResponse)
def verify_code(body: VerifyCodeRequest, response: Response, db: Session = Depends(get_db)):
    record = get_latest_pending_code(db, body.phone)
    if record is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先获取验证码")

    if _as_aware(record.expires_at) <= _utcnow():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码已过期，请重新发送")

    if record.code != body.code:
        register_code_failure(db, record)
        db.refresh(record)
        if record.status == CodeStatus.invalidated:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="验证码错误次数过多，已作废，请重新发送",
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误")

    # 验证通过，标记已使用
    record.status = CodeStatus.used
    db.commit()

    students = _students_bound_to_phone(db, body.phone)
    if not students:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该手机号未绑定学生，请联系班主任绑定",
        )

    if len(students) == 1:
        # 单娃：直接签发正式 JWT
        student, _ = students[0]
        access_token = _issue_tokens(response, student)
        return VerifyCodeResponse(
            access_token=access_token,
            must_change_password=student.must_change_password,
            role=student.role.value,
            user=_user_info(student),
        )

    # 多娃：返回 Temp Token + 学生列表
    temp_token = create_temp_token(phone=body.phone)
    return VerifyCodeResponse(
        temp_token=temp_token,
        students=[
            StudentBrief(id=s.id, name=s.name, class_id=s.class_id, class_name=class_name)
            for s, class_name in students
        ],
    )


class SwitchStudentResponse(VerifyCodeResponse):
    message: str | None = None


@router.post("/switch-student", response_model=SwitchStudentResponse)
def switch_student(
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    refresh_token_cookie: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
):
    """已登录家长切换孩子：用 Refresh Token 中的 phone 重新查询学生列表并签发新 Temp Token。"""
    if not refresh_token_cookie:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="认证失效，请重新登录")

    try:
        payload = decode_token(refresh_token_cookie)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="认证失效，请重新登录")

    if payload.get("type") != TOKEN_TYPE_REFRESH:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="认证失效，请重新登录")

    phone = payload.get("phone")
    if not phone:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前账号不支持切换孩子")

    students = _students_bound_to_phone(db, phone)
    if not students:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该手机号未绑定学生，请联系班主任绑定",
        )

    if len(students) == 1:
        return SwitchStudentResponse(
            message="仅绑定一个孩子，无需切换",
            students=[StudentBrief(id=students[0][0].id, name=students[0][0].name, class_id=students[0][0].class_id, class_name=students[0][1])],
        )

    temp_token = create_temp_token(phone=phone)
    return SwitchStudentResponse(
        temp_token=temp_token,
        students=[
            StudentBrief(id=s.id, name=s.name, class_id=s.class_id, class_name=class_name)
            for s, class_name in students
        ],
    )


@router.post("/select-student", response_model=TokenResponse)
def select_student(
    body: SelectStudentRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        payload = decode_token(body.temp_token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="临时令牌已过期，请重新登录",
        )

    if payload.get("type") != TOKEN_TYPE_TEMP:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="临时令牌无效")

    phone = payload.get("phone")
    student = db.get(User, body.student_id)
    if (
        student is None
        or student.role != Role.student
        or student.phone != phone
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权选择该学生")

    access_token = _issue_tokens(response, student)
    return TokenResponse(
        access_token=access_token,
        must_change_password=student.must_change_password,
        role=student.role.value,
        user=_user_info(student),
    )
