## Context

CampusClaw 已完成材料上传入库（add-material-upload）：上传后经 BackgroundTasks 把文件解析为整份纯文本，存于 `MaterialContent` 表，`is_indexed=true` 即被 `material_service.get_indexed_contexts(db, class_id, limit=10)` **整份拼接**返回给 AI 解题助手（`routers/student.py` 的 `ask_ai`）。当前无分块、无向量化、无相似度检索、无溯源。本项目为单机 SQLite + FastAPI + Next.js + Docker，无 Redis、无外部队列、短信为 Mock。本设计为 `rag-search` 规约中的行为提供实现方案。参见 proposal.md - Why。

## Goals / Non-Goals

**Goals:**

- 定义文本分块（长度 + 重叠）与块序号方案
- 定义分块向量的存储方式（贴合现有 SQLite）
- 定义限定班级（class_id）的 Top-K 相似度召回算法
- 定义 AI 上下文注入结构与答案溯源输出
- 定义无召回分块时的降级行为

**Non-Goals:**

- 不引入外部向量数据库服务（如 Pinecone/Weaviate），保持单机 SQLite 架构
- 不引入外部 embedding API 服务（避免费用与网络依赖），默认使用本地离散 embedding + 较轻量实现
- 不实现跨班检索或全局检索（严格按班级隔离）
- 不做重排（rerank）或多轮记忆检索
- 不引入对象存储或全文搜索引擎

## Decisions

### 1. 分块策略

使用固定长度 + 重叠的滑动窗口分块：`CHUNK_SIZE = 500` 字符，`OVERLAP = 100` 字符，按字符切分（对中文友好，避免按词切分的中文分词依赖）。边界尽量对齐段落或换行符；无自然边界时按字符硬切。

- 每块存 `chunk_index`（从 1 开始递增），同材料的块共享 `material_id` 与 `class_id`。
- 当前 `MaterialContent.content` 仍存整份文本以保留预览/校验；分块数据落到新表 `MaterialChunk`。

**替代方案**：按语义段落切分。**未选原因**：实现复杂、覆盖不全；定长+重叠简单可靠，配合溯源已满足课程作业要求。

### 2. 向量化与内容存储

新增 `MaterialChunk` 表：

```
id INTEGER PK
material_id INTEGER FK → Material (CASCADE)
class_id INTEGER NOT NULL   -- 冗余存储以支持按班隔离检索，避免跨表 join
chunk_index INTEGER NOT NULL
content TEXT NOT NULL
embedding BLOB NOT NULL     -- 向量稠密表示
created_at TIMESTAMP
```

- **向量来源（默认）**：本地无监督离散向量。采用「字符 n-gram 哈希向量」（char-level hashing vectorizer，维度约 512）：对分块文本做字符 bigram/trigram 哈希 + TF 加权，得到定长向量 `embedding`。零外部依赖、离线可用、对中文与拼写变体鲁棒，足以支撑"限定班级召回相关片段"，完全满足作业对"向量化 + 相似度检索"的验收。
- **可选增强**：若后期需要更高质量语义向量，可替换为本地 SBERT / sentence-transformers（如 `paraphrase-multilingual-MiniLM`），仅替换 `embedding_service` 内部实现，不动表结构与接口——此兼容性写入 `embedding_service` 的接口设计。

**替代方案 a**：`sqlite-vec` 扩展做原生 KNN 向量检索。**未选原因**：加载 C 扩展在 FastAPI/uv 环境与 Docker 镜像存在额外集成成本；数据量为班级级（数百块以内），全表欧氏距离 + 余弦排序在 Python 层即可满足性能。
**替代方案 b**：FAISS / Chroma 独立向量库。**未选原因**：引入额外运行时与持久化文件，与"单机 SQLite"约束相悖（项目硬性约束不引 Redis，同理避免额外状态存储）。

### 3. 限定班级的相似度召回

查询路径（`rag_search_service.retrieve_top_k`）：

1. 由 JWT 取 `class_id`（学生）或 `teaching_classes`（教师），**不信任前端参数**（复用 `require_student_class_id` / `check_class_id_consistency`）。
2. **跨章节标题预筛（轻量关键词层）**：先 `SELECT id, filename FROM material WHERE class_id = :cid AND is_indexed = true` 取候选材料，用 `_prefilter_materials`（字符二元组 bigram 重叠）过滤掉与问题无实质关键词共现、仅字面重叠的不同章节材料；若无保留则回退全保留（避免泛化标题材料导致空结果）。此层放在向量排序之前，弥补字符 n-gram 哈希向量对"字面重叠但章节不同"材料误排高分的问题。
3. 将用户问题文本做与分块相同的向量化，得到查询向量 `q`。
4. `SELECT id, material_id, class_id, chunk_index, content, embedding FROM material_chunk WHERE class_id = :class_id`（教师时 `class_id IN :teaching_classes`），并 `JOIN material ON material.is_indexed = true`，且 `material_id IN (预筛保留的材料)`。
5. 逐块计算余弦相似度 `sim = dot(q, e) / (|q|*|e|)`，按 `sim` 降序取 Top-K（默认 `K = 12`，`config.chunk_top_k`）。
6. 召回结果为 `[{material, filename, chunk_index, content, score}]`，供溯源与上下文注入。

隔离：查询层强制 `class_id` 过滤（对齐项目硬性约束"查询层强制 class_id 过滤作为最终防御"）。

### 4. AI 上下文注入与溯源

- 把召回块按 score 降序拼接为上下文块，附带引用编号 `[1..K]` 与来源（material 标题、chunk_index）。
- Prompt 要求大模型回答时对依据标注 `[编号]`，仅当答案能由某块支撑时才标该引用；不支持则不标。
- 响应结构扩展 `answer + citations:[{material_id, filename, chunk_index, text(excerpt), score}]`。
- 前端 AI 解题助手回答区新增「参考资料」面板，点击可跳转到对应材料预览。

### 5. 索引流程改造

`material_service.run_indexing` 在解析出整份纯文本后，追加两步（仍为 BackgroundTasks 异步，失败不影响上传）：

1. 文本分块 → 写入 `MaterialChunk`（含 `class_id`）
2. 每块向量化 → 写 `embedding` 列

任一步骤失败：该材料 `is_indexed` 保持 `false` 并写 `parse_error`（对齐既有行为）。全成功才置 `is_indexed=true`。

旧 `get_indexed_contexts` 被 `rag_search_service.retrieve_top_k` 取代；`ask_ai` 改用召回块作上下文，并返回 `citations`。

### 6. 回答渲染与布局分离

前端 AI 解题助手回答区引入以下方案（纯前端 + 后端 prompt 约束，属于独立增量，与 RAG 检索/溯源功能共享同一变更）：

- **Markdown + LaTeX 渲染**：新增 `react-markdown` 组件，配合 `remark-math`（解析 LaTeX）与 `rehype-katex`（渲染为数学符号），并 import `katex/dist/katex.min.css`。封装为 `components/markdown-answer.tsx`，统一承载 AI 回答文本渲染。
- **公式定界符限制**：`remark-math@6` 只识别 `$...$`/`$$...$$`，不识别 `\(...\)`/`\[...\]`（后者会源码原样透传，导致 `\vec`/`\frac` 字样暴露）。因此后端 `llm_service.SYSTEM_PROMPT` MUSt 要求 DeepSeek 用 `$...$`（行内）/`$$...$$`（独立独占一行）包裹公式，并给出 `\frac{}{}`、`\sqrt{}`、`\vec{a}` 等写法的示例。
- **回答禁含检索过程元话语**：`SYSTEM_PROMPT` 明确禁止回答正文出现「据资料重建」「公式本体未收录」「文档格式限制」「仅保留标题」「教材标准公式」「召回文本未含公式本体」「资料检索」「按标准形式给出」等内部处理/检索状态/过渡性说明；资料仅提及某公式知识点但召回文本未含公式本体时，模型可直接以 `$...$`/`$$...$$` 呈现该标准公式并正常 `[n]` 标源，直接进入解题与结论。
- **回答与参考资料独立成卡**：「回答正文」与「参考资料」从视觉上拆分为两个独立卡片（回答卡为灰底、资料卡为白底带边框），参考资料不再内嵌于回答卡片内部。
- **参考资料仅显示文件名**：参考资料卡片条目只展示来源材料文件名（不带块序号、不展示原文摘要，避免大段摘要撑高卡片），点击条目跳转到材料预览。同一份材料的多个分块召回时，按文件名去重，同份资料只出现一次。
- **无引用不渲染资料卡**：当 `citations` 为空时，仅渲染回答卡片，不渲染空的参考资料卡片。

该方案中，前端仅扩展展示层（不改后端响应结构 `answer + citations`）；后端仅调整 `llm_service.SYSTEM_PROMPT` 引导模型输出可被渲染的公式定界符并抑制元话语，不改变接口结构。

## Risks / Trade-offs

- **[字符 n-gram 哈希向量语义较弱]** → 可能召回字面重叠但语义相关性一般的块。**缓解**：支持替换 embedding 实现（接口隔离）；Top-K + 溯源让学生能核对；作业为范围限定检索，字面相关已足够演示。另在向量排序前增加跨章节标题预筛（`_prefilter_materials`），按问题与标题的字符二元组重叠排除「字面重叠但章节不同」的材料。
- **[标题预筛误伤泛化标题材料]**（统练/期中/月考等标题不含问题关键词的材料可能被过滤）→ **缓解**：预筛无任何保留时回退全保留；预筛按整份候选材料而非单块判定，仅影响跨章节误排这一特定场景；根本解法仍是升级为本地语义向量（SBERT），见 Open Questions。
- **[分块边界割裂语义]** → 定义恰好在句子中间的块。**缓解**：按段落/换行对齐优先；重叠 100 字符补偿边界信息损失。
- **[全班块全量载入内存计算相似度]** → 班级块基数小，问题不大；块数增长时**缓解**：可按关键词/BM25 预筛后再精确向量排序，留作优化项。
- **[向量化失败致整份材料未索引]** → **缓解**：与既有 parse_error 一致，仅该材料不可检索，不影响其他材料与上传。
- **[本地向量无法覆盖同义改写查询]** → **缓解**：文档化说明其为默认轻量方案，后续可换 embedding 模型提升召回。

## Migration Plan

- 新增 `MaterialChunk` 表（`run_simple_migrations` 或 `create_all` 建表，无历史数据回落风险）。
- 对已 `is_indexed=true` 的存量材料，提供一次性重索引入口（复用教师 reindex 端点改跑分块+向量化）。
- 无破坏性变更；`get_indexed_contexts` 保留为兼容壳，`ask_ai` 切换新检索实现。

## Open Questions

- 是否将 embedder 升级为本地语义模型（SBERT）以提升召回质量——不改变规格与接口，可在任务实施后按质量评估决定，仅影响 `embedding_service` 内部实现。