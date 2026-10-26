## 1. 数据模型

- [x] 1.1 在 models.py 新增 AgentConfig 表（id, class_id UNIQUE, teacher_id FK, system_prompt, tutor_enabled, updated_at）；新增 Conversation（id, student_id FK, class_id FK, title, created_at, updated_at + (student_id, class_id) 索引）；新增 Message（id, conversation_id FK CASCADE, role, content, sources JSON, created_at + conversation_id 索引），验证三表经 create_all 创建成功
- [x] 1.2 验证 SQLite 未启用外键级联时删除会话需先清空 messages 再删 conversations

## 2. LLM 服务：可配置提示词与流式

- [x] 2.1 llm_service 新增 resolve_system_prompt(config)：自定义提示词或默认 DEFAULT_SYSTEM_PROMPT，tutor_enabled 时追加 TUTOR_SKILL_PROMPT（「解题引导」只给思路）;原有 SYSTEM_PROMPT 保留为默认别名，generate_answer 兼容旧 ask_ai
- [x] 2.2 新增 build_chat_messages(system_prompt, history, question, context_block)：system + 最近历史轮次 + 当前检索上下文 user 消息
- [x] 2.3 新增 stream_chat(messages)（httpx.AsyncClient stream）：逐行解析 data delta 并 yield；非 2xx/网络错误抛 LLMGenerationError

## 3. 教师配置接口

- [x] 3.1 teacher.py 新增 GET /api/teacher/agent-config?class_id=（校验 class_id ∈ teaching_classes，回读配置或默认空/真）
- [x] 3.2 新增 PUT /api/teacher/agent-config（upsert AgentConfig，写老师编辑人；system_prompt 空则回退默认）
- [x] 3.3 新增 GET /api/teacher/agent-config/default-prompt 返回默认提示词与技能文案供界面预览

## 4. 学生多轮会话接口

- [x] 4.1 student.py 新增 POST /api/student/conversations（建会话，绑定 student_id + class_id，require_student_class_id）
- [x] 4.2 新增 GET /api/student/conversations（当前学生当前班级，按 updated_at 倒序 limit 50）
- [x] 4.3 新增 GET /api/student/conversations/{id}/messages（归属+班级校验，时间正序，assistant 解析 sources）
- [x] 4.4 新增 DELETE /api/student/conversations/{id}（清空 messages 再删会话，非本人 404）

## 5. 学生流式提问接口

- [x] 5.1 新增 POST /api/student/conversations/{id}/chat：校验会话归属/班级；check_ai_limit 复用 AIQuestionLog（超限 429+审计）；retrieve_top_k 检索本班上下文与 citations
- [x] 5.2 读取历史最近若干轮、resolve_system_prompt 按该班 AgentConfig 取提示词、build_chat_messages 组装
- [x] 5.3 返回 StreamingResponse：delta/done/error 三种 SSE 事件 JSON；无命中→done 降级文案；DeepSeek 失败/无 Key→error 展示检索段落
- [x] 5.4 finally 用独立 SessionLocal 写回 assistant 消息（含 sources）并更新 AIQuestionLog.answer、会话 updated_at；remaining = 20 - 当日计数

## 6. 前端 API 层

- [x] 6.1 api.ts 新增 getAgentConfig/saveAgentConfig/getAgentDefaultPrompt、createConversation/listConversations/getConversationMessages/deleteConversation 及对应类型
- [x] 6.2 新增 streamChat(cid, q, cb)：fetch+ReadableStream 解析 SSE，自动刷新 token，onDelta/onDone/onError 分发

## 7. 前端学生端多轮会话

- [x] 7.1 /student 改为「会话列表 + 消息线程」布局；切班级（currentStudent.id 变化）重载会话、清空消息
- [x] 7.2 发送时乐观插入 user 消息，流式 delta 追加到当前 assistant 占位，onDone 落盘并刷新会话列表与剩余次数；onError 保留已吐出部分
- [x] 7.3 每条 assistant 消息按 sources 渲染「参考资料」并支持「查看原文」；无 sources 不渲染资料卡

## 8. 前端教师端配置

- [x] 8.1 /teacher 新增「AI 助手配置」：按选中班级加载配置；提示词 textarea（可填默认/清空）+ 技能开关 + 技能文案预览 + 保存
- [x] 8.2 保存成功后提示"学生端下次提问将使用此提示词与技能设置"

## 9. 部署与集成验证

- [x] 9.1 Nginx /api/ 增设 proxy_http_version 1.1 + proxy_buffering off + proxy_cache off + proxy_set_header Connection ""，保证 SSE 流式
- [x] 9.2 后端 import/建表通过、前端 npm run build 通过
- [x] 9.3 端到端冒烟：学生建会话→流式降级→user+assistant 消息持久化→会话列表→删除会话后读取 404；教师配置端点在被学生 token 访问时 403（班级隔离/越权）