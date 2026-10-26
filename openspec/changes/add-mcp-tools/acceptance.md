# 第 6 课验收记录

验收日期：2026-10-21（Asia/Shanghai）。环境：当前仓库的 Docker Compose，统一入口 `http://localhost:8080`。真实令牌不记录在此文件。

## 运行结果

| 清单项 | 证据与结果 |
| --- | --- |
| 同仓独立 MCP | `mcp-server/`，Compose 新增 mcp-server 服务，仅内网 8090 |
| 健康与认证 | 容器内 GET /health → 200；无 Bearer POST /mcp → 401 |
| 初始化、发现 | 后端 MCPClient 真实 initialize → initialized → tools/list，返回三个工具 |
| 公式工具 | `formula_hint(topic=速度公式)` 返回 v=s/t、条件、单位和引导步骤 |
| 单位换算 | 0 c → 32 f；学生问题 1 km 转成 m → 1000 m |
| 天气工具 | 真实 Open-Meteo 查询上海，返回 2026-10-21/22 预报、Asia/Shanghai、数据时间与来源；非 fixture |
| 教师页面 | 一年级1班（class_id=101）登记 campus-tools，连接后可见三个工具及 schema |
| 技能文件 | 教师页面保存公式提示、单位换算、天气查询三个启用技能 |
| 学生会话 | 课程验收会话 id=4，unit_convert 与 weather_query 真实调用状态均为 ok；SSE done 及历史保留 tool_calls |
| 工具审计 | 教师页面可见工具引用、用户、会话、耗时、时间和状态；验收用户 id=2 |
| 断开拒绝 | 在教师页面断开，发现缓存消失；同会话再次单位换算得到 denied，审计落库，随后已恢复连接 |
| Swagger | 浏览器成功打开 /api/docs，显示 MCP 管理、connect、tools、技能保存与审计及 Bearer 授权入口 |
| 班级与角色 | 独立数据库 HTTP 集成覆盖学生管理接口 403、跨班资源/会话 404、未认证 401 |
| 密钥 | 根/后端 .env 被 Git 忽略；同一随机 MCP_AUTH_TOKEN 注入服务端；API 只返回 token_configured，镜像不复制 .env |

## 自动化验证

- 在 `backend` 目录执行 `.venv/Scripts/python.exe -m unittest discover -s tests -v`：22 项通过（含既有认证回归、区县消歧、多轮补参）。
- `npm.cmd test`：8 项通过，含跨 UTF-8 分块的 SSE meta/done 元数据及实际 Markdown/KaTeX 渲染验证。
- `npm.cmd run build` 及 Docker 前端构建：通过，新页面 `/teacher/mcp` 成功生成。
- `backend/.venv/Scripts/python.exe apitest/run_all.py --mcp-only`：7 项 HTTP 链路用例通过；报告 `apitest/reports/report.html` 已生成且被 Git 忽略。
- `openspec.cmd validate add-mcp-tools --strict`：通过。CLI 同时提示未归档前置 `add-agent-assistant` 尚未生成基准 spec；归档时须先归档前置变更。本次保留该变更现状。

## 边界

天气依赖供应商网络，失败时明确 error；公式库范围和支持单位以工具 schema/实现为准。MCP 客户端只实现所声明的 JSON HTTP 子集。自动化天气测试使用明确的 MockTransport fixture，独立于上述真实天气查询。原有全量 apitest 依赖固定外部种子数据，本次以 `--mcp-only` 执行新增课程用例，不宣称原有全量套件已通过。

## 区县、多轮天气与公式显示回归

已在同日重新构建并启动当前 Compose。班级 102、小红用户 3 的新会话 6 使用真实上游执行：

1. “今天的天气怎么样” → needs_input，询问地点；无远端调用审计。
2. “北京市大兴区” → ok，匹配大兴/北京市/中国，经纬度 39.74025、116.32693；使用该坐标预报，不回退北京市中心。
3. “那明天呢” → ok，保留大兴区，day_offset=1，预报日期 2026-10-22；历史消息保留 weather_context。
4. 审计表仅新增两条实际调用，状态均为 ok；回答使用普通 °C、%、km/h，无 LaTeX 源码和资料缺失说明。

浏览器以本地模拟短信流程登录现有小红账号，打开同一会话验证历史显示，并补充自然问法“我在北京市大兴区，今天要带伞吗”。数学渲染回归复现 KaTeX 0.16.11 的“空格后接上标”错误，升级至 0.16.32 后带空格温度、分式、向量公式的实际渲染均无 katex-error；代码示例保持原文。
