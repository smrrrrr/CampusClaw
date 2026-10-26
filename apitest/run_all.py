# -*- coding: utf-8 -*-
"""apitest 总入口：运行全部 HTTP 用例并生成 HTML 报告。

- 用例文件按 URL 目录组织，逐一收敛进 cases/**。
- BASE_URL 默认 http://localhost:8001（本地 dev 服务，ENABLE_DOCS=true）。
- 报告输出到 reports/report.html（已加入 .gitignore，不入库）。

用法：
    先启动本地 dev 服务，再运行本脚本：
      cd backend
      .venv\\Scripts\\python -m uvicorn main:app --host 127.0.0.1 --port 8001
      backend\\.venv\\Scripts\\python.exe apitest\\run_all.py
"""

import glob
import argparse
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)  # 使相对路径与 conftest 默认路径解析稳定

parser = argparse.ArgumentParser(description="HTTP 接口测试与 HTML 报告")
parser.add_argument("--mcp-only", action="store_true", help="只执行独立数据库的第 6 课 MCP HTTP 链路测试")
options = parser.parse_args()
case_root = os.path.join(HERE, "cases", "api", "mcp") if options.mcp_only else os.path.join(HERE, "cases")
cases = sorted(p for p in glob.glob(os.path.join(case_root, "**", "*.py"), recursive=True) if os.path.basename(p) != "__init__.py")
if not cases:
    print("未找到任何用例文件", file=sys.stderr)
    sys.exit(2)

report_dir = os.path.join(HERE, "reports")
os.makedirs(report_dir, exist_ok=True)
report_path = os.path.join(report_dir, "report.html")

# 显式传入用例路径（覆盖默认的 test_* 收集规则，XML/HTTP 用例名可含 POST/GET/PUT）
args = [
    *cases,
    "-v",
    "--tb=short",
    "-p",
    "no:cacheprovider",
    "-p",
    "no:randomly",
    f"--html={report_path}",
    "--self-contained-html",
]

print(f"运行 {len(cases)} 个用例文件，BASE_URL={os.environ.get('APITEST_BASE_URL', 'http://localhost:8001')}")
print(f"HTML 报告：{report_path}\n")

rc = pytest.main(args)
print(f"\n完成，退出码={rc}，报告见 {report_path}")
sys.exit(rc)
