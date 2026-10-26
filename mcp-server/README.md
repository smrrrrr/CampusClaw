# 第 6 课：MCP 与工具接入

工具：`formula_hint`（数学/物理公式提示）、`unit_convert`（含温度的单位换算）、`weather_query`（Open-Meteo 城市天气与未来七天预报）。采用 MCP 2025-06-18 无状态 JSON HTTP 子集，不实现资源、提示词和服务端事件订阅。

## 部署

在仓库根目录运行：

```powershell
python scripts/configure_mcp.py
docker compose up -d --build
docker compose exec -T nginx nginx -s reload
```

配置脚本生成随机令牌（已有则复用），只写入 Git 忽略的根目录 `.env` 和 `backend/.env`，不打印值。Compose 把同一 `MCP_AUTH_TOKEN` 注入后端与 MCP 服务；镜像不含环境文件。请勿提交/截图真实令牌。MCP 容器仅内网开放 8090，HTTP 调用失败不会向前端回显 Authorization。

进入 `http://localhost:8080/teacher/mcp`，选择任教班级：

1. 登记 `campus-tools`，Base URL 填 `http://mcp-server:8090`。
2. 点击「连接并发现工具」，应出现三个工具及参数 schema。
3. 点击三个技能模板，分别保存，或复制 examples/ 中的技能正文。技能引用的服务器名须与登记名称相同。
4. 切换学生账号，提问「速度公式是什么」「1 km 转成 m」「上海明天天气怎么样」。学生所属班级必须与技能所属班级一致。
5. 学生消息上显示 `tool@server · 成功/失败/已拒绝`；教师页面「本班调用审计」可刷新查看用户、会话、状态、耗时与时间。
6. 断开服务器后再次提问：元数据与审计应为 `denied`；新的对应技能保存被拒绝。原有 RAG 与流式回答仍可继续。

无需真实 DeepSeek Key 也能展示确定性公式/换算及成功天气工具文本。天气上游断网或城市无结果会明确显示失败，不会生成假的天气。支持常见中文城市名映射，其余城市由 Open-Meteo 地名编码匹配；返回中提供实际匹配地点，请注意同名城市。

`ENABLE_DOCS=true` 时，浏览器访问 `http://localhost:8080/api/docs`，用现有应用 Access Token 的 Bearer 鉴权试调 MCP 登记、connect、tools、技能保存、审计；MCP 服务令牌不应输入该 Swagger。生产可在根目录 `.env` 设置 `ENABLE_DOCS=false` 后重建后端。

## 本地开发

```powershell
# 终端一，在仓库根目录启动独立 MCP 服务
backend/.venv/Scripts/python.exe -m uvicorn main:app --app-dir mcp-server --env-file .env --host 127.0.0.1 --port 8090
# 终端二，按主 README 启动 backend 和 frontend
```

本地教师登记 `http://127.0.0.1:8090`，后端 `MCP_ALLOWED_BASE_URLS` 需包含该地址。Compose 仅允许 `http://mcp-server:8090`；添加其他服务时必须由服务端维护允许清单，不允许学生/模型指定 URL。

## 测试和报告

```powershell
cd backend
.venv/Scripts/python.exe -m unittest discover -s tests -v
cd ../frontend
npm.cmd test
npm.cmd run build
cd ..
backend/.venv/Scripts/python.exe apitest/run_all.py --mcp-only
```

接口测试使用独立内存数据库、临时 HTTP MCP 服务和固定测试令牌，不修改开发数据，不调用真实模型。天气单测使用明确标记的供应商响应 fixture；最终部署验收另外进行真实天气查询。HTML 报告位于 `apitest/reports/report.html`，已被 Git 忽略。默认不带 `--mcp-only` 仍运行原有全部接口用例；这些旧用例需要其指定的外部测试服务与种子数据。

## 协议与数据参考

- [MCP HTTP transport](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
- [MCP lifecycle](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle)
- [MCP tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
- [Open-Meteo forecast](https://open-meteo.com/en/docs)、[geocoding](https://open-meteo.com/en/docs/geocoding-api)
