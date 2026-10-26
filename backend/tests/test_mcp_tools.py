"""MCP 协议、数学工具与天气供应商边界；仅使用固定测试令牌。"""
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

MCP_ROOT = Path(__file__).resolve().parents[2] / "mcp-server"
sys.path.insert(0, str(MCP_ROOT))
import tools as mcp_tools

spec = importlib.util.spec_from_file_location("campus_mcp_app", MCP_ROOT / "main.py")
mcp_app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp_app)


class MCPProtocolTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"MCP_AUTH_TOKEN": "test-only-token"})
        self.env.start()
        self.client = TestClient(mcp_app.app)
        self.headers = {"Authorization": "Bearer test-only-token"}

    def tearDown(self):
        self.client.close()
        self.env.stop()

    def rpc(self, method, params=None):
        return self.client.post("/mcp", headers=self.headers, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})

    def test_health_and_bearer_fail_closed(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        for headers in ({}, {"Authorization": "Bearer wrong"}):
            self.assertEqual(self.client.post("/mcp", headers=headers, json={}).status_code, 401)
        with patch.dict(os.environ, {"MCP_AUTH_TOKEN": ""}):
            self.assertEqual(self.rpc("tools/list").status_code, 401)

    def test_initialize_discover_call_and_notifications(self):
        initialized = self.rpc("initialize", {"protocolVersion": "2025-06-18", "clientInfo": {"name": "test", "version": "1"}, "capabilities": {}}).json()
        self.assertEqual(initialized["result"]["protocolVersion"], "2025-06-18")
        notification = self.client.post("/mcp", headers=self.headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual(notification.status_code, 202)
        tools = self.rpc("tools/list").json()["result"]["tools"]
        self.assertEqual({t["name"] for t in tools}, {"formula_hint", "unit_convert", "weather_query"})
        result = self.rpc("tools/call", {"name": "formula_hint", "arguments": {"topic": "速度公式"}}).json()["result"]
        self.assertFalse(result["isError"])
        self.assertIn("v=s/t", result["content"][0]["text"])

    def test_invalid_protocol_and_origin(self):
        malformed = self.client.post("/mcp", headers=self.headers, content="{").json()
        self.assertEqual(malformed["error"]["code"], -32700)
        self.assertEqual(self.rpc("does-not-exist").json()["error"]["code"], -32601)
        self.assertEqual(self.rpc("tools/call", {"name": "missing"}).json()["error"]["code"], -32602)
        self.assertTrue(self.rpc("tools/call", {"name": "unit_convert", "arguments": {}}).json()["result"]["isError"])
        self.assertEqual(self.client.post("/mcp", headers={**self.headers, "Origin": "https://untrusted.example"}, json={}).status_code, 403)


class CalculationTests(unittest.TestCase):
    def convert(self, value, source, target):
        return mcp_tools.unit_convert(mcp_tools.ConvertArgs(value=value, from_unit=source, to_unit=target))

    def test_scale_offset_and_aliases(self):
        self.assertIn("1000 m", self.convert(1, "km", "m"))
        self.assertIn("32 °F", self.convert(0, "摄氏度", "°F"))
        self.assertIn("0 ℃", self.convert(32, "°F", "℃"))
        self.assertIn("10 m/s", self.convert(36, "公里/小时", "m/s"))
        self.assertIn("10000 cm²", self.convert(1, "m²", "cm²"))

    def test_invalid_dimensions_values_and_absolute_zero(self):
        with self.assertRaises(ValueError): self.convert(1, "m", "kg")
        with self.assertRaises(ValueError): self.convert(-274, "c", "k")
        with self.assertRaises(ValueError): self.convert(float("nan"), "m", "cm")
        with self.assertRaises(ValueError): self.convert(1, "__import__('os')", "m")

    def test_unknown_formula_not_fabricated(self):
        result = mcp_tools.formula_hint(mcp_tools.FormulaArgs(topic="未知超级公式"))
        self.assertIn("未覆盖", result)


class WeatherTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        mcp_tools._weather_cache.clear()
        mcp_tools._geocoding_cache.clear()
        self.original = httpx.AsyncClient

    async def test_real_provider_shape_and_success_cache(self):
        requests = []
        def handler(request):
            requests.append(request)
            if "geocoding" in request.url.host:
                return httpx.Response(200, json={"results": [{"name": "上海", "admin1": "上海", "country": "中国", "latitude": 31.2, "longitude": 121.4}]})
            return httpx.Response(200, json={"timezone": "Asia/Shanghai", "current": {"time": "2026-10-21T12:00", "temperature_2m": 20}, "current_units": {"temperature_2m": "°C"}, "daily": {"time": ["2026-10-21", "2026-10-22"], "temperature_2m_max": [23, 24], "temperature_2m_min": [16, 17]}, "daily_units": {"temperature_2m_max": "°C"}})
        with patch.object(mcp_tools.httpx, "AsyncClient", side_effect=lambda **kw: self.original(transport=httpx.MockTransport(handler))):
            args = mcp_tools.WeatherArgs(location="上海", days=1, day_offset=1)
            result = json.loads(await mcp_tools.weather_query(args))
            self.assertEqual(result["forecast"][0]["time"], "2026-10-22")
            self.assertEqual(result["timezone"], "Asia/Shanghai")
            self.assertIn("Open-Meteo", result["source"])
            self.assertTrue(result["fetched_at"])
            await mcp_tools.weather_query(args)
            self.assertEqual(len(requests), 2)

    async def test_missing_city_and_network_errors(self):
        with patch.object(mcp_tools.httpx, "AsyncClient", side_effect=lambda **kw: self.original(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"results": []})))):
            with self.assertRaisesRegex(ValueError, "未找到"):
                await mcp_tools.weather_query(mcp_tools.WeatherArgs(location="不存在城市"))
        def fail(request): raise httpx.ConnectError("private-error-details", request=request)
        with patch.object(mcp_tools.httpx, "AsyncClient", side_effect=lambda **kw: self.original(transport=httpx.MockTransport(fail))):
            with self.assertRaisesRegex(ValueError, "天气服务暂不可用"):
                await mcp_tools.weather_query(mcp_tools.WeatherArgs(location="上海"))
        with self.assertRaises(ValueError): mcp_tools.WeatherArgs(location="上海", days=7, day_offset=1)

    async def test_district_is_filtered_by_parent_city(self):
        queries, forecast_coords = [], []
        def handler(request):
            if "geocoding" in request.url.host:
                name = request.url.params["name"]
                queries.append(name)
                if name != "大兴": return httpx.Response(200, json={"results": []})
                return httpx.Response(200, json={"results": [
                    {"id": 1, "name": "大兴", "admin1": "云南", "admin2": "丽江市", "latitude": 27.2, "longitude": 100.8},
                    {"id": 2, "name": "大兴", "admin1": "北京市", "admin2": "北京市", "latitude": 39.74025, "longitude": 116.32693},
                ]})
            forecast_coords.append(request.url.params["latitude"])
            return httpx.Response(200, json={"timezone": "Asia/Shanghai", "daily": {"time": ["2026-10-21"], "temperature_2m_max": [20], "temperature_2m_min": [10]}})
        with patch.object(mcp_tools.httpx, "AsyncClient", side_effect=lambda **kw: self.original(transport=httpx.MockTransport(handler))):
            result = json.loads(await mcp_tools.weather_query(mcp_tools.WeatherArgs(location="北京市大兴区")))
        self.assertEqual(queries, ["北京市大兴区", "大兴"])
        self.assertEqual(forecast_coords, ["39.74025"])
        self.assertEqual(result["location"]["requested"], "北京市大兴区")
        self.assertEqual(result["location"]["name"], "大兴")

    async def test_ambiguous_district_requires_parent_instead_of_guessing(self):
        def handler(request):
            self.assertIn("geocoding", request.url.host)
            return httpx.Response(200, json={"results": [
                {"id": 1, "name": "大兴", "admin1": "北京市", "latitude": 39.7, "longitude": 116.3},
                {"id": 2, "name": "大兴", "admin1": "云南", "latitude": 27.2, "longitude": 100.8},
            ]})
        with patch.object(mcp_tools.httpx, "AsyncClient", side_effect=lambda **kw: self.original(transport=httpx.MockTransport(handler))):
            with self.assertRaisesRegex(ValueError, "多个同名"):
                await mcp_tools.weather_query(mcp_tools.WeatherArgs(location="大兴区"))
