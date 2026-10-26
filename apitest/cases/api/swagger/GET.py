# -*- coding: utf-8 -*-
"""GET /openapi.json 与 /docs —— 校验 OpenAPI 描述与 Swagger 文档可访问。"""

REQUIRED_PATHS = [
    "/api/auth/login",
    "/api/teacher/agent-config",
    "/api/student/ai-question",
    "/api/student/conversations",
]


def test_openapi_describes_key_paths(api):
    """openapi.json 200 且包含关键路径及请求/响应结构描述。"""
    r = api.get("/openapi.json")
    assert r.status_code == 200, r.status_code
    doc = r.json()
    assert doc.get("openapi")
    paths = doc.get("paths", {})
    for p in REQUIRED_PATHS:
        assert p in paths, f"openapi.json 应包含路径 {p}"

    # 登录：应声明 200 → TokenResponse 及其请求体；并包含标准 422 校验错误码
    login = paths["/api/auth/login"]["post"]
    responses = login.get("responses", {})
    assert "200" in responses, "登录接口应声明 200 成功响应"
    assert "422" in responses, "登录接口应声明 422 校验错误码"
    assert "application/json" in login.get("requestBody", {}).get("content", {}), \
        "登录接口应声明 JSON 请求体"

    # AI 检索接口：应声明 JSON 请求体与成功响应结构
    ai = paths["/api/student/ai-question"]["post"]
    assert "200" in ai.get("responses", {}), "AI 检索接口应声明 200 成功响应"
    assert "application/json" in ai.get("requestBody", {}).get("content", {}), \
        "AI 检索接口应声明 JSON 请求体"


def test_swagger_docs_page(api):
    """Swagger 文档页面可打开（本地 dev 服务 ENABLE_DOCS=true）。"""
    r = api.get("/docs")
    assert r.status_code == 200, r.status_code