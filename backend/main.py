"""CampusClaw FastAPI 应用入口。

启动方式（uv 管理环境）：
    uv run uvicorn main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

import models  # noqa: F401  # 确保模型注册到 Base.metadata
from config import settings
from database import Base, SessionLocal, engine, run_simple_migrations
from routers import auth, materials, student, teacher
from security import JWTError, TOKEN_TYPE_ACCESS, decode_token
from services import write_audit_log


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 简单迁移：骨架表升级（materials 扩展为业务表等）
    run_simple_migrations()
    # 启动时自动建表（SQLite 文件随之生成）
    Base.metadata.create_all(bind=engine)
    yield


# ENABLE_DOCS=false 时关闭交互式文档（生产部署不暴露接口自描述）
_docs_enabled = settings.enable_docs

app = FastAPI(
    title="CampusClaw API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

# CORS：前端与后端不同端口，必须允许 credentials（HttpOnly Cookie 刷新）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(teacher.router)
app.include_router(student.router)
app.include_router(materials.router)


# ---------------------------------------------------------------------------
# 403 审计日志中间件：拦截 403 响应，异步写入 AuditLog
# ---------------------------------------------------------------------------


@app.middleware("http")
async def audit_403_middleware(request: Request, call_next):
    response = await call_next(request)

    if response.status_code == 403:
        # 从 Authorization 头解析用户信息（可选，无 Token 则 user_id/role 为 None）
        user_id = None
        role = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                payload = decode_token(token)
                if payload.get("type") == TOKEN_TYPE_ACCESS:
                    user_id = payload.get("user_id")
                    role = payload.get("role")
            except JWTError:
                pass

        ip = request.client.host if request.client else None
        # 异步写入：用独立 DB session，catch-and-log 不影响主请求
        try:
            audit_db = SessionLocal()
            write_audit_log(
                audit_db,
                user_id=user_id,
                role=role,
                request_path=request.url.path,
                method=request.method,
                status_code=403,
                ip_address=ip,
            )
        finally:
            audit_db.close()

    return response


@app.get("/api/health", tags=["health"])
def health_check():
    return {"status": "ok", "sms_mock": settings.sms_mock}
