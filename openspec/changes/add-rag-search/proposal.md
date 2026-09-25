## Why

CampusClaw 的 AI 解题助手当前仅把本班 `is_indexed=true` 的材料**整份纯文本拼接**后直接塞给大模型作为上下文（见 `material_service.get_indexed_contexts`），没有分块、没有相似度检索、没有按相关片段召回、也没有内容溯源。材料一多，上下文会超限且不精准，学生也无法知道回答引用了哪份资料的哪一段。本变更为系统引入**限定班级范围的知识库检索（RAG）+ 内容溯源**规约，让 AI 回答仅基于与本班问题最相关的资料片段，并标注引用来源。

## What Changes

- 引入**文本分块（chunking）**：上传材料解析为纯文本后，按固定长度 + 重叠（overlap）切分为带序号的块，取代"整份拼接"。
- 引入**向量化存储**：每个文本块生成 embedding 向量，连同所属 class_id、material_id、块序号持久化（SQLite + sqlite-vec 扩展，或本地 FAISS/Chroma）。
- 引入**限定班级的相似度检索**：学生提问时，将问题向量化，仅在本班（class_id）分块集合内按向量相似度召回 Top-K 个相关块，作为大模型上下文。
- 引入**内容溯源**：AI 回答携带引用信息（material_id、filename、块序号、原文摘要），前端展示"参考了哪份资料"。
- 引入**检索失效降级**：默认使用内置本地 embedding（避免外部 API 依赖与费用）；当某班无可检索分块时，返回"暂无相关班级资料"，不生成无依据回答。
- 兼容既有隔离：检索严格受 JWT class_id / teaching_classes 约束，越权返回 403 并记审计日志。

## Capabilities

### New Capabilities

- `rag-search`: 限定班级范围的知识库检索与内容溯源，覆盖文本分块、向量化存储、限定班级的相似度召回、AI 检索上下文注入、答案引用溯源、无相关分块时的降级处理，以及"上传材料解析后切分并向量化、全成功才置 is_indexed=true"的索引流程扩展。

## Impact

- **后端 (FastAPI)**：新增 `chunk_service`（分块）与 `embedding_service`（向量化）；`MaterialContent` 扩展或新增 `MaterialChunk` 表存向量；学生 AI 提问接口从"整份拼接上下文"改为"向量召回 Top-K 块 + 溯源引用"；异步解析任务改为生成分块和向量；检索严格按 class_id 过滤。
- **数据库 (SQLite)**：新增 `MaterialChunk` 表（id, material_id, class_id, chunk_index, content, embedding, created_at）与 (class_id, is_indexed) 隔离检索索引；启用 sqlite-vec 扩展（或选用 FAISS 向量文件）。
- **依赖**：新增向量化/检索库（根据设计决策在 sqlite-vec / FAISS / Chroma 间选择）。
- **前端 (Next.js)**：AI 解题助手回答区新增"参考资料"溯源展示（来源文件、页码/块）；无相关材料时空状态提示。
- **约束**：无外部队列新增，仍基于 FastAPI BackgroundTasks + SQLite；向量化默认本地模型避免外部费用。

_备注：这是课程第 4 次课个人作业"限定班级范围的知识库检索 + 内容溯源（可考虑向量数据库）"的实现变更。_