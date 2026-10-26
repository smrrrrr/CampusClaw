"""按提问关联的出站调用记录。只保存脱敏正文，不保存认证头。"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import logging
import re
import time
from uuid import uuid4
from urllib.parse import urlsplit, urlunsplit

from config import settings
from models import InvocationAudit

current_trace = ContextVar("invocation_trace", default=None)


def sanitize(value):
    if isinstance(value, dict):
        return {k: "[redacted]" if re.search(r"authorization|api[_-]?key|password|secret|cookie|^(?:access_|refresh_|auth_)?token$", str(k), re.I) else sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(v) for v in value]
    if not isinstance(value, str):
        return value
    for secret in (settings.deepseek_api_key, settings.mcp_auth_token, settings.jwt_secret_key):
        if secret:
            value = value.replace(secret, "[redacted]")
    value = re.sub(r"Bearer\s+[^\s\"']+", "Bearer [redacted]", value, flags=re.I)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[redacted]", value)
    value = re.sub(r"\b1[3-9]\d{9}\b", "[phone redacted]", value)
    value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email redacted]", value)
    return value


@dataclass
class Trace:
    sessions: object
    class_id: int
    user_id: int
    conversation_id: int | None = None
    application_id: int | None = None
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    context: dict = field(default_factory=dict)


@contextmanager
def trace_scope(sessions, **kwargs):
    trace = Trace(sessions, **kwargs)
    token = current_trace.set(trace)
    try:
        yield trace
    finally:
        current_trace.reset(token)


def update_context(**kwargs):
    trace = current_trace.get()
    if trace:
        trace.context.update(kwargs)


class OutboundCall:
    def __init__(self, phase, endpoint, request):
        self.trace = current_trace.get()
        self.phase, self.endpoint, self.request = phase, endpoint, sanitize(request)
        self.response, self.status = {}, "ok"
        self.started = time.monotonic()

    def __enter__(self):
        return self

    def __exit__(self, kind, error, tb):
        if error:
            self.status = "cancelled" if kind.__name__ in ("CancelledError", "GeneratorExit") else "error"
            self.response["error"] = str(error) or kind.__name__
        trace = self.trace
        if trace is None:
            return
        # 审计失败不得伪装为模型成功，也不打断已经开始的流式回答；服务端明确记录故障。
        try:
            endpoint = urlsplit(self.endpoint)
            safe_endpoint = urlunsplit((endpoint.scheme, endpoint.netloc.split("@")[-1], endpoint.path, "", ""))
            with trace.sessions() as db:
                db.add(InvocationAudit(trace_id=trace.trace_id, class_id=trace.class_id, user_id=trace.user_id,
                    conversation_id=trace.conversation_id, application_id=trace.application_id, phase=self.phase,
                    endpoint=safe_endpoint, request_json=json.dumps(self.request, ensure_ascii=False),
                    response_json=json.dumps(sanitize(self.response), ensure_ascii=False),
                    context_json=json.dumps(sanitize(trace.context), ensure_ascii=False), status=self.status,
                    duration_ms=int((time.monotonic() - self.started) * 1000)))
                db.commit()
        except Exception:
            logging.getLogger(__name__).exception("调用审计写入失败 trace=%s", trace.trace_id)


def record_skip(reason, answer=""):
    with OutboundCall("llm_skipped", "", {"reason": reason}) as call:
        call.status = "skipped"
        call.response = {"answer": answer}
