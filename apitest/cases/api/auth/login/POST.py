# -*- coding: utf-8 -*-
"""POST /api/auth/login —— 密码登录。"""

import pytest

from conftest import TEACHER, STUDENT


def test_teacher_login_success(api, db_conn):
    """教师登录：返回 token + 正确角色 + must_change_password=False。"""
    r = api.post("/api/auth/login", json=dict(TEACHER))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "teacher"
    assert body["must_change_password"] is False
    assert body["token_type"] == "bearer"
    u = body["user"]
    assert u["id"] == 1
    assert 101 in (u["teaching_classes"] or [])  # 王老师任教 101，供 agent-config 用例使用


def test_student_login_success(api, db_conn):
    """学生登录：返回 token + 正确角色 + 所在班级 class_id 一致。"""
    r = api.post("/api/auth/login", json=dict(STUDENT))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "student"
    assert body["user"]["id"] == 3
    assert body["user"]["class_id"] == 102  # 与数据库一致


def test_wrong_password_returns_401_and_counts(api, db_conn):
    """错误密码 → 401，且 login_attempts 计数递增（数据库一致性）。"""
    r = api.post(
        "/api/auth/login",
        json={"identifier": "apitest_nope", "password": "wrong-pass-1"},
    )
    assert r.status_code == 401, r.text
    rows = db_conn.execute(
        "select attempt_count from login_attempts where identifier='apitest_nope'"
    ).fetchall()
    assert rows, "数据库应记录本次失败尝试"
    assert rows[-1]["attempt_count"] >= 1
    # 清理：删除本用例产生的失败计数，保持幂等
    db_conn.execute("delete from login_attempts where identifier='apitest_nope'")
    db_conn.commit()