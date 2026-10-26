# CampusClaw 校园助手

Next.js 前端 + FastAPI 后端，SQLite 保存业务数据。需要 Python 3.12+、Node.js 20+。

第 6 课新增公式提示、单位换算和天气 MCP 工具；配置、技能示例、Swagger 与验收步骤见 [MCP 使用说明](mcp-server/README.md)。

## 本地安装

在项目根目录执行（Windows PowerShell）：

```powershell
python -m pip install uv
python -m uv sync --locked --inexact --project backend --cache-dir .uv-cache
cd frontend
npm.cmd ci
cd ..
```

保留已有的 `backend/.env`。新环境可复制 `backend/.env.example` 为 `backend/.env`，本地查看接口文档时设置 `ENABLE_DOCS=true`。AI 回答需要在该文件填写 `DEEPSEEK_API_KEY`；未配置时仍可使用登录、材料管理和检索。

分别在两个终端运行：

```powershell
# 终端一
cd backend
.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

```powershell
# 终端二
cd frontend
npm.cmd run dev -- --hostname 127.0.0.1
```

浏览器访问 http://localhost:3000，前端 `/api` 自动代理到后端 8000 端口。整个登录过程请使用同一个主机名，避免混用 `localhost` 与 `127.0.0.1` 导致 Cookie 不共享。

全新开发数据库可以在 `backend` 目录执行 `.venv\Scripts\python.exe dev_seed.py` 创建演示账号：教师 `TEA001 / Teach@2026`，学生 `20230001 / thu230001`（首次需要改密）。已有数据时请勿重复执行该脚本，它会重置演示学生的密码。

## 验证

```powershell
cd backend
.venv\Scripts\python.exe -m unittest discover -s tests -v
cd ../frontend
npm.cmd test
npm.cmd run build
```

会话回归测试使用独立内存数据库，不修改现有用户或材料。登录凭证仅存前端内存；刷新页面时用 HttpOnly Refresh Cookie 恢复完整会话，再运行路由守卫。无需把 Token 存入 localStorage。

## Docker

```powershell
python scripts/configure_mcp.py
docker compose up -d --build
# 重建应用容器后刷新 Nginx 缓存的上游地址
docker compose exec -T nginx nginx -s reload
```

访问 http://localhost:8080。根目录 `.env` 提供容器使用的 `DEEPSEEK_API_KEY`，`data/` 和 `backend/uploads/` 保存持久化数据。Docker 的数据库与默认本地开发数据库不同，部署时请确认使用的是预期数据。

配置脚本会生成或复用 MCP 令牌和 Docker JWT 签名密钥，并保存在被 Git 忽略的环境文件中，不显示密钥内容。旧的全量 `apitest` 还需通过环境变量 `APITEST_TEACHER_PASSWORD`、`APITEST_STUDENT_PASSWORD` 提供测试密码；账号可分别用 `APITEST_TEACHER_IDENTIFIER`、`APITEST_STUDENT_IDENTIFIER` 覆盖。测试账号与数据库必须匹配，不能使用生产账号运行会修改数据的接口测试。

## 学科应用、模板、技能上传和调用验证

学生首页可选择通用、数学、物理、英语助手。新对话绑定所选应用，历史会话保留原有学科；升级前的会话继续使用通用助手。教师侧新增：

- **学科应用与模板**（`/teacher/applications`）：每班内置三个学科应用，分别保存名称、提示词、解题引导开关，以及资料和技能绑定。新学科应用默认不绑定资料或技能，按学科勾选后保存；“使用本班全部”会包括后续新增项目，全部不勾选表示不使用该类资源。
- **解题引导优先**：开关开启时，教师自定义提示词被屏蔽，使用内置学科引导和苏格拉底式提问规则。关闭后才使用自定义提示词。技能指令也不得覆盖引导规则而要求直接给出整题答案。
- **提示词模板库**：支持查看三个内置模板，新建、编辑、删除本班自定义模板，并填入应用。模板应用后保存的是内容副本，编辑模板不会自动覆盖已保存的助手配置。
- **工具与技能**（`/teacher/mcp`）：上传 UTF-8 的 `.md` / `.txt` 文件，校验、预览、编辑后保存，再到学科应用绑定。最大 48KB / 12000 字符；必须有 `[名称]`、`[触发词]`、`[工具]`、`[指令]` 四个段落，纯指导技能的 `[工具]` 可以留空。示例见 `mcp-server/examples/{math,physics,english}-guidance.md`。绑定 MCP 工具时仍须先连接并发现该工具。
- **调用验证**（`/teacher/invocations`）：按班级、会话和追踪编号查看实际出站请求及返回，分页浏览并导出脱敏 JSON。单次提问内的参数规划、MCP 初始化/调用、模型生成共享追踪编号；重试分开记录。无 Key 或天气直接格式化时记录 `llm_skipped`，不伪造模型调用。

记录保存实际模型 `model/messages/temperature/stream` 等参数；参数规划路径额外保存 `tools/tool_choice`，流式响应保存 SSE data 帧、拼接文本和完成状态。上下文记录知识引用、历史条数、技能指令截断长度和自定义提示词是否被屏蔽。认证头不落库，已配置密钥、手机号和邮箱会脱敏。记录只允许任教本班的教师读取，从启用此功能后开始积累，不能还原升级前的请求。导出上限为 2000 条，更多记录需按会话或追踪编号筛选。

重启后端时会自动新增表及 `conversations.application_id` 列，不重置已有用户、资料或会话。Docker 使用者重新执行 `docker compose up -d --build` 和 Nginx reload 后才能看到新功能。

自动化回归使用内存数据库、本机 MCP 服务和明确的模型 HTTP fixture；模型 fixture 验证请求拼接及审计，不代表真实模型的教学效果验收。真实演示时配置模型 Key，使用三个学科应用实际提问后，在“调用验证”导出对应 JSON，作为作业报告的证据。
