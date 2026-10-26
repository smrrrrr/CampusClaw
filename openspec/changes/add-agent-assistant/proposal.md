## Why

CampusClaw 已有的 AI 解题助手（`add-rag-search`）已具备"班级知识库检索 + 溯源"能力，但仍是**单次提问、无状态**：`ask_ai` 每次只回答一个问题，系统提示词（`llm_service.SYSTEM_PROMPT`）硬编码、教师无法按班差异化配置，回答一次性返回、无流式，且不保存追问前后的多轮上下文。教师无法引导学生"先想思路"，学生也无法在同一个话题上连续追问。本变更为系统引入**可配置的解题助手智能体（对话式 agent）**：提示词按班可配、内置「解题引导」技能、支持多轮会话（按会话保存上下文）、SSE 流式返回，从而把"登录鉴权 + 班级知识库检索"拼装为可连续对话的解题助手。

## What Changes

- 引入**可配置提示词**：新增班级级 `AgentConfig`（class_id 唯一），教师可自定义系统提示词；留空回退到内置默认提示词。
- 引入**「解题引导」技能开关**：教师按班开启/关闭；开启后 AI 只给思路引导、不直接给最终答案，引导学生自己算出（技能文案可随配置预览）。
- 引入**多轮会话**：新增 `Conversation`（按学生+班级隔离）与 `Message`（user/assistant，assistant 携带溯源 `sources`）；同一会话内连续追问，历史作为上下文带入。
- 引入 **SSE 流式返回**：学生提问后逐字流式渲染回答；流式结束后把 user/assistant 消息写回会话，保证上下文可续。
- 引入**会话管理接口**：学生可新建/列出/读取/删除会话（删除同步清空消息）；切换子女（class_id 变化）时按班级隔离重新加载。
- 兼容既有约束：每日 20 次限制复用 `AIQuestionLog` 计数；检索仍走 `retrieve_top_k` 限定班级；越权/超限返回 403/429 并记审计。

## Capabilities

### New Capabilities

- `agent-assistant`: 可配置、带「解题引导」技能、支持多轮会话与 SSE 流式输出的 AI 解题助手。

## Impact

- **后端 (FastAPI)**：新增 `AgentConfig`/`Conversation`/`Message` 三表；`llm_service` 改为提示词可配置（自定义 + 技能拼接）并新增 `stream_chat` SSE 流式；教师端新增配置保存/读取接口；学生端新增会话管理 + 流式提问接口。
- **数据库 (SQLite)**：新增 `agent_configs`（class_id 唯一）、`conversations`（student_id + class_id）、`messages`（conversation_id CASCADE）；SQLite 未启用外键级联，删除会话时需先清空消息。
- **前端 (Next.js)**：`api.ts` 新增配置/会话/流式接口与 `streamChat` SSE 客户端；学生端改造为"会话列表 + 消息线程"布局并流式渲染；教师端新增按班提示词与技能配置界面。
- **部署 (Nginx)**：`/api/` 关闭响应缓冲（`proxy_buffering off`）以支持 SSE 长连接流式。
- **约束**：无外部队列/外部状态新增；仍基于 FastAPI BackgroundTasks + SQLite；AI 提问计数仍按自然日 20 次。

_备注：这是课程第 5 次课个人作业"解题助手智能体（提示词可配置 + 解题引导技能 + 多轮会话 + SSE 流式）"的实现变更。_