## Context

CampusClaw 已实现班级知识库检索（`rag_search_service.retrieve_top_k`）与溯源（`citations`/`best_snippet`）、材料上传入库（`is_indexed`）、JWT 双 Token + 班级数据隔离（`require_student_class_id` / JWT `class_id`）。当前 AI 解题助手（`routers/student.py` 的 `ask_ai`）是**单次提问、无状态**：返回一次性 `answer + citations`，系统提示词硬编码在 `llm_service.SYSTEM_PROMPT`，无法按班配置，也无多轮上下文与流式。本项目为单机 SQLite + FastAPI + Next.js + Docker，无 Redis、无队列，短信为 Mock。本设计为 `agent-assistant` 规约中的行为提供实现方案。

## Goals / Non-Goals

**Goals:**

- 教师按班级配置 AI 助手的系统提示词与「解题引导」技能开关
- 学生新建/列出/读取/删除会话，并在会话内连续追问（历史作文上下文）
- 学生提问以 SSE 流式逐字返回，流式结束把消息写回会话
- 复用既有检索/溯源/每日限次/班级隔离，不破坏 `ask_ai` 既有行为

**Non-Goals:**

- 不改变 RAG 检索算法（`retrieve_top_k` 分块/向量/混合检索保持不变）
- 不引入消息队列、WebSocket 或外部会话存储（SSE 即可满足逐字输出）
- 不实现跨班会话或多用户协作
- 不实现流式中断后的断点续传（客户端重连时以已持久化的历史为准）

## Decisions

### 1. 配置模型：AgentConfig（班级级，非教师级）

新增 `agent_configs` 表，`class_id` 唯一，字段：`system_prompt`（可空，空则回退默认）、`tutor_enabled`（bool，默认 true）、`teacher_id`、`updated_at`。

- **按 class_id 而非按 teacher_id**：学生的助手由"所在班级"决定，班级与助手一一对应更贴合"教师为所教班级配置"的语义，也便于学生侧按 `class_id` 直接取配置，避免"多老师同班取谁的"歧义。
- 教师保存/读取时用 `require_teacher_classes` + `class_id ∈ teaching_classes` 双重校验，越权 403。
- 提示词解析在 `llm_service.resolve_system_prompt(config)`：`base = 自定义或默认`；`tutor_enabled` 时 `base += TUTOR_SKILL_PROMPT`。

**替代方案**：按 `teacher_id` 单份全局配置。**未选原因**：多班共用同一提示词无法满足"按班引导"，且学生侧需要反查班级所属教师，逻辑更绕；按班最直白。

### 2. 「解题引导」技能：提示词拼接而非独立分支

技能以一段固定文案 `TUTOR_SKILL_PROMPT`（"只给思路引导、不直接给最终答案"）在系统提示词末尾拼接实现，由 `AgentConfig.tutor_enabled` 控制。开启/关闭不改变调用流程与大模型接口。

- **理由**：无需在后端额外做"解释器分支"，交给大模型按提示词约束输出即可，实现轻量、可自然回退（教师关掉即恢复默认引导风格）。
- 技能文案由教师配置界面从 `GET /api/teacher/agent-config/default-prompt` 拉取预览。

### 3. 会话模型：Conversation + Message

- `conversations`：`id, student_id, class_id, title, created_at, updated_at`；`(student_id, class_id)` 隔离检索。
- `messages`：`id, conversation_id(FK CASCADE), role(user/assistant), content, sources(JSON), created_at`。
- 隔离校验集中在 `_coerce_conversation`：会话必须属于当前学生（否则 404）且 `class_id` === JWT `class_id`（否则 403）。
- SQLite 未开外键级联：删除会话先 `DELETE messages` 再 `DELETE conversations`。

### 4. 多轮上下文

`chat` 端点读取会话历史（时间正序），取最近 `CHAT_HISTORY_TURNS * 2` 条（默认 6 轮）`(role, content)`，与新问题一起经 `build_chat_messages` 构造 messages 数组：`system` + 历史轮次 + 当前检索上下文 user 消息。检索上下文块（带 `[n]` 编号）只追加到当前 user 消息前，历史轮次不带检索块（避免上下文膨胀）。

### 5. SSE 流式

- `llm_service.stream_chat(messages)`：`httpx.AsyncClient.stream("POST", ..., stream=True)` 逐行解析 `data:` 累加 delta 并 `yield`；非 2xx 或网络错误抛 `LLMGenerationError`。
- `chat` 端点返回 `StreamingResponse`，SSE 事件 JSON：`{"type":"delta","content"}`、`{"type":"done","answer","citations","remaining"}`、`{"type":"error","message"}`。
- 降级路径：无命中 → 直接 yield done 文案；有命中但 DeepSeek 失败/无 Key → yield error（内容为检索段落展示）。`finally` 用独立 `SessionLocal` 写回 assistant 消息与更新 `AIQuestionLog.answer`。
- Nginx `/api/` 需 `proxy_buffering off` + `proxy_http_version 1.1` + `proxy_set_header Connection ""`，防止流式被缓冲/长连接断。

### 6. 前端

- `api.ts`：新增 `getAgentConfig/saveAgentConfig/getAgentDefaultPrompt`、`createConversation/listConversations/getConversationMessages/deleteConversation`，及基于 `fetch + ReadableStream` 的 `streamChat(cid, q, {onDelta,onDone,onError})`（自动刷新 token、按 `\n\n` 分帧解析 SSE）。
- 学生端 `student/page.tsx`：改为"左侧会话列表 + 右侧消息线程"布局；发送时乐观插入 user 消息，流式 delta 追加到当前 assistant 占位，`onDone` 落盘到消息态并刷新会话列表；`onError` 保留已吐出部分。切换子女（`currentStudent?.id` 变化）时按新班级重载会话并清空消息。
- 教师端 `teacher/page.tsx`：按选中班级加载配置，提供提示词 textarea（可"填入默认/清空"）与技能开关 checkbox，保存调用 `saveAgentConfig`，展示技能文案预览。

## Risks / Trade-offs

- **[多轮上下文可能超长]** → 限制只带最近若干轮；如需更强可对历史做截断/摘要（留作优化项）。
- **[SSE 经 Nginx 被缓冲导致不逐字]** → 已关闭 `/api/` 缓冲并加长 `proxy_read_timeout`；仍异常时降级为一次性 JSON 不影响正确性。
- **[DeepSeek 流式中途失败丢已输出]** → `onError` 保留已吐出部分作为答案并在写回时补"AI 生成中断"；`finally` 兜底持久化，保证上下文不断链。
- **[历史与检索上下文同塞 prompt 增大 token]** → 历史仅存 user/assistant 文本、不携带各自检索块，控制体积。
- **[客户端中途断开导致消息未写回]** → 服务端 `finally` 仍写回（已吐出部分），下次打开会话见完整历史。

## Migration Plan

- 新增 `agent_configs`、`conversations`、`messages` 三表，`Base.metadata.create_all` 启动时自动建表，无破坏性变更。
- 存量 `ask_ai` / `ai-history` 端点与新会话流程并存；两者共用 `AIQuestionLog` 每日限次。
- 无需数据回填；教师首次进配置页读到默认空配置（回退默认提示词）。

## Open Questions

- 是否统一废弃旧的单次 `ask_ai` / `ai-history` 界面，只保留多轮会话？（当前为兼容并存，后续可按需收敛。）
- 是否需要给会话支持重命名、固定（pin）或按时间分组？（当前仅最近 50 条倒序、标题取自首条问题。）
- 「解题引导」是否需要在技能开启时也约束"参考文献作答"的答案展示（而非只约束引导语气）？（当前由提示词文案统一约束。）