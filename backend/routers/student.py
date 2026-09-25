"""学生相关路由：AI 提问（含每日次数限制 + 班级数据隔离）。"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from deps import CurrentUser, get_current_student
from config import settings
from llm_service import LLMGenerationError, generate_answer
from rag_search_service import retrieve_top_k
from services import (
    check_ai_limit,
    get_ai_daily_count,
    record_ai_question,
    require_student_class_id,
    write_audit_log,
)

router = APIRouter(prefix="/api/student", tags=["student"])


class AIQuestionRequest(BaseModel):
    question: str


class Citation(BaseModel):
    material_id: int
    filename: str
    chunk_index: int
    excerpt: str
    score: float


class AIQuestionResponse(BaseModel):
    id: int
    answer: str
    remaining: int
    citations: list[Citation] = []


@router.post("/ai-question", response_model=AIQuestionResponse)
def ask_ai(
    body: AIQuestionRequest,
    request: Request,
    background: BackgroundTasks,
    current: CurrentUser = Depends(get_current_student),
    db: Session = Depends(get_db),
):
    """学生发起 AI 提问。每日上限 20 次，按 student_id 计数，跨日重置。

    班级数据隔离：未分配班级的学生（class_id=NULL）被拒绝（403），
    提问记录关联到学生所在班级 class_id。
    """
    # 无班级边界处理：class_id 为 NULL 时拒绝查询
    class_id = require_student_class_id(current.class_id)

    allowed, reason = check_ai_limit(db, current.user_id)
    if not allowed:
        # 越权/超限记录审计日志
        background.add_task(
            _async_audit,
            user_id=current.user_id,
            role=current.role,
            path=request.url.path,
            method=request.method,
            status_code=429,
            ip=request.client.host if request.client else None,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=reason,
        )

    # 检索本班已索引材料分块（仅 is_indexed=true 且 class_id 匹配）
    hits = retrieve_top_k(db, [class_id], body.question)

    if not hits:
        answer = f"暂无相关班级资料，暂无法回答「{body.question}」。"
        citations: list[Citation] = []
    else:
        # 组装带引用编号的上下文
        context_lines = []
        citations = []
        for i, hit in enumerate(hits, start=1):
            excerpt = hit["content"][:200] + ("…" if len(hit["content"]) > 200 else "")
            context_lines.append(
                f"[{i}]《{hit['filename']}》(块{hit['chunk_index']}): {excerpt}"
            )
            citations.append(
                Citation(
                    material_id=hit["material_id"],
                    filename=hit["filename"],
                    chunk_index=hit["chunk_index"],
                    excerpt=excerpt,
                    score=hit["score"],
                )
            )
        context_block = "\n".join(context_lines)

        # DeepSeek 生成解答；未配置 Key / 调用失败时降级为展示检索段落
        try:
            generated = generate_answer(body.question, context_block)
        except LLMGenerationError:
            generated = None
            degraded = "AI 生成失败（服务暂不可用），已为你展示检索到的相关段落：\n" + context_block
        if generated:
            answer = generated
        elif generated is None and settings.deepseek_api_key:
            answer = degraded
        else:
            answer = (
                "AI 生成服务未配置 API Key，暂仅展示检索到的相关段落：\n" + context_block
            )
    log = record_ai_question(
        db,
        student_id=current.user_id,
        class_id=class_id,
        question=body.question,
        answer=answer,
    )
    remaining = 20 - get_ai_daily_count(db, current.user_id)
    return AIQuestionResponse(
        id=log.id, answer=log.answer or "", remaining=remaining, citations=citations
    )


def _async_audit(
    *,
    user_id: int | None,
    role: str | None,
    path: str,
    method: str,
    status_code: int,
    ip: str | None,
) -> None:
    """BackgroundTasks 调用的异步审计写入。"""
    db = SessionLocal()
    try:
        write_audit_log(
            db,
            user_id=user_id,
            role=role,
            request_path=path,
            method=method,
            status_code=status_code,
            ip_address=ip,
        )
    finally:
        db.close()
