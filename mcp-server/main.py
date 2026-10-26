"""无状态 MCP HTTP JSON-RPC 服务，课程实现协议版本 2025-06-18。"""
import hmac
import json
import os
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from tools import call_tool, list_tools

app = FastAPI(title="CampusClaw MCP Tools", docs_url=None, redoc_url=None, openapi_url=None)
PROTOCOL_VERSION = "2025-06-18"


def rpc_error(request_id, code, message):
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}})


@app.get("/health")
def health():
    return {"status": "ok", "service": "campus-tools"}


@app.get("/mcp")
def no_subscriptions():
    return Response(status_code=405, headers={"Allow": "POST"})


@app.post("/mcp")
async def mcp(request: Request):
    token = os.environ.get("MCP_AUTH_TOKEN", "")
    supplied = request.headers.get("Authorization", "")
    if not token or not hmac.compare_digest(supplied.encode(), f"Bearer {token}".encode()):
        return JSONResponse({"detail": "MCP Bearer 认证失败"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
    origin = request.headers.get("origin")
    if origin:
        allowed = os.environ.get("MCP_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8080,http://127.0.0.1:3000").split(",")
        if origin not in allowed:
            return JSONResponse({"detail": "不允许的 Origin"}, status_code=403)
    if request.headers.get("MCP-Protocol-Version", PROTOCOL_VERSION) != PROTOCOL_VERSION:
        return JSONResponse({"detail": "不支持的 MCP 协议版本"}, status_code=400)
    raw = await request.body()
    if len(raw) > 65536:
        return rpc_error(None, -32600, "请求过大")
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return rpc_error(None, -32700, "无法解析 JSON")
    if not isinstance(body, dict):
        return rpc_error(None, -32600, "必须提供 JSON-RPC 对象")
    request_id = body.get("id")
    if body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str) or ("id" in body and (isinstance(request_id, (bool, dict, list)) or request_id is None)):
        return rpc_error(None, -32600, "无效的 JSON-RPC 请求")
    method, params = body["method"], body.get("params", {})
    if not isinstance(params, dict):
        return rpc_error(request_id, -32602, "params 必须是对象")
    if "id" not in body:
        return Response(status_code=202)
    if method == "initialize":
        if not isinstance(params.get("clientInfo"), dict) or not isinstance(params.get("capabilities"), dict) or not isinstance(params.get("protocolVersion"), str):
            return rpc_error(request_id, -32602, "初始化缺少 protocolVersion/capabilities/clientInfo")
        result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "campus-tools", "version": "1.0.0"}}
    elif method == "tools/list":
        if params.get("cursor"):
            return rpc_error(request_id, -32602, "无效分页游标")
        result = {"tools": list_tools()}
    elif method == "tools/call":
        name, arguments = params.get("name"), params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return rpc_error(request_id, -32602, "工具名称必须是字符串，arguments 必须是对象")
        try:
            result = await call_tool(name, arguments)
        except KeyError:
            return rpc_error(request_id, -32602, "未知工具")
    elif method == "ping":
        result = {}
    else:
        return rpc_error(request_id, -32601, "不支持的 JSON-RPC 方法")
    return {"jsonrpc": "2.0", "id": request_id, "result": result}
