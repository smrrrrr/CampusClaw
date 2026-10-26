"""第 6 课 HTTP 管理/技能/会话/审计用例，复用独立数据库真实 MCP 测试环境。

不依赖既有学生密码、固定数据库 ID、DeepSeek 密钥或真实天气供应商。
MCP tools/call 经过真实 localhost HTTP；主应用通过 FastAPI TestClient 请求。
"""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "backend" / "tests"))
workflow = importlib.import_module("test_mcp_integration")


class TestMCPWorkflow(workflow.MCPIntegrationTests):
    """登记/连接/发现、非法权限、技能绑定、真实调用、落库与断开拒绝。"""
