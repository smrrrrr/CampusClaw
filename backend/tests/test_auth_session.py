"""会话恢复回归测试，使用独立内存数据库，不读写开发数据。"""

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from main import app
from models import Class, Role, User
from security import REFRESH_COOKIE_NAME, create_access_token, decode_token, hash_password


class AuthSessionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        with self.sessions() as db:
            db.add_all([Class(id=101, name="测试一班"), Class(id=102, name="测试二班")])
            db.flush()
            password_hash = hash_password("Test@2026")
            db.add_all([
                User(id=1, role=Role.teacher, identifier="teacher", name="测试教师",
                     password_hash=password_hash, teaching_classes="[101, 102]",
                     must_change_password=False),
                User(id=2, role=Role.student, identifier="student", name="测试学生",
                     password_hash=password_hash, class_id=101, phone="13800000001",
                     must_change_password=True),
                User(id=3, role=Role.student, identifier="sibling", name="另一学生",
                     password_hash=password_hash, class_id=102, phone="13800000001",
                     must_change_password=False),
            ])
            db.commit()

        def override_db():
            with self.sessions() as db:
                yield db

        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def login(self, identifier):
        response = self.client.post("/api/auth/login", json={
            "identifier": identifier, "password": "Test@2026",
        })
        self.assertEqual(response.status_code, 200)
        return response

    def test_refresh_restores_teacher_and_current_permissions(self):
        login = self.login("teacher")
        cookie = login.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Path=/api/auth", cookie)
        with self.sessions() as db:
            db.get(User, 1).teaching_classes = json.dumps([102])
            db.commit()
        response = self.client.post("/api/auth/refresh")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["user"]["name"], "测试教师")
        self.assertEqual(data["role"], "teacher")
        self.assertEqual(data["user"]["teaching_classes"], [102])
        self.assertEqual(decode_token(data["access_token"])["teaching_classes"], [102])
        self.assertFalse(data["is_phone_login"])
        self.assertFalse(data["can_switch_student"])

    def test_password_student_still_requires_password_change(self):
        self.login("student")
        data = self.client.post("/api/auth/refresh").json()
        self.assertEqual(data["user"]["id"], 2)
        self.assertEqual(data["user"]["class_id"], 101)
        self.assertTrue(data["must_change_password"])
        self.assertFalse(data["is_phone_login"])
        self.assertFalse(data["can_switch_student"])

    def test_phone_login_and_selected_child_survive_repeated_refresh(self):
        with patch("routers.auth.settings.sms_mock", True):
            code = self.client.post("/api/auth/send-code", json={"phone": "13800000001"}).json()["code"]
        verified = self.client.post("/api/auth/verify-code", json={"phone": "13800000001", "code": code}).json()
        selected = self.client.post("/api/auth/select-student", json={
            "temp_token": verified["temp_token"], "student_id": 2,
        })
        self.assertEqual(selected.status_code, 200)
        for _ in range(2):
            response = self.client.post("/api/auth/refresh")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertTrue(data["is_phone_login"])
            self.assertTrue(data["can_switch_student"])
            self.assertEqual(data["user"]["id"], 2)

    def test_logout_removes_cookie_and_prevents_restoration(self):
        token = self.login("teacher").json()["access_token"]
        response = self.client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.post("/api/auth/refresh").status_code, 401)

    def test_missing_invalid_and_wrong_type_tokens_are_rejected(self):
        self.assertEqual(self.client.post("/api/auth/refresh").status_code, 401)
        for token in ["invalid", create_access_token(user_id=1, role="teacher", class_id=None, must_change_password=False)]:
            self.client.cookies.set(REFRESH_COOKIE_NAME, token, path="/api/auth")
            self.assertEqual(self.client.post("/api/auth/refresh").status_code, 401)


if __name__ == "__main__":
    unittest.main()
