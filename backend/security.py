"""安全工具：密码哈希、密码策略、初始密码、JWT 签发与解析。"""

import re
import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from config import settings

# ---------------------------------------------------------------------------
# 密码哈希（bcrypt 加盐）
# ---------------------------------------------------------------------------

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, password_hash: str) -> bool:
    return pwd_context.verify(plain, password_hash)


# ---------------------------------------------------------------------------
# 密码策略：至少 8 位，必须同时包含大写字母、小写字母、数字、特殊字符
# ---------------------------------------------------------------------------

_SPECIAL_CHARS = r"!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~"
_POLICY_PATTERN = re.compile(
    rf"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[{re.escape(_SPECIAL_CHARS)}]).{{8,}}$"
)


def validate_password_policy(password: str) -> tuple[bool, str]:
    """返回 (是否合规, 不合规原因)。"""
    if len(password) < 8:
        return False, "密码长度至少为 8 位"
    if not re.search(r"[a-z]", password):
        return False, "密码必须包含小写字母"
    if not re.search(r"[A-Z]", password):
        return False, "密码必须包含大写字母"
    if not re.search(r"\d", password):
        return False, "密码必须包含数字"
    if not re.search(rf"[{re.escape(_SPECIAL_CHARS)}]", password):
        return False, "密码必须包含特殊字符"
    if not _POLICY_PATTERN.match(password):
        return False, "密码不符合安全策略"
    return True, ""


# ---------------------------------------------------------------------------
# 初始密码：学校三位小写缩写 + 学号/工号后 6 位，例如 thu123456
# ---------------------------------------------------------------------------


def generate_initial_password(identifier: str) -> str:
    tail = identifier[-6:]
    return f"{settings.school_abbr.lower()}{tail}"


# ---------------------------------------------------------------------------
# JWT：Access Token(2h) / Refresh Token(7d) / Temp Token(5min)
# ---------------------------------------------------------------------------

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"
TOKEN_TYPE_TEMP = "temp"

REFRESH_COOKIE_NAME = "refresh_token"


def _create_token(
    data: dict,
    expires_delta: timedelta,
    token_type: str,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        **data,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(
    *,
    user_id: int,
    role: str,
    class_id: int | None,
    must_change_password: bool,
    teaching_classes: list[int] | None = None,
) -> str:
    """正式 Access Token：user_id / role / class_id / must_change_password / teaching_classes，2h。"""
    payload: dict = {
        "user_id": user_id,
        "role": role,
        "class_id": class_id,
        "must_change_password": must_change_password,
    }
    if teaching_classes is not None:
        payload["teaching_classes"] = teaching_classes
    return _create_token(
        payload,
        timedelta(minutes=settings.access_token_expire_minutes),
        TOKEN_TYPE_ACCESS,
    )


def create_refresh_token(
    *,
    user_id: int,
    role: str,
    class_id: int | None,
    must_change_password: bool,
    phone: str | None = None,
    teaching_classes: list[int] | None = None,
) -> str:
    """Refresh Token：7d，HttpOnly Cookie 存放。含 phone 供多娃切换重新查询学生列表。"""
    payload: dict = {
        "user_id": user_id,
        "role": role,
        "class_id": class_id,
        "must_change_password": must_change_password,
        "phone": phone,
    }
    if teaching_classes is not None:
        payload["teaching_classes"] = teaching_classes
    return _create_token(
        payload,
        timedelta(days=settings.refresh_token_expire_days),
        TOKEN_TYPE_REFRESH,
    )


def create_temp_token(*, phone: str) -> str:
    """Temp Token：仅含 phone，5min，仅用于多娃选择流程。"""
    return _create_token(
        {"phone": phone},
        timedelta(minutes=settings.temp_token_expire_minutes),
        TOKEN_TYPE_TEMP,
    )


def decode_token(token: str) -> dict:
    """解析并校验 JWT，失败抛出 JWTError。"""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


__all__ = [
    "JWTError",
    "REFRESH_COOKIE_NAME",
    "TOKEN_TYPE_ACCESS",
    "TOKEN_TYPE_REFRESH",
    "TOKEN_TYPE_TEMP",
    "create_access_token",
    "create_refresh_token",
    "create_temp_token",
    "decode_token",
    "generate_initial_password",
    "hash_password",
    "validate_password_policy",
    "verify_password",
]
