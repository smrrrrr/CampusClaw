"""真实远端 MCP JSON 客户端、技能校验及受班级边界约束的执行器。"""
import json
import re
import time
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from config import settings
from models import AgentSkill, MCPServer, ToolCallAudit
from invocation_audit import OutboundCall, update_context

PROTOCOL = "2025-06-18"
TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SERVER_NAME = re.compile(r"^[a-z][a-z0-9-]{0,63}$")


class MCPFailure(Exception):
    pass


class MCPDenied(MCPFailure):
    pass


class MCPNeedsInput(MCPFailure):
    """需要用户补充参数，还没有执行远端调用。"""
    pass


WEATHER_INTENT = re.compile(r"天气|气温|降雨|下雨|下雪|冷不冷|热不热|冷吗|热吗|带伞|刮风|晴天")
WEATHER_DATE_REPLY = re.compile(r"^(?:那|那么|还有)?(?:今天|明天|后天)(?:呢|怎么样|如何)?[?？。]*$")


def location_reply(question: str) -> str | None:
    """保守识别单独补充的地名，避免把取消或新问题当成地点。"""
    value = re.sub(r"[，,。？！?!\s]+$", "", question.strip())
    value = re.sub(r"(?:呢|那边|这里)$", "", value)
    if re.search(r"我|想|请|帮|查|什么|怎么|多少|谢谢|不用|不查|取消|算了|好的|不会|公式|向量|换算|天气|今天|明天|后天", value):
        return None
    if value.lower() in {"thanks", "cancel", "no", "ok", "today", "tomorrow"}:
        return None
    return value if re.fullmatch(r"[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z ·.'-]{1,49}", value) else None


def weather_window(question: str) -> dict:
    if re.search(r"大后天|下周|下个月|昨天|历史|\d{4}-\d{2}-\d{2}", question):
        raise MCPFailure("目前支持今天、明天、后天或未来 1–7 天的天气，请明确查询范围。")
    match = re.search(r"未来(\d+|[一二两三四五六七八九十])天", question)
    count = int(match[1]) if match and match[1].isdigit() else ({"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}.get(match[1], 1) if match else 1)
    offset = 2 if "后天" in question else 1 if "明天" in question else 0
    if not 1 <= count <= 7 or count + offset > 7:
        raise MCPFailure("只能查询未来七天内的天气，请缩小日期范围。")
    return {"days": count, "day_offset": offset}


def weather_location(question: str) -> str | None:
    value = question.strip()
    value = re.sub(r"^(?:(?:能不能|能|可以|请问|请|帮我|帮忙|给我|我想知道|我想查|我想看|我现在在|我在|查询|查一下|查查|看看|查|问一下)|今天|明天|后天|的|\s)+", "", value)
    before = re.split(r"(?:今天|明天|后天|现在|目前|未来(?:\d+|[一二两三四五六七八九十])天|的?天气|气温|温度|(?:会不会|会|要)?下雨|(?:会不会|会)?下雪|降雨|冷不冷|热不热|冷吗|热吗|要不要带伞|需要带伞|带伞|刮风|晴天)", value, maxsplit=1)[0]
    return location_reply(before.rstrip("的，, "))


def recent_weather_context(history: list[dict]) -> dict | None:
    """只沿当前会话最近的天气话题续接，不读取其他会话或班级。"""
    for message in reversed(history[-6:]):
        if message["role"] == "assistant":
            for call in message.get("tool_calls", []):
                context = call.get("weather_context")
                if call.get("tool_ref", "").startswith("weather_query@") and isinstance(context, dict):
                    return context
        if message["role"] == "user":
            text = message["content"]
            if WEATHER_INTENT.search(text):
                try:
                    return {**weather_window(text), "location": weather_location(text)}
                except MCPFailure:
                    return None
            if not location_reply(text):
                return None
    return None


def weather_arguments(question: str, context: dict | None = None) -> dict:
    context = context or {}
    if WEATHER_INTENT.search(question) or WEATHER_DATE_REPLY.fullmatch(question.strip()):
        window = weather_window(question)
        location = weather_location(question) or context.get("location")
    else:
        window = {"days": context.get("days", 1), "day_offset": context.get("day_offset", 0)}
        location = location_reply(question)
    previous = context.get("location") or ""
    if location and previous:
        if location.endswith(("区", "县")) and "市" not in location and previous.endswith("市"):
            location = previous + location
        elif previous.endswith(("区", "县")) and "市" not in previous and location.endswith("市"):
            location += previous
    if not location:
        raise MCPNeedsInput("你想查询哪个城市或区县的天气？例如：北京市大兴区。")
    return {**window, "location": location}


def redact(value: str) -> str:
    for secret in (settings.mcp_auth_token, settings.deepseek_api_key):
        if secret:
            value = value.replace(secret, "[redacted]")
    return re.sub(r"Bearer\s+[^\s\"']+", "Bearer [redacted]", value, flags=re.I)


def checked_base_url(value: str) -> str:
    value = value.strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        raise HTTPException(400, "Base URL 格式无效")
    allowed = {url.strip().rstrip("/") for url in settings.mcp_allowed_base_urls.split(",")}
    if parsed.scheme not in ("http", "https") or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path or value not in allowed:
        raise HTTPException(400, "Base URL 未列入服务端 MCP_ALLOWED_BASE_URLS，或包含非法路径/凭证")
    return value


class MCPClient:
    def __init__(self, base_url: str):
        self.base_url = checked_base_url(base_url)
        self.headers = {"Authorization": f"Bearer {settings.mcp_auth_token}", "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": PROTOCOL}
        self.counter = 0
        self.client = None

    async def __aenter__(self):
        if not settings.mcp_auth_token:
            raise MCPFailure("服务端尚未配置 MCP_AUTH_TOKEN")
        self.client = httpx.AsyncClient(timeout=settings.mcp_timeout, follow_redirects=False, trust_env=False)
        try:
            result = await self.rpc("initialize", {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "campusclaw", "version": "1.0.0"}})
            if result.get("protocolVersion") != PROTOCOL or "tools" not in result.get("capabilities", {}):
                raise MCPFailure("MCP 协议版本或 tools 能力不兼容")
            await self.rpc("notifications/initialized", {}, notification=True)
            return self
        except BaseException:
            await self.client.aclose()
            raise

    async def __aexit__(self, *args):
        await self.client.aclose()

    async def rpc(self, method: str, params: dict, notification=False):
        self.counter += 1
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notification:
            body["id"] = self.counter
        try:
            with OutboundCall("mcp_rpc", self.base_url + "/mcp", body) as audit:
                async with self.client.stream("POST", self.base_url + "/mcp", headers=self.headers, json=body) as response:
                    audit.response = {"http_status": response.status_code}
                    if response.status_code == 401:
                        raise MCPFailure("MCP 认证失败，请检查服务端环境变量")
                    if response.is_redirect or response.status_code >= 400:
                        raise MCPFailure(f"MCP HTTP 错误（{response.status_code}）")
                    if notification:
                        return {}
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 65536:
                            raise MCPFailure("MCP 响应超过长度限制")
                        chunks.append(chunk)
                    data = json.loads(b"".join(chunks))
                    audit.response["body"] = data
                    if response.headers.get("Mcp-Session-Id"):
                        self.headers["Mcp-Session-Id"] = response.headers["Mcp-Session-Id"]
                    if not isinstance(data, dict) or data.get("jsonrpc") != "2.0" or data.get("id") != self.counter:
                        raise MCPFailure("MCP 返回无效 JSON-RPC 响应")
                    if "error" in data:
                        raise MCPFailure("MCP 拒绝了协议请求")
                    if not isinstance(data.get("result"), dict):
                        raise MCPFailure("MCP 响应缺少结果对象")
                    if data["result"].get("isError"):
                        audit.status = "tool_error"
                    return data["result"]
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise MCPFailure("MCP 连接超时或响应无效，请稍后重试") from exc

    async def discover(self):
        tools, cursor = [], None
        for _ in range(10):
            result = await self.rpc("tools/list", {"cursor": cursor} if cursor else {})
            page = result.get("tools")
            if not isinstance(page, list):
                raise MCPFailure("工具发现响应无效")
            for tool in page:
                if not isinstance(tool, dict) or not isinstance(tool.get("name"), str) or not TOOL_NAME.fullmatch(tool["name"]) or not isinstance(tool.get("inputSchema"), dict) or tool["inputSchema"].get("type") != "object":
                    raise MCPFailure("工具名称或参数 schema 无效")
                tools.append({"name": tool["name"], "description": str(tool.get("description", ""))[:500], "inputSchema": tool["inputSchema"]})
            cursor = result.get("nextCursor")
            if not cursor:
                if len({t["name"] for t in tools}) != len(tools):
                    raise MCPFailure("工具发现包含重复名称")
                return tools
        raise MCPFailure("工具分页超过上限")


def parse_skill(content: str) -> dict:
    sections = list(re.finditer(r"(?m)^\[(名称|触发词|工具|指令)\][ \t]*", content))
    if len(sections) != 4 or {m[1] for m in sections} != {"名称", "触发词", "工具", "指令"}:
        raise HTTPException(400, "技能必须各含一个 [名称]、[触发词]、[工具]、[指令] 段落")
    values = {match[1]: content[match.end():sections[i + 1].start() if i + 1 < len(sections) else len(content)].strip() for i, match in enumerate(sections)}
    keywords = [v.strip() for v in re.split(r"[,，、\n]", values["触发词"]) if v.strip()]
    refs = list(dict.fromkeys(v.strip() for v in re.split(r"[,，\n]", values["工具"]) if v.strip()))
    if not 1 <= len(values["名称"]) <= 128 or not keywords or any(len(v) > 50 for v in keywords) or len(keywords) > 20 or len(refs) > 3 or not values["指令"]:
        raise HTTPException(400, "技能名称/触发词/指令不能为空，最多 20 个触发词与 3 个工具；纯指导技能的 [工具] 可留空")
    for ref in refs:
        if ref == "knowledge_search":
            continue
        parts = ref.split("@")
        if len(parts) != 2 or not TOOL_NAME.fullmatch(parts[0]) or not SERVER_NAME.fullmatch(parts[1]):
            raise HTTPException(400, "MCP 引用必须为 tool_name@server-name")
    return {"name": values["名称"], "keywords": keywords, "tools": refs, "instructions": values["指令"]}


def resolve_tool(db: Session, class_id: int, ref: str):
    tool_name, server_name = ref.split("@")
    server = db.query(MCPServer).filter_by(class_id=class_id, name=server_name).first()
    if not server or not server.connected:
        raise MCPDenied("服务器未连接或不属于本班")
    schema = next((t for t in json.loads(server.tools_cache or "[]") if t["name"] == tool_name), None)
    if not schema:
        raise MCPDenied("工具未通过本班服务发现")
    return server, schema


def validate_bindings(db: Session, class_id: int, parsed: dict):
    for ref in parsed["tools"]:
        if ref == "knowledge_search":
            continue
        try:
            resolve_tool(db, class_id, ref)
        except MCPFailure as exc:
            raise HTTPException(400, str(exc)) from exc


def known_arguments(name: str, question: str) -> dict | None:
    if name == "formula_hint":
        return {"topic": question[:500]}
    if name == "unit_convert":
        match = re.search(r"(-?\d+(?:\.\d+)?)\s*([^\s\d，,。？?]+?)\s*(?:换算成|转换为|换成|转成|转为|等于多少|是多少|等于|到|to)\s*([^\s，,。？?]+)", question, re.I)
        if match:
            return {"value": float(match[1]), "from_unit": match[2], "to_unit": match[3]}
    if name == "weather_query":
        return weather_arguments(question)
    return None


async def plan_arguments(name: str, question: str, schema: dict):
    known = known_arguments(name, question)
    if known is not None:
        return known
    if not settings.deepseek_api_key:
        raise MCPFailure("参数不完整，请明确城市、日期范围，或使用“1 km 转成 m”这样的换算格式")
    payload = {
        "model": settings.deepseek_model, "temperature": 0,
        "messages": [{"role": "system", "content": "仅从用户问题提取工具参数；不得猜测缺失的城市、数量或单位。信息不足时不调用工具。"}, {"role": "user", "content": question}],
        "tools": [{"type": "function", "function": {"name": name, "description": schema.get("description", ""), "parameters": schema["inputSchema"]}}],
        "tool_choice": "auto",
    }
    url = settings.deepseek_base_url.rstrip("/") + "/chat/completions"
    try:
        with OutboundCall("llm_tool_arguments", url, payload) as audit:
            async with httpx.AsyncClient(timeout=min(settings.deepseek_timeout, 20)) as client:
                response = await client.post(url, headers={"Authorization": f"Bearer {settings.deepseek_api_key}"}, json=payload)
                audit.response = {"http_status": response.status_code, "body": response.text}
                response.raise_for_status()
                data = response.json()
                audit.response["body"] = data
                call = data["choices"][0]["message"].get("tool_calls", [])[0]["function"]
                args = json.loads(call["arguments"])
                if call["name"] != name or not isinstance(args, dict):
                    raise ValueError()
                return args
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        raise MCPFailure("无法从问题中确定工具参数，请补充明确的城市、数值和单位") from exc


async def run_skill_tools(db: Session, class_id: int, user_id: int, conversation_id: int, question: str, knowledge_context: str, history: list[dict] | None = None, skill_ids: list[int] | None = None):
    metadata, results, instructions, seen = [], [], [], set()
    query = db.query(AgentSkill).filter_by(class_id=class_id, enabled=True)
    if skill_ids is not None:
        query = query.filter(AgentSkill.id.in_(skill_ids))
    skills = query.order_by(AgentSkill.id).all()
    selected = []
    update_context(matched_skills=selected)
    matched = 0
    weather_context = recent_weather_context(history or [])
    weather_followup = weather_context is not None and (location_reply(question) is not None or WEATHER_DATE_REPLY.fullmatch(question.strip()))
    for skill in skills:
        parsed = parse_skill(skill.content)
        weather_bound = any(ref.startswith("weather_query@") for ref in parsed["tools"])
        if not any(k.lower() in question.lower() for k in parsed["keywords"]) and not (weather_bound and (WEATHER_INTENT.search(question) or weather_followup)):
            continue
        if matched >= 3:
            break
        matched += 1
        instructions.append(parsed["instructions"][:2000])
        selected.append({"id": skill.id, "name": parsed["name"], "file_chars": len(skill.content), "instruction_chars": len(parsed["instructions"]), "sent_instruction_chars": len(parsed["instructions"][:2000]), "tools": parsed["tools"]})
        if not parsed["tools"]:
            metadata.append({"tool_ref": "instruction_only", "status": "ok", "skill": parsed["name"], "summary": "已应用指导指令，未调用外部工具"})
        for ref in parsed["tools"]:
            if ref in seen or len(seen) >= 3:
                continue
            seen.add(ref)
            started, outcome, text = time.monotonic(), "ok", ""
            arguments = None
            if ref == "knowledge_search":
                metadata.append({"tool_ref": ref, "status": "ok", "skill": parsed["name"], "summary": "已检索本班资料"})
                continue
            try:
                # 从数据库重新读取连接状态，不能依赖保存技能时的快照。
                db.expire_all()
                server, schema = resolve_tool(db, class_id, ref)
            except MCPFailure as exc:
                outcome, text = "denied", str(exc)
            else:
                try:
                    arguments = weather_arguments(question, weather_context) if schema["name"] == "weather_query" else await plan_arguments(schema["name"], question, schema)
                    # 参数规划可能耗时：发起远端请求前再次校验连接状态。
                    db.expire_all()
                    server, _ = resolve_tool(db, class_id, ref)
                    async with MCPClient(server.base_url) as client:
                        result = await client.rpc("tools/call", {"name": schema["name"], "arguments": arguments})
                    content = result.get("content")
                    if not isinstance(content, list):
                        raise MCPFailure("MCP 工具响应 content 无效")
                    text = "\n".join(c["text"] for c in content if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str))[:12000]
                    if result.get("isError") or not text:
                        outcome = "error"
                        text = text or "工具没有返回文本结果"
                except MCPNeedsInput as exc:
                    window = weather_window(question)
                    metadata.append({"tool_ref": ref, "status": "needs_input", "skill": parsed["name"], "summary": str(exc), "weather_context": {**window, "location": None}})
                    results.append({"tool_ref": ref, "status": "needs_input", "text": str(exc)})
                    continue  # 没有执行远端调用，不记为失败或成功审计。
                except (MCPFailure, HTTPException) as exc:
                    outcome, text = "denied" if isinstance(exc, MCPDenied) else "error", exc.detail if isinstance(exc, HTTPException) else str(exc)
            text = redact(text)
            elapsed = int((time.monotonic() - started) * 1000)
            item = {"tool_ref": ref, "status": outcome, "skill": parsed["name"], "duration_ms": elapsed, "summary": text[:300]}
            if ref.startswith("weather_query@") and arguments is not None:
                item["weather_context"] = arguments
            metadata.append(item)
            results.append({"tool_ref": ref, "status": outcome, "text": text})
            db.add(ToolCallAudit(class_id=class_id, user_id=user_id, conversation_id=conversation_id, skill_id=skill.id, tool_ref=ref, status=outcome, duration_ms=elapsed, summary=text[:1000]))
            db.commit()
    return metadata, results, instructions
