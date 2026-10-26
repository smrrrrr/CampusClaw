"""学科应用、提示词模板与脱敏出站调用记录。"""
import json
from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from application_service import application_data, builtin_templates, ensure_applications, get_application
from database import get_db
from deps import CurrentUser, get_current_student, get_current_teacher
from invocation_audit import sanitize
from models import AgentSkill, InvocationAudit, Material, PromptTemplate
from routers.mcp import require_class
from services import require_student_class_id

router = APIRouter(tags=["学科应用与调用验证"])


class ApplicationRequest(BaseModel):
    class_id: int
    name: str = Field(min_length=1, max_length=128)
    system_prompt: str = Field(default="", max_length=12000)
    tutor_enabled: bool = True
    material_ids: list[int] | None = Field(default_factory=list, max_length=500)
    skill_ids: list[int] | None = Field(default_factory=list, max_length=100)


class TemplateRequest(BaseModel):
    class_id: int
    name: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=12000)


def validate_ids(db, model, class_id, ids):
    if ids is None:
        return None
    ids = list(dict.fromkeys(ids))
    found = {row.id for row in db.query(model).filter(model.class_id == class_id, model.id.in_(ids))}
    if found != set(ids):
        raise HTTPException(400, "绑定包含不存在或不属于本班的资料/技能")
    return json.dumps(ids)


@router.get("/api/student/applications")
def student_apps(current: CurrentUser = Depends(get_current_student), db: Session = Depends(get_db)):
    class_id = require_student_class_id(current.class_id)
    return [application_data(a, student=True) for a in ensure_applications(db, class_id)]


@router.get("/api/teacher/applications")
def teacher_apps(class_id: int, current: CurrentUser = Depends(get_current_teacher), db: Session = Depends(get_db)):
    require_class(db, current, class_id)
    return [application_data(a) for a in ensure_applications(db, class_id)]


@router.put("/api/teacher/applications/{application_id}")
def save_application(application_id: int, body: ApplicationRequest, current: CurrentUser = Depends(get_current_teacher), db: Session = Depends(get_db)):
    require_class(db, current, body.class_id)
    app = get_application(db, body.class_id, application_id)
    if not body.name.strip():
        raise HTTPException(400, "应用名称不能为空")
    material_ids = validate_ids(db, Material, body.class_id, body.material_ids)
    skill_ids = validate_ids(db, AgentSkill, body.class_id, body.skill_ids)
    app.name, app.system_prompt, app.tutor_enabled = body.name.strip(), body.system_prompt.strip(), body.tutor_enabled
    app.material_ids, app.skill_ids = material_ids, skill_ids
    db.commit()
    return application_data(app)


def template_data(row):
    return {"id": str(row.id), "name": row.name, "content": row.content, "builtin": False}


@router.get("/api/teacher/prompt-templates")
def list_templates(class_id: int, current: CurrentUser = Depends(get_current_teacher), db: Session = Depends(get_db)):
    require_class(db, current, class_id)
    return builtin_templates() + [template_data(t) for t in db.query(PromptTemplate).filter_by(class_id=class_id).order_by(PromptTemplate.id)]


def owned_template(db, current, template_id):
    row = db.query(PromptTemplate).filter(PromptTemplate.id == template_id, PromptTemplate.class_id.in_(current.teaching_classes or [])).first()
    if row is None:
        raise HTTPException(404, "模板不存在")
    return row


def validate_template(body):
    if not body.name.strip() or not body.content.strip():
        raise HTTPException(400, "模板名称和内容不能为空")


@router.post("/api/teacher/prompt-templates", status_code=201)
def create_template(body: TemplateRequest, current: CurrentUser = Depends(get_current_teacher), db: Session = Depends(get_db)):
    require_class(db, current, body.class_id)
    validate_template(body)
    row = PromptTemplate(class_id=body.class_id, name=body.name.strip(), content=body.content.strip())
    db.add(row)
    db.commit()
    return template_data(row)


@router.put("/api/teacher/prompt-templates/{template_id}")
def update_template(template_id: int, body: TemplateRequest, current: CurrentUser = Depends(get_current_teacher), db: Session = Depends(get_db)):
    row = owned_template(db, current, template_id)
    if row.class_id != body.class_id:
        raise HTTPException(404, "模板不存在")
    validate_template(body)
    row.name, row.content = body.name.strip(), body.content.strip()
    db.commit()
    return template_data(row)


@router.delete("/api/teacher/prompt-templates/{template_id}", status_code=204)
def delete_template(template_id: int, current: CurrentUser = Depends(get_current_teacher), db: Session = Depends(get_db)):
    db.delete(owned_template(db, current, template_id))
    db.commit()
    return Response(status_code=204)


def audit_query(db, class_id, conversation_id, trace_id):
    q = db.query(InvocationAudit).filter_by(class_id=class_id)
    if conversation_id is not None:
        q = q.filter_by(conversation_id=conversation_id)
    if trace_id:
        q = q.filter_by(trace_id=trace_id)
    return q


def audit_data(row, detail=False):
    result = {k: getattr(row, k) for k in ("id", "trace_id", "class_id", "user_id", "conversation_id", "application_id", "phase", "endpoint", "status", "duration_ms")}
    created = row.created_at
    result["created_at"] = (created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created.astimezone(timezone.utc)).isoformat()
    if detail:
        result.update(request=json.loads(row.request_json), response=json.loads(row.response_json), context=json.loads(row.context_json))
    # 再次脱敏，覆盖写入之后才配置的密钥。
    return sanitize(result)


@router.get("/api/teacher/invocation-audits")
def list_audits(class_id: int, conversation_id: int | None = None, trace_id: str | None = None,
                limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0),
                current: CurrentUser = Depends(get_current_teacher), db: Session = Depends(get_db)):
    require_class(db, current, class_id)
    q = audit_query(db, class_id, conversation_id, trace_id)
    return {"total": q.count(), "items": [audit_data(r) for r in q.order_by(InvocationAudit.id.desc()).offset(offset).limit(limit)]}


@router.get("/api/teacher/invocation-audits/export")
def export_audits(class_id: int, conversation_id: int | None = None, trace_id: str | None = None,
                  current: CurrentUser = Depends(get_current_teacher), db: Session = Depends(get_db)):
    require_class(db, current, class_id)
    q = audit_query(db, class_id, conversation_id, trace_id)
    if q.count() > 2000:
        raise HTTPException(400, "记录超过 2000 条，请按会话或追踪编号筛选后导出")
    body = {"class_id": class_id, "redacted": True, "items": [audit_data(r, True) for r in q.order_by(InvocationAudit.id)]}
    return Response(json.dumps(body, ensure_ascii=False, indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="llm-audits-{class_id}.json"'})


@router.get("/api/teacher/invocation-audits/{audit_id}")
def audit_detail(audit_id: int, current: CurrentUser = Depends(get_current_teacher), db: Session = Depends(get_db)):
    row = db.query(InvocationAudit).filter(InvocationAudit.id == audit_id, InvocationAudit.class_id.in_(current.teaching_classes or [])).first()
    if row is None:
        raise HTTPException(404, "调用记录不存在")
    return audit_data(row, True)
