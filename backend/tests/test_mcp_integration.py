"""真实 HTTP MCP + FastAPI 接口集成，独立内存数据，不调用真实大模型。"""
import json
import os
import socket
import threading
import time
import unittest
from unittest.mock import patch

import uvicorn
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from config import settings
from database import Base, get_db
from main import app
from models import Class, Conversation, Message, Role, ToolCallAudit, User
from security import create_access_token
from test_mcp_tools import mcp_app


def skill_file(tool="formula_hint", keywords="公式", server="campus-tools"):
    return f"[名称]\n测试技能\n[触发词]\n{keywords}\n[工具]\n{tool}@{server}\n[指令]\n根据工具事实回答，不编造。"


class MCPIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.env = patch.dict(os.environ, {"MCP_AUTH_TOKEN": "integration-only-token"})
        cls.env.start()
        cls.sock = socket.socket()
        cls.sock.bind(("127.0.0.1", 0))
        cls.base_url = f"http://127.0.0.1:{cls.sock.getsockname()[1]}"
        cls.server = uvicorn.Server(uvicorn.Config(mcp_app.app, log_level="critical", access_log=False, loop="asyncio"))
        cls.thread = threading.Thread(target=lambda: cls.server.run(sockets=[cls.sock]), daemon=True)
        cls.thread.start()
        until = time.monotonic() + 5
        while not cls.server.started and time.monotonic() < until:
            time.sleep(.01)
        if not cls.server.started:
            raise RuntimeError("测试 MCP 服务启动失败")

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(5)
        cls.sock.close()
        cls.env.stop()

    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions() as db:
            db.add_all([Class(id=101, name="一班"), Class(id=102, name="二班")])
            db.flush()
            for uid, role, cid, teaching in [(1, Role.teacher, None, "[101]"), (2, Role.student, 101, None), (3, Role.student, 102, None), (4, Role.teacher, None, "[102]")]:
                db.add(User(id=uid, identifier=f"test{uid}", role=role, class_id=cid, teaching_classes=teaching, name=f"测试{uid}", password_hash="unused", must_change_password=False))
            db.commit()

        def override_db():
            with self.sessions() as db: yield db
        app.dependency_overrides[get_db] = override_db
        self.patches = [
            patch("main.SessionLocal", self.sessions), patch("routers.student.SessionLocal", self.sessions),
            patch.object(settings, "mcp_auth_token", "integration-only-token"),
            patch.object(settings, "mcp_allowed_base_urls", self.base_url), patch.object(settings, "deepseek_api_key", ""),
        ]
        for item in self.patches: item.start()
        self.client = TestClient(app)
        self.teacher, self.student = self.headers(1, "teacher", None, [101]), self.headers(2, "student", 101)
        self.other_teacher, self.other_student = self.headers(4, "teacher", None, [102]), self.headers(3, "student", 102)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        for item in reversed(self.patches): item.stop()
        self.engine.dispose()

    def headers(self, uid, role, cid, teaching=None):
        token = create_access_token(user_id=uid, role=role, class_id=cid, must_change_password=False, teaching_classes=teaching)
        return {"Authorization": f"Bearer {token}"}

    def register(self):
        result = self.client.post("/api/teacher/mcp-servers", headers=self.teacher, json={"class_id": 101, "name": "campus-tools", "base_url": self.base_url})
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()["id"]

    def connect(self, sid):
        response = self.client.post(f"/api/teacher/mcp-servers/{sid}/connect", headers=self.teacher)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual({t["name"] for t in response.json()["tools"]}, {"formula_hint", "unit_convert", "weather_query"})
        self.assertNotIn("integration-only-token", response.text)

    def save_skill(self, content):
        response = self.client.post("/api/teacher/skills", headers=self.teacher, json={"class_id": 101, "content": content})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def conversation(self):
        return self.client.post("/api/student/conversations", headers=self.student, json={}).json()["id"]

    def chat(self, cid, question):
        response = self.client.post(f"/api/student/conversations/{cid}/chat", headers=self.student, json={"question": question})
        self.assertEqual(response.status_code, 200, response.text)
        return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]

    def test_live_http_discovery_skill_chat_audit_history_and_disconnect(self):
        sid = self.register()
        self.connect(sid)
        self.save_skill(skill_file())
        cid = self.conversation()
        events = self.chat(cid, "速度公式是什么")
        self.assertEqual(events[0]["type"], "meta")
        self.assertEqual(events[0]["tool_calls"][0]["status"], "ok")
        self.assertIn("v=s/t", events[-1]["answer"])
        self.assertEqual(events[-1]["tool_calls"][0]["tool_ref"], "formula_hint@campus-tools")
        history = self.client.get(f"/api/student/conversations/{cid}/messages", headers=self.student).json()
        self.assertEqual(history[-1]["tool_calls"][0]["status"], "ok")
        audit = self.client.get("/api/teacher/tool-audits?class_id=101", headers=self.teacher).json()
        self.assertEqual(audit["items"][0]["status"], "ok")
        self.assertEqual(audit["items"][0]["user_id"], 2)
        outbound = self.client.get(f"/api/teacher/invocation-audits/export?class_id=101&conversation_id={cid}", headers=self.teacher).json()["items"]
        rpc = next(item for item in outbound if item["phase"] == "mcp_rpc" and item["request"]["method"] == "tools/call")
        self.assertEqual(rpc["request"]["params"], {"name": "formula_hint", "arguments": {"topic": "速度公式是什么"}})
        self.assertIn("v=s/t", json.dumps(rpc["response"], ensure_ascii=False))
        self.assertTrue(any(item["phase"] == "llm_skipped" for item in outbound))
        self.assertEqual(len({item["trace_id"] for item in outbound}), 1)
        self.client.post(f"/api/teacher/mcp-servers/{sid}/disconnect", headers=self.teacher)
        self.assertEqual(self.client.get(f"/api/teacher/mcp-servers/{sid}/tools", headers=self.teacher).json(), [])
        events = self.chat(cid, "再说一下速度公式")
        self.assertEqual(events[-1]["tool_calls"][0]["status"], "denied")
        invalid = self.client.post("/api/teacher/skills", headers=self.teacher, json={"class_id": 101, "content": skill_file()})
        self.assertEqual(invalid.status_code, 400)

    def test_unit_convert_parameters_and_tool_error_are_visible(self):
        self.connect(self.register())
        self.save_skill(skill_file("unit_convert", "转成"))
        cid = self.conversation()
        result = self.chat(cid, "1 km 转成 m")[-1]
        self.assertIn("1000 m", result["answer"])
        self.assertEqual(result["tool_calls"][0]["status"], "ok")
        invalid = self.chat(cid, "1 m 转成 kg")[-1]
        self.assertEqual(invalid["tool_calls"][0]["status"], "error")
        self.assertIn("量纲", invalid["answer"])

    def test_permission_boundaries_and_unlisted_url(self):
        sid = self.register()
        for headers, expected in [(self.student, 403), (self.other_teacher, 404), ({}, 401)]:
            response = self.client.post(f"/api/teacher/mcp-servers/{sid}/connect", headers=headers)
            self.assertEqual(response.status_code, expected)
        blocked = self.client.post("/api/teacher/mcp-servers", headers=self.teacher, json={"class_id": 101, "name": "blocked", "base_url": "http://169.254.169.254"})
        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(self.client.get("/api/teacher/tool-audits?class_id=101", headers=self.other_teacher).status_code, 404)
        cid = self.conversation()
        for method, path in [("get", f"/api/student/conversations/{cid}/messages"), ("delete", f"/api/student/conversations/{cid}")]:
            self.assertEqual(getattr(self.client, method)(path, headers=self.other_student).status_code, 404)
        self.assertEqual(self.client.post(f"/api/student/conversations/{cid}/chat", headers=self.other_student, json={"question": "公式"}).status_code, 404)

    def test_bad_binding_and_failed_connection_clear_cache(self):
        sid = self.register()
        self.connect(sid)
        with patch.object(settings, "mcp_auth_token", "wrong"):
            response = self.client.post(f"/api/teacher/mcp-servers/{sid}/connect", headers=self.teacher)
            self.assertEqual(response.status_code, 502)
        self.assertEqual(self.client.get(f"/api/teacher/mcp-servers/{sid}/tools", headers=self.teacher).json(), [])
        for content in ["invalid", skill_file("missing"), skill_file(server="other-class")]:
            self.assertEqual(self.client.post("/api/teacher/skills", headers=self.teacher, json={"class_id": 101, "content": content}).status_code, 400)

    def test_untrusted_tool_data_stays_in_user_message(self):
        self.connect(self.register())
        self.save_skill(skill_file())
        captured = []
        async def fake_stream(messages):
            captured.extend(messages)
            yield "测试回答"
        with patch("routers.student.stream_chat", fake_stream):
            self.chat(self.conversation(), "速度公式")
        self.assertIn("不可信数据", captured[0]["content"])
        self.assertIn("外部工具数据 JSON", captured[-1]["content"])
        self.assertNotIn("v=s/t", captured[0]["content"])

    def test_weather_clarifies_then_resumes_location_and_date(self):
        self.connect(self.register())
        self.save_skill(skill_file("weather_query", "天气,气温,降雨"))
        calls = []
        async def tool(name, arguments):
            calls.append(arguments)
            data = {"location": {"requested": arguments["location"], "name": "大兴", "admin1": "北京市"}, "timezone": "Asia/Shanghai", "current": {"time": "2026-10-21T12:00", "temperature_2m": 10.4, "relative_humidity_2m": 50}, "forecast": [{"time": "2026-10-22" if arguments['day_offset'] else "2026-10-21", "temperature_2m_min": 10, "temperature_2m_max": 20, "weather_code": 3}], "fetched_at": "2026-10-21T04:00:00Z"}
            return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}], "isError": False}
        cid = self.conversation()
        with patch.object(mcp_app, "call_tool", tool):
            prompt = self.chat(cid, "今天的天气怎么样")[-1]
            self.assertEqual(prompt["tool_calls"][0]["status"], "needs_input")
            self.assertIn("城市或区县", prompt["answer"])
            self.assertNotIn("资料", prompt["answer"])
            self.assertEqual(calls, [])
            with self.sessions() as db: self.assertEqual(db.query(ToolCallAudit).count(), 0)
            # 每次接口请求重新从数据库读取历史，不依赖前端内存。
            answered = self.chat(cid, "北京市大兴区")[-1]
            self.assertEqual(calls[-1], {"location": "北京市大兴区", "days": 1, "day_offset": 0})
            self.assertEqual(answered["tool_calls"][0]["status"], "ok")
            self.assertIn("10.4°C", answered["answer"])
            self.assertIn("50%", answered["answer"])
            self.assertNotIn("\\", answered["answer"])
            self.assertNotIn("资料", answered["answer"])
            self.chat(cid, "那明天呢")
            self.assertEqual(calls[-1]["location"], "北京市大兴区")
            self.assertEqual(calls[-1]["day_offset"], 1)
            # 新会话不能复用另一会话的待补参数。
            before = len(calls)
            self.chat(self.conversation(), "北京市大兴区")
            self.assertEqual(len(calls), before)

    def test_natural_weather_phrase_and_disconnect_while_awaiting_city(self):
        sid = self.register()
        self.connect(sid)
        self.save_skill(skill_file("weather_query", "天气"))
        cid = self.conversation()
        self.assertEqual(self.chat(cid, "明天天气怎么样")[-1]["tool_calls"][0]["status"], "needs_input")
        self.client.post(f"/api/teacher/mcp-servers/{sid}/disconnect", headers=self.teacher)
        resumed = self.chat(cid, "北京市大兴区")[-1]
        self.assertEqual(resumed["tool_calls"][0]["status"], "denied")
        self.connect(sid)
        calls = []
        async def tool(name, arguments):
            calls.append(arguments)
            return {"content": [{"type": "text", "text": "测试供应商不可用"}], "isError": True}
        with patch.object(mcp_app, "call_tool", tool):
            result = self.chat(self.conversation(), "请帮我看看北京明天会下雨吗")[-1]
            self.chat(self.conversation(), "我在北京市大兴区，今天要带伞吗")
        self.assertEqual(calls, [{"location": "北京", "days": 1, "day_offset": 1}, {"location": "北京市大兴区", "days": 1, "day_offset": 0}])
        self.assertEqual(result["tool_calls"][0]["status"], "error")
        self.assertNotIn("资料", result["answer"])
