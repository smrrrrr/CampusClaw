"""教师按班管理 MCP 连接、技能文件和工具审计。"""
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from deps import CurrentUser, get_current_teacher
from mcp_service import MCPClient, MCPFailure, checked_base_url, parse_skill, validate_bindings
from models import AgentSkill, Class, MCPServer, ToolCallAudit

router = APIRouter(prefix="/api/teacher", tags=["MCP 与技能"])


class ServerRequest(BaseModel):
    class_id: int = Field(description="必须属于当前教师任教班级")
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$", examples=["campus-tools"])
    base_url: str = Field(max_length=512, examples=["http://mcp-server:8090"], description="服务端允许清单内的 Base URL，不填写 /mcp；密钥从服务端环境读取")


class ServerResponse(BaseModel):
    id: int
    class_id: int
    name: str
    base_url: str
    connected: bool
    token_configured: bool
    tools: list[dict]


class SkillRequest(BaseModel):
    class_id: int
    content: str = Field(min_length=1, max_length=12000, description="含 [名称]、[触发词]、[工具]、[指令] 的技能文件正文")
    enabled: bool = True


class SkillResponse(BaseModel):
    id: int
    class_id: int
    name: str
    content: str
    enabled: bool
    keywords: list[str]
    tools: list[str]


class AuditItem(BaseModel):
    id: int
    class_id: int
    user_id: int
    conversation_id: int
    tool_ref: str
    status: str
    duration_ms: int
    summary: str
    created_at: str


class AuditResponse(BaseModel):
    items: list[AuditItem]
    total: int


def require_class(db: Session, current: CurrentUser, class_id: int):
    if class_id not in (current.teaching_classes or []) or db.get(Class, class_id) is None:
        raise HTTPException(404, "班级不存在")


def server_for_teacher(db: Session, current: CurrentUser, server_id: int):
    server = db.query(MCPServer).filter(MCPServer.id == server_id, MCPServer.class_id.in_(current.teaching_classes or [])).first()
    if not server:
        raise HTTPException(404, "MCP 服务器不存在")
    return server


def server_response(server: MCPServer):
    return ServerResponse(id=server.id, class_id=server.class_id, name=server.name, base_url=server.base_url, connected=server.connected, token_configured=bool(settings.mcp_auth_token), tools=json.loads(server.tools_cache or "[]") if server.connected else [])


def skill_response(skill: AgentSkill):
    parsed = parse_skill(skill.content)
    return SkillResponse(id=skill.id, class_id=skill.class_id, name=skill.name, content=skill.content, enabled=skill.enabled, keywords=parsed["keywords"], tools=parsed["tools"])


@router.post("/skills/preview", summary="上传 UTF-8 技能文件并校验，预览后再保存")
async def preview_skill(class_id: int = Form(...), file: UploadFile = File(...), current: CurrentUser = Depends(get_current_teacher), db: Session = Depends(get_db)):
    require_class(db, current, class_id)
    if not (file.filename or "").lower().endswith((".md", ".txt")):
        raise HTTPException(400, "仅支持 .md 和 .txt 技能文件")
    data = await file.read(48001)
    if len(data) > 48000:
        raise HTTPException(400, "技能文件不能超过 48KB")
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(400, "请使用 UTF-8 编码的技能文件")
    if not content.strip() or len(content) > 12000:
        raise HTTPException(400, "技能内容不能为空且不能超过 12000 字符")
    parsed = parse_skill(content)
    validate_bindings(db, class_id, parsed)
    return {**parsed, "content": content, "filename": file.filename}


@router.get("/mcp-servers", response_model=list[ServerResponse], summary="列出本班 MCP 服务（不返回令牌）")
def list_servers(class_id: int = Query(...), current: CurrentUser = Depends(get_current_teacher), db: Session = Depends(get_db)):
    require_class(db, current, class_id)
    return [server_response(s) for s in db.query(MCPServer).filter_by(class_id=class_id).order_by(MCPServer.id).all()]


@router.post("/mcp-servers", response_model=ServerResponse, status_code=201, summary="登记本班 MCP 服务")
def register_server(body: ServerRequest, current: CurrentUser = Depends(get_current_teacher), db: Session = Depends(get_db)):
    require_class(db, current, body.class_id)
    server = MCPServer(class_id=body.class_id, name=body.name, base_url=checked_base_url(body.base_url))
    db.add(server)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "本班已登记同名 MCP 服务")
    return server_response(server)


@router.post("/mcp-servers/{server_id}/connect", response_model=ServerResponse, summary="初始化 MCP 并发现、缓存工具")
async def connect_server(server_id: int, current: CurrentUser = Depends(get_current_teacher), db: Session = Depends(get_db)):
    server = server_for_teacher(db, current, server_id)
    # 连接过程开始就失效旧缓存，防止失败时仍可调用旧工具。
    server.connected, server.tools_cache = False, "[]"
    server.revision += 1
    db.commit()
    revision = server.revision
    try:
        async with MCPClient(server.base_url) as client:
            tools = await client.discover()
    except (MCPFailure, HTTPException) as exc:
        raise HTTPException(502, str(exc) if isinstance(exc, MCPFailure) else exc.detail)
    db.refresh(server)
    if server.revision != revision:
        raise HTTPException(409, "连接状态已被其他操作修改，请重新连接")
    server.tools_cache = json.dumps(tools, ensure_ascii=False)
    server.connected = True
    db.commit()
    return server_response(server)


@router.post("/mcp-servers/{server_id}/disconnect", response_model=ServerResponse, summary="断开服务并立即清空工具缓存")
def disconnect_server(server_id: int, current: CurrentUser = Depends(get_current_teacher), db: Session = Depends(get_db)):
    server = server_for_teacher(db, current, server_id)
    server.connected, server.tools_cache = False, "[]"
    server.revision += 1
    db.commit()
    return server_response(server)


@router.get("/mcp-servers/{server_id}/tools", response_model=list[dict], summary="查看本班服务已发现工具，断开后为空")
def server_tools(server_id: int, current: CurrentUser = Depends(get_current_teacher), db: Session = Depends(get_db)):
    return server_response(server_for_teacher(db, current, server_id)).tools


@router.get("/skills", response_model=list[SkillResponse], summary="列出本班技能文件")
def list_skills(class_id: int = Query(...), current: CurrentUser = Depends(get_current_teacher), db: Session = Depends(get_db)):
    require_class(db, current, class_id)
    return [skill_response(s) for s in db.query(AgentSkill).filter_by(class_id=class_id).order_by(AgentSkill.id).all()]


@router.post("/skills", response_model=SkillResponse, status_code=201, summary="保存技能并校验所有本班工具绑定")
def create_skill(body: SkillRequest, current: CurrentUser = Depends(get_current_teacher), db: Session = Depends(get_db)):
    require_class(db, current, body.class_id)
    parsed = parse_skill(body.content)
    validate_bindings(db, body.class_id, parsed)
    skill = AgentSkill(class_id=body.class_id, name=parsed["name"], content=body.content, enabled=body.enabled)
    db.add(skill)
    db.commit()
    return skill_response(skill)


@router.put("/skills/{skill_id}", response_model=SkillResponse, summary="编辑或启停技能，重新校验工具绑定")
def update_skill(skill_id: int, body: SkillRequest, current: CurrentUser = Depends(get_current_teacher), db: Session = Depends(get_db)):
    skill = db.query(AgentSkill).filter(AgentSkill.id == skill_id, AgentSkill.class_id.in_(current.teaching_classes or [])).first()
    if not skill or skill.class_id != body.class_id:
        raise HTTPException(404, "技能不存在")
    parsed = parse_skill(body.content)
    validate_bindings(db, body.class_id, parsed)
    skill.name, skill.content, skill.enabled = parsed["name"], body.content, body.enabled
    db.commit()
    return skill_response(skill)


@router.get("/tool-audits", response_model=AuditResponse, summary="分页查询本班工具调用审计")
def tool_audits(class_id: int = Query(...), limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), current: CurrentUser = Depends(get_current_teacher), db: Session = Depends(get_db)):
    require_class(db, current, class_id)
    query = db.query(ToolCallAudit).filter_by(class_id=class_id)
    total = query.count()
    rows = query.order_by(ToolCallAudit.id.desc()).offset(offset).limit(limit).all()
    return AuditResponse(total=total, items=[AuditItem(id=r.id, class_id=r.class_id, user_id=r.user_id, conversation_id=r.conversation_id, tool_ref=r.tool_ref, status=r.status, duration_ms=r.duration_ms, summary=r.summary, created_at=r.created_at.isoformat()) for r in rows])
