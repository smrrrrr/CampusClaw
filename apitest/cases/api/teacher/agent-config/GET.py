# -*- coding: utf-8 -*-
"""GET /api/teacher/agent-config —— 读取班级提示词与技能配置。"""


def test_get_agent_config_returns_fields(api, teacher_headers):
    """教师读取任教班级(101)配置：200 且含 system_prompt / tutor_enabled。"""
    r = api.get("/api/teacher/agent-config", params={"class_id": 101}, headers=teacher_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["class_id"] == 101
    assert isinstance(body["system_prompt"], str)
    assert isinstance(body["tutor_enabled"], bool)


def test_agent_config_requires_auth(api):
    """未携带 Bearer 访问受保护接口 → 401。"""
    r = api.get("/api/teacher/agent-config", params={"class_id": 101})
    assert r.status_code == 401, r.text