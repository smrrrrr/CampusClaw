"""Pydantic 请求 / 响应模型。"""

from pydantic import BaseModel, Field


# --- 密码登录 ---


class LoginRequest(BaseModel):
    identifier: str = Field(..., description="学号 / 工号")
    password: str


class UserInfo(BaseModel):
    id: int
    role: str
    name: str | None = None
    class_id: int | None = None
    must_change_password: bool
    teaching_classes: list[int] | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool
    role: str
    user: UserInfo


# --- 改密 ---


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


# --- 验证码 ---


class SendCodeRequest(BaseModel):
    phone: str = Field(..., pattern=r"^1\d{10}$")


class SendCodeResponse(BaseModel):
    message: str
    # Mock 模式下返回验证码，生产模式不返回
    code: str | None = None


class VerifyCodeRequest(BaseModel):
    phone: str = Field(..., pattern=r"^1\d{10}$")
    code: str = Field(..., min_length=6, max_length=6)


class StudentBrief(BaseModel):
    id: int
    name: str | None = None
    class_id: int | None = None
    class_name: str | None = None


class VerifyCodeResponse(BaseModel):
    """单娃：直接签发正式 Token；多娃：返回 Temp Token 与学生列表。"""

    access_token: str | None = None
    token_type: str = "bearer"
    must_change_password: bool | None = None
    role: str | None = None
    user: UserInfo | None = None
    # 多娃
    temp_token: str | None = None
    students: list[StudentBrief] | None = None


class SelectStudentRequest(BaseModel):
    temp_token: str
    student_id: int


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool
    role: str
    teaching_classes: list[int] | None = None


class MessageResponse(BaseModel):
    message: str
