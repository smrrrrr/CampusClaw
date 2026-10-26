## Context

技术栈为 FastAPI、SQLAlchemy/SQLite、Next.js 14、DeepSeek、SSE、Docker Compose。当前技能为 AgentConfig.tutor_enabled，需新增可编辑技能文件而非将已有开关视为完整技能系统。课程截图是本变更验收基线。

## Goals / Non-Goals

Goals：同仓可复现部署、真实 HTTP MCP 链路、三个工具、班级级技能及审计、失败降级可见、Swagger 可试调、端到端证据。

Non-Goals：任意公网 MCP 地址、写操作工具、复杂工作流、自动定位、历史天气、天气预警、完整 MCP 资源/提示词/订阅功能。

## Decisions

### 协议与部署

实现固定协议版本 `2025-06-18` 的无状态 HTTP JSON-RPC 子集，支持 initialize、notifications/initialized、tools/list、tools/call、ping。POST /mcp 返回 JSON；GET /mcp 返回 405，表示不提供服务端 SSE 订阅。MCP 端与应用对学生输出的 SSE 是不同链路。每次主机操作先初始化并通知 initialized；发现结果只在整个握手和 tools/list 成功后写缓存。JSON-RPC 错误与工具执行 isError 分开，禁止模拟远端成功。

MCP 容器名 `mcp-server`、内网端口 8090，主应用默认登记 `http://mcp-server:8090`。MCP_AUTH_TOKEN 从根目录 .env 注入两个容器；本地开发通过环境文件注入。镜像不 COPY .env。/health 仅暴露非敏感存活状态，/mcp 缺失/错误令牌均为 HTTP 401。校验 Origin，禁止重定向；管理接口 Base URL 只允许服务端明确配置的地址清单，避免教师提供地址导致内网探测或令牌泄露。

### 三个工具

- formula_hint：输入 topic，返回可核对的数学/物理公式、适用条件、引导步骤；先覆盖二次方程、勾股定理、速度、密度、牛顿第二定律、欧姆定律。不支持的主题明确说明，不生成公式。
- unit_convert：输入 value、from_unit、to_unit；支持长度、面积、体积、质量、时间、速度、温度，包含摄氏/华氏/开尔文偏移换算。禁止跨量纲换算、非有限数和绝对零度以下温度。不执行用户表达式。
- weather_query：输入 location、days(1..7)、day_offset(0..6)，总窗口不得超过 7 天。固定访问 Open-Meteo 地名编码与预报端点，输出匹配城市/地区/国家、时区、当前值的数据时间、预报日期、温度/降水/风及来源链接、抓取时间。无设备定位；未知城市、网络失败返回工具错误；天气是模型数据，不宣称气象站实时观测。缓存最多 128 项、5 分钟，仅缓存成功结果。

### 服务与密钥管理

MCPServer 按 class_id + name 唯一，包含 base_url、connected、tools_cache、更新时间。名称限定小写字母开头的字母数字连字符，工具名限定小写字母开头的字母数字下划线。教师只登记名称和地址；认证材料统一从 MCP_AUTH_TOKEN 读取，不接受学生提供令牌。响应只暴露 token_configured，不返回令牌、Authorization 或上游原始异常。连接失败清空连接与缓存，给出脱敏原因；断开立即使缓存与运行时调用无效。

### 技能与调度

技能文件存为数据库中的 Markdown 正文（保留原文，可复制导出），解析四个必需段落 `[名称]`、`[触发词]`、`[工具]`、`[指令]`。触发词以逗号分隔，匹配当前学生问题，最多命中 3 个技能、每轮最多调用 3 个不同工具。保存时所有 MCP 引用必须属于本班已连接服务的发现缓存，否则 400 拒绝；引用其他班服务器不可成功。工具断开后已有技能保留，但运行时重新校验并记录 denied，禁止只依赖保存时校验。

参数规划优先使用已知三个工具的明确参数解析；单位等无法直接解析时可由已配置的模型依据发现的 inputSchema 提取 JSON 参数，仍由远端 Pydantic 校验。规划仅传问题和该工具 schema，不接收模型自选 URL/工具名。天气使用专用自然表达解析，不依赖模型猜测缺失城市；支持下雨、带伞等意图。最近 6 条当前会话消息的 weather_context 保存地点与日期窗口，允许只补充地点或追问日期；无地点返回 needs_input，未执行调用就不写工具审计。不得跨会话、跨班复用，续接时仍校验连接。其他工具使用受控参数规划接口。

区县查询先尝试完整地名，再去行政后缀查本地名称，并用上级行政标签过滤候选；歧义报错、不回退到市中心。地名成功缓存 24 小时、最多 128 项，天气成功缓存 5 分钟。回答保留匹配区域与模型网格精度说明。

技能指令由教师编辑并按班应用，工具返回文本保持独立的数据块，只加入当前 user 消息；系统提示词明确外部数据不得覆盖系统/教师指令。现有 knowledge_search 复用本班 RAG，无需创建第二套知识库。

### 元数据、审计与降级

ToolCallAudit 保存 class_id、user_id、conversation_id、skill_id、tool_ref、status(ok/error/denied)、duration_ms、脱敏结果摘要、created_at；不存令牌。Message.tool_calls 通过轻量列迁移追加，旧消息默认空列表。SSE 先发 meta，再发 delta/done；done 与历史消息均携带 tool_calls，前端展示工具引用和状态。DeepSeek 不可用时仍展示成功工具文本及本班资料；工具超时/断开不能阻断已有回答流程。工具执行与连接均有超时、响应长度及调用次数上限。

仅天气结果直接按结构化事实格式化，不经过资料优先的大模型提示词；缺参和错误直接提示，成功结果保留日期、来源、抓取时间并采用 °C、%、km/h 普通文本。数学回答仍使用 Markdown/KaTeX；规范标准行内和块级定界符但保护代码，KaTeX 从 0.16.11 更新到 0.16.32，修复空格后接上标的官方已知问题（KaTeX #3878）。

### Swagger 与接口

教师接口统一 `/api/teacher/mcp-servers`、`/{id}/connect`、`/{id}/disconnect`、`/{id}/tools`、`/api/teacher/skills`、`/api/teacher/tool-audits`，class_id 均校验任教范围。新增 `/api/docs` 和 `/api/openapi.json`，复用 nginx /api 转发并由 ENABLE_DOCS 控制；课程开发 Compose 开启，可在环境中关闭。

## Risks / Trade-offs

- 天气上游不可用：明确 error 并保留 RAG/聊天；自动化测试用 MockTransport 固定数据，最终验收额外真实查询。
- 简单触发词不能替代完整智能体路由：教师可以修改触发词，界面显示技能命中与实际工具结果；不做静默猜测。
- 已有规范会话越权状态存在 403/404 混用：本次仅统一会话与新增 MCP 资源为 404；非教师操作仍 403。
- 首次部署令牌缺失：MCP 端 fail closed，教师页面明确提示未配置；提供生成令牌的部署说明，真实值不进入 Git/镜像/报告。

## Migration / Validation

新增表 create_all，Message 增列兼容旧数据。构建时导入应用检查依赖。先运行协议/算法/上游错误/权限测试，再跑独立数据库 HTTP 集成与现有登录回归，最后构建前端、Compose 部署、真实 MCP 发现调用和天气查询。run_all.py 生成忽略入库的 HTML 报告，并记录断开拒绝和审计结果。

OpenSpec 归档依赖：`add-agent-assistant` 仍为未归档前置变更，需先归档该变更生成基准 `agent-assistant` spec，再归档本变更的 MODIFIED delta；本次不擅自归档用户已有变更。

## References

- https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
- https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- https://open-meteo.com/en/docs
- https://open-meteo.com/en/docs/geocoding-api
