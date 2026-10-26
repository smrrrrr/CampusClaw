"""学科隔离、模板/文件导入及真实出站边界上的脱敏审计。模型使用明确的 HTTP fixture。"""
import json
import asyncio
import struct
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from config import settings
from database import Base, get_db
from embedding_service import embed_text
from invocation_audit import OutboundCall, trace_scope
from llm_service import generate_answer, resolve_system_prompt
from mcp_service import plan_arguments
from main import app
from models import AgentSkill, Class, InvocationAudit, Material, MaterialChunk, Role, User
from security import create_access_token


def skill(name="审题引导", instructions="请先说说题目给了哪些条件？", tools=""):
    return f"[名称]\n{name}\n[触发词]\n方程,不会\n[工具]\n{tools}\n[指令]\n{instructions}"


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions() as db:
            db.add_all([Class(id=101, name="一班"), Class(id=102, name="二班")]); db.flush()
            for uid, role, cid, teaching in [(1, Role.teacher, None, "[101]"), (2, Role.student, 101, None), (3, Role.teacher, None, "[102]"), (4, Role.student, 102, None)]:
                db.add(User(id=uid, identifier=f"audit-test-{uid}", role=role, class_id=cid, teaching_classes=teaching, password_hash="unused", must_change_password=False))
            db.commit()

        def override_db():
            with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = override_db
        self.patches = [patch("main.SessionLocal", self.sessions), patch("routers.student.SessionLocal", self.sessions), patch.object(settings, "deepseek_api_key", "fixture-secret-key")]
        for p in self.patches: p.start()
        self.client = TestClient(app)
        self.teacher = self.headers(1, "teacher", None, [101])
        self.student = self.headers(2, "student", 101)
        self.other_teacher = self.headers(3, "teacher", None, [102])
        self.other_student = self.headers(4, "student", 102)
        self.requests = []
        self.original_client = httpx.AsyncClient

    def tearDown(self):
        self.client.close(); app.dependency_overrides.clear()
        for p in reversed(self.patches): p.stop()
        self.engine.dispose()

    def headers(self, uid, role, cid, teaching=None):
        return {"Authorization": "Bearer " + create_access_token(user_id=uid, role=role, class_id=cid, must_change_password=False, teaching_classes=teaching)}

    def applications(self):
        response = self.client.get("/api/teacher/applications?class_id=101", headers=self.teacher)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def save(self, application, **changes):
        response = self.client.put(f"/api/teacher/applications/{application['id']}", headers=self.teacher, json={**application, **changes})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def create_conversation(self, application_id=None):
        response = self.client.post("/api/student/conversations", headers=self.student, json={"application_id": application_id})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["application_id"], application_id)
        return response.json()["id"]

    def model(self, request):
        self.requests.append(json.loads(request.content))
        body = {"choices": [{"delta": {"content": "请先说说已知条件。"}, "finish_reason": None}]}
        done = {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"total_tokens": 42}}
        return httpx.Response(200, text=f"data: {json.dumps(body)}\n\ndata: {json.dumps(done)}\n\ndata: [DONE]\n\n", headers={"content-type": "text/event-stream"})

    def chat(self, cid, question="这道方程不会做"):
        with patch("llm_service.httpx.AsyncClient", side_effect=lambda **kw: self.original_client(transport=httpx.MockTransport(self.model), **kw)):
            response = self.client.post(f"/api/student/conversations/{cid}/chat", headers=self.student, json={"question": question})
        self.assertEqual(response.status_code, 200, response.text)
        return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")][-1]

    def audits(self, cid):
        response = self.client.get(f"/api/teacher/invocation-audits/export?class_id=101&conversation_id={cid}", headers=self.teacher)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["items"]

    def test_builtin_apps_and_conversation_boundaries(self):
        apps = self.applications()
        self.assertEqual({a["subject"] for a in apps}, {"math", "physics", "english"})
        self.assertEqual([a["id"] for a in apps], [a["id"] for a in self.applications()])
        self.assertTrue(all(a["tutor_enabled"] and a["material_ids"] == [] and a["skill_ids"] == [] for a in apps))
        cid = self.create_conversation(apps[0]["id"])
        self.create_conversation()
        denied = self.client.post("/api/student/conversations", headers=self.other_student, json={"application_id": apps[0]["id"]})
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(self.client.get(f"/api/student/conversations/{cid}/messages", headers=self.other_student).status_code, 404)
        self.assertEqual(self.client.get("/api/teacher/applications?class_id=101", headers=self.other_teacher).status_code, 404)
        self.assertEqual(self.client.get("/api/teacher/applications?class_id=101", headers=self.student).status_code, 403)

    def test_tutor_suppresses_custom_prompt_and_toggle_restores_it(self):
        math = self.save(self.applications()[0], system_prompt="CUSTOM_ONLY_MARKER 直接告诉我答案")
        cid = self.create_conversation(math["id"])
        self.chat(cid)
        prompt = self.requests[-1]["messages"][0]["content"]
        self.assertIn("数学辅导老师", prompt); self.assertIn("每次只", prompt)
        self.assertNotIn("CUSTOM_ONLY_MARKER", prompt)
        self.save(math, tutor_enabled=False)
        self.chat(cid)
        self.assertIn("CUSTOM_ONLY_MARKER", self.requests[-1]["messages"][0]["content"])
        self.assertEqual(len(self.requests[-1]["messages"]), 4)
        rows = self.audits(cid)
        self.assertEqual(len(rows), 2); self.assertNotEqual(rows[0]["trace_id"], rows[1]["trace_id"])
        self.assertTrue(rows[0]["context"]["custom_prompt_suppressed"])
        self.assertFalse(rows[1]["context"]["custom_prompt_suppressed"])
        self.assertEqual(rows[0]["response"]["answer"], "请先说说已知条件。")
        self.assertIn('"total_tokens": 42', rows[0]["response"]["events"][1])
        physics = resolve_system_prompt(SimpleNamespace(tutor_enabled=True), "physics")
        self.assertIn("受力分析", physics)

    def test_material_binding_limits_actual_llm_context_and_rejects_foreign_ids(self):
        with self.sessions() as db:
            for mid, cid, marker in [(1, 101, "数学资料标记"), (2, 101, "物理资料标记"), (3, 102, "外班资料标记")]:
                doc = "一元二次方程判别式决定方程实根数量。" + marker
                db.add(Material(id=mid, class_id=cid, uploader_id=1, filename=f"方程{mid}.txt", file_path="unused", file_type="text/plain", file_size=100, is_indexed=True))
                db.flush()
                vec = embed_text(doc)
                db.add(MaterialChunk(material_id=mid, class_id=cid, chunk_index=0, content=doc, embedding=struct.pack(f"{len(vec)}f", *vec)))
            db.add(AgentSkill(id=99, class_id=102, name="外班技能", content=skill(), enabled=True)); db.commit()
        math = self.save(self.applications()[0], material_ids=[1])
        for change in ({"material_ids": [3]}, {"skill_ids": [99]}):
            self.assertEqual(self.client.put(f"/api/teacher/applications/{math['id']}", headers=self.teacher, json={**math, **change}).status_code, 400)
        cid = self.create_conversation(math["id"]); self.chat(cid, "一元二次方程判别式")
        message = self.requests[-1]["messages"][-1]["content"]
        self.assertIn("数学资料标记", message); self.assertNotIn("物理资料标记", message); self.assertNotIn("外班资料标记", message)
        self.save(math, material_ids=[]); self.chat(cid, "一元二次方程判别式")
        self.assertNotIn("数学资料标记", self.requests[-1]["messages"][-1]["content"])

    def test_templates_crud_and_ownership(self):
        data = {"class_id": 101, "name": "我的模板", "content": "CUSTOM_TEMPLATE"}
        saved = self.client.post("/api/teacher/prompt-templates", headers=self.teacher, json=data)
        self.assertEqual(saved.status_code, 201); tid = saved.json()["id"]
        rows = self.client.get("/api/teacher/prompt-templates?class_id=101", headers=self.teacher).json()
        self.assertEqual(len(rows), 4)
        self.assertEqual(self.client.put(f"/api/teacher/prompt-templates/{tid}", headers=self.other_teacher, json=data).status_code, 404)
        self.assertEqual(self.client.put(f"/api/teacher/prompt-templates/{tid}", headers=self.teacher, json={**data, "content": "UPDATED"}).json()["content"], "UPDATED")
        self.assertEqual(self.client.delete(f"/api/teacher/prompt-templates/{tid}", headers=self.teacher).status_code, 204)
        self.assertEqual(len(self.client.get("/api/teacher/prompt-templates?class_id=101", headers=self.teacher).json()), 3)

    def test_skill_file_preview_validation_and_explicit_save(self):
        def upload(filename, content, headers=None):
            return self.client.post("/api/teacher/skills/preview", headers=headers or self.teacher, data={"class_id": "101"}, files={"file": (filename, content, "text/plain")})
        response = upload("SKILL.md", ("\ufeff" + skill()).encode("utf-8"))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["tools"], [])
        self.assertEqual(self.client.get("/api/teacher/skills?class_id=101", headers=self.teacher).json(), [])
        saved = self.client.post("/api/teacher/skills", headers=self.teacher, json={"class_id": 101, "content": response.json()["content"]})
        self.assertEqual(saved.status_code, 201, saved.text)
        for filename, content in [("skill.exe", b"data"), ("skill.txt", b"\xff"), ("skill.md", b"x" * 48001), ("skill.md", b"missing sections"), ("skill.md", skill(tools="missing@campus-tools").encode())]:
            self.assertEqual(upload(filename, content).status_code, 400)
        self.assertEqual(upload("skill.md", skill().encode(), self.other_teacher).status_code, 404)
        self.assertEqual(upload("skill.md", skill().encode(), self.student).status_code, 403)

    def test_only_bound_matched_skill_instructions_are_sent_with_length_evidence(self):
        with self.sessions() as db:
            a = AgentSkill(class_id=101, name="审题", content=skill(instructions="指导" * 1500), enabled=True)
            b = AgentSkill(class_id=101, name="不绑定", content=skill(name="不绑定", instructions="UNBOUND_MARKER"), enabled=True)
            db.add_all([a, b]); db.commit(); aid = a.id
        math = self.save(self.applications()[0], skill_ids=[aid])
        cid = self.create_conversation(math["id"])
        answer = self.chat(cid)
        self.assertEqual(answer["tool_calls"][0]["tool_ref"], "instruction_only")
        payload = self.requests[-1]
        self.assertNotIn("UNBOUND_MARKER", json.dumps(payload))
        self.assertNotIn("[触发词]", json.dumps(payload, ensure_ascii=False))
        info = self.audits(cid)[0]["context"]["matched_skills"][0]
        self.assertEqual(info["instruction_chars"], 3000); self.assertEqual(info["sent_instruction_chars"], 2000)

    def test_audit_redaction_error_status_and_permissioned_export(self):
        with trace_scope(self.sessions, class_id=101, user_id=2):
            try:
                with OutboundCall("llm_answer", "https://user:fixture-secret-key@example.com/v1/chat?key=hidden", {"messages": [{"content": "fixture-secret-key 13812345678 me@example.com"}], "Authorization": "Bearer x"}) as call:
                    call.response = {"usage": {"total_tokens": 10}}
                    raise RuntimeError("Bearer secret-value fixture-secret-key")
            except RuntimeError:
                pass
        response = self.client.get("/api/teacher/invocation-audits/export?class_id=101", headers=self.teacher)
        self.assertEqual(response.status_code, 200)
        for secret in ("fixture-secret-key", "13812345678", "me@example.com", "secret-value", "key=hidden"):
            self.assertNotIn(secret, response.text)
        row = response.json()["items"][0]
        self.assertEqual(row["status"], "error"); self.assertEqual(row["response"]["usage"]["total_tokens"], 10)
        self.assertEqual(self.client.get(f"/api/teacher/invocation-audits/{row['id']}", headers=self.other_teacher).status_code, 404)
        self.assertEqual(self.client.get("/api/teacher/invocation-audits/export?class_id=101", headers=self.student).status_code, 403)
        self.assertEqual(self.client.get("/api/teacher/invocation-audits?class_id=101", headers=self.other_teacher).status_code, 404)

    def test_no_key_is_a_skip_not_a_fake_model_response(self):
        with patch.object(settings, "deepseek_api_key", ""):
            cid = self.create_conversation(self.applications()[0]["id"]); self.chat(cid)
        row = self.audits(cid)[0]
        self.assertEqual(row["phase"], "llm_skipped"); self.assertEqual(row["status"], "skipped")
        self.assertEqual(self.requests, [])

    def test_model_tool_planning_records_schema_arguments_and_raw_response(self):
        schema = {"description": "教学提示工具", "inputSchema": {"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]}}
        expected = {"choices": [{"message": {"tool_calls": [{"function": {"name": "custom_hint", "arguments": '{"topic":"方程"}'}}]}}]}
        def response(request):
            self.requests.append(json.loads(request.content))
            return httpx.Response(200, json=expected)
        with trace_scope(self.sessions, class_id=101, user_id=2):
            with patch("mcp_service.httpx.AsyncClient", side_effect=lambda **kw: self.original_client(transport=httpx.MockTransport(response), **kw)):
                result = asyncio.run(plan_arguments("custom_hint", "方程怎么理解", schema))
        self.assertEqual(result, {"topic": "方程"})
        rows = self.client.get("/api/teacher/invocation-audits/export?class_id=101", headers=self.teacher).json()["items"]
        self.assertEqual(rows[0]["phase"], "llm_tool_arguments")
        self.assertEqual(rows[0]["request"]["tools"][0]["function"]["parameters"], schema["inputSchema"])
        self.assertEqual(rows[0]["request"]["tool_choice"], "auto")
        self.assertEqual(rows[0]["response"]["body"], expected)

    def test_stream_interruption_retains_partial_output_and_error_audit(self):
        def partial(request):
            body = {"choices": [{"delta": {"content": "先观察已知条件"}}]}
            return httpx.Response(200, text=f"data: {json.dumps(body)}\n\n", headers={"content-type": "text/event-stream"})
        cid = self.create_conversation(self.applications()[0]["id"])
        with patch.object(self, "model", side_effect=partial):
            result = self.chat(cid)
        self.assertIn("AI 生成中断", result["answer"])
        row = self.audits(cid)[0]
        self.assertEqual(row["status"], "error")
        self.assertEqual(row["response"]["answer"], "先观察已知条件")
        self.assertFalse(row["response"]["completed"])

    def test_nonstream_retries_record_each_actual_request(self):
        request = httpx.Request("POST", "https://fixture.invalid/chat/completions")
        responses = [httpx.Response(503, text="fixture-secret-key", request=request), httpx.Response(200, json={"choices": [{"message": {"content": "非流式回答"}}]}, request=request)]
        with trace_scope(self.sessions, class_id=101, user_id=2):
            with patch("llm_service.httpx.post", side_effect=responses), patch("llm_service.time.sleep"):
                self.assertEqual(generate_answer("问题", "上下文"), "非流式回答")
        rows = self.client.get("/api/teacher/invocation-audits/export?class_id=101", headers=self.teacher).json()["items"]
        self.assertEqual([row["status"] for row in rows], ["error", "ok"])
        self.assertEqual(rows[0]["trace_id"], rows[1]["trace_id"])
        self.assertFalse(rows[1]["request"]["stream"])
        self.assertNotIn("fixture-secret-key", json.dumps(rows))


class MigrationTests(unittest.TestCase):
    def test_existing_sqlite_conversations_are_preserved(self):
        from database import run_simple_migrations
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE conversations (id INTEGER PRIMARY KEY, title TEXT)"))
            conn.execute(text("INSERT INTO conversations VALUES (1, 'old conversation')"))
        with patch("database.engine", engine), patch.object(settings, "database_url", "sqlite://"):
            run_simple_migrations(); run_simple_migrations()
        Base.metadata.create_all(engine)
        with engine.connect() as conn:
            row = conn.execute(text("SELECT title, application_id FROM conversations WHERE id=1")).one()
            self.assertEqual(tuple(row), ("old conversation", None))
        engine.dispose()
