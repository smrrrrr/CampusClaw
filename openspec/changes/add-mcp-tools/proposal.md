## Why

第 6 课要求将第 5 课的解题助手接入真实远端 MCP 工具。目前只有提示词式解题引导开关，没有 MCP 服务登记、发现、技能文件、工具调用和调用审计。用户已选定「公式提示 + 单位换算 + 查询天气」。

## What Changes

- 同仓新增 `mcp-server/`，通过 Compose 启动，以 Bearer 保护 `/mcp`，提供公式提示 `formula_hint`、单位换算 `unit_convert` 和天气查询 `weather_query` 三个只读工具。
- 教师按班登记、连接、发现、断开 MCP 服务；连接初始化后缓存工具；断开清空缓存，已有技能随后调用明确 denied。
- 新增 Markdown 技能文件管理，支持 `[名称]`、`[触发词]`、`[工具]`、`[指令]`；工具引用包含内置 `knowledge_search` 与 `工具名@服务器名`。
- 对话命中技能后在服务端校验班级、连接和发现缓存，真实调用远端工具，将结果作为不可信数据加入用户消息；SSE meta、最终消息和审计记录调用状态。
- 提供教师管理页面、Swagger、独立数据库自动化测试、apitest HTTP 用例和 HTML 报告。
- MCP 及会话资源的跨班/非本人访问统一返回 404；角色不符仍为 403，未认证为 401。保留已有 RAG、每日限额和流式主链路。

## Capabilities

### New Capabilities

- `mcp-server`: JSON-RPC MCP 服务及三个教学/生活工具。
- `mcp-management`: 班级级登记、连接、工具发现与断开。
- `skill-tool-binding`: 技能文件、触发匹配、工具绑定及运行时鉴权。
- `mcp-audit`: 调用元数据、审计、Swagger 和验收证据。

### Modified Capabilities

- `agent-assistant`: 工具辅助 SSE、多轮消息保存调用元数据，跨班会话统一 404。

## Impact

新增 MCP 服务容器，后端新增 MCPServer/AgentSkill/ToolCallAudit 表及 Message.tool_calls 列；前端新增工具与技能管理页面和学生调用状态。令牌由服务端环境变量读取，既不入库明文，也不在 API、前端或镜像中返回。天气查询需访问 Open-Meteo，不使用模拟天气作为成功结果。
