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

默认采用**概念感知分块**（本地优化版 `chunk_service.py`）：

1. 把整份纯文本先按**语义锚点**切成逻辑段（segment）：
   - Markdown 标题（`##` / `### …`）
   - 加粗子标签行（`**向量夹角公式**：`、`**线面角公式**：` 等定义/公式入口）
   这样每个公式、每条定义都尽量自成一段，作为独立可检索单元，避免「概念标题 + 公式体」被定长窗口从中间劈开而稀释检索信噪比。
2. 段长 ≤ `CHUNK_SIZE`（默认 300）时整段保留；超长的段再按空白行（段落）贪婪合并为 ≤ 300 的块，并与相邻块携带 `OVERLAP`（默认 60）字符上下文，避免概念衔接被硬断。

- 每块存 `chunk_index`（从 1 开始递增），同材料的块共享 `material_id` 与 `class_id`。
- 当前 `MaterialContent.content` 仍存整份文本以保留预览/校验；分块数据落到新表 `MaterialChunk`。

**替代方案**：纯固定长度 + 重叠的滑动窗口分块。**未选原因**：定长 500/300 会恰好切进公式/定义中间，把「向量夹角公式」的标题与公式体split成两块，严重降低检索精度；概念感知分块在同一纯文本层实现、零外部依赖、无需分词，覆盖更贴合讲义的实际结构。

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
5. 逐块计算余弦相似度 `sim = dot(q, e) / (|q|*|e|)`，按 `sim` 降序取 Top-K（默认 `K = 3`，`config.chunk_top_k`，参考资料 2-3 条即可）。
6. 召回结果为 `[{material, filename, chunk_index, content, score}]`，供溯源与上下文注入。
7. 排序后按 `config.chunk_min_relevance`（默认 0.35）做相关度下限过滤：低于「最优命中分数 × 该比例」的块剔除后再截断 Top-K，避免章节总览等弱相关块硬凑条数。

检索采用多路打分并默认 RRF 融合（`config.retrieval_mode`，默认 `hybrid`）：
- **向量信号**：`sim = dot(q, e) / (|q|*|e|)`（字符 n-gram 哈希向量余弦）。
- **关键字信号**：`kw = Σ query 字符二元组在 chunk.content 的出现次数 × 该词的 IDF 权重`（纯文本层，无需额外索引）。IDF 权重按「该词在整批候选块中的文档频率」计算（`_idf_weights`），抑制「向量」（几乎每块出现）这类高频泛词，让「夹角/公式/cos/坐标」等稀有判别词主导排序——弥补纯字符信号无法语义联想「求夹角→cos 公式」的缺陷。
- **RRF 融合**：对每路排序（按各自分降序的 chunk_id 列表）计算 `score = Σ 1/(60+rank)`，按融合分降序取 Top-K；双路都命中的分块排名靠前。
- **模式切换**：`vector` 走余弦、`keyword` 走关键字、`hybrid`（默认）走 RRF。任一路无相关（余弦≤0 且关键字≤0）的分块直接排除，避免无关块混入。

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
- **参考资料标注出处并可回溯原文**：参考资料卡片条目逐条展示每个命中分块——标注来源文件名与块序号、展示该分块原文片段（`.citation-excerpt` 浅灰底+红左边条），并提供「查看原文」入口（通过鉴权预览/下载接口打开来源材料文件）。同一份材料的多个分块命中时逐条保留（每条独立出处与片段），不做文件名合并去重，以保留原文定位能力。
- **命中原文片段只展示知识点讲解**：对讲义类材料（知识点讲解与【即学即练】练习题交错分布），溯源片段不固定取分块前 N 字，而用 `best_snippet(content, query)` 滑窗找出与问题字符二元组重叠最密集的连续子片段（并前后补省略号），使参考资料呈现解题「依据」而非练习题目墙。配合较小的切块（300/60），知识点片段更聚焦。
- **公式渲染归一化**：`markdown-answer.tsx` 对公式块内的裸 LaTeX 命令（如源文件 `$vec{a}$`、`$sqrt{...}$` 缺反斜杠）在渲染期补 `\`；匹配方式为「最长字母串 + 前面非反斜杠 + 位于命令表」，确保已正确转义的 `\overrightarrow` 不被误拆为 `\over\rightarrow`（后者会触发 KaTeX 红色源码直显）。
- **无引用不渲染资料卡**：当 `citations` 为空时，仅渲染回答卡片，不渲染空的参考资料卡片。

该方案中，前端仅扩展展示层（不改后端响应结构 `answer + citations`）；后端仅调整 `llm_service.SYSTEM_PROMPT` 引导模型输出可被渲染的公式定界符并抑制元话语，不改变接口结构。

## Risks / Trade-offs

- **[字符 n-gram 哈希向量语义较弱、无法联想「求夹角→cos 公式」类同义改写]** → 曾导致「坐标算夹角」召回基底定理/共面向量等无关块。**缓解（已实现）**：(1) 概念感知分块让「夹角公式标题 + 公式体」自成一块；(2) IDF 加权关键字打分抑制「向量」高频泛词、凸显稀有判别词。二者结合后该查询可正确召回 cos/夹角公式块。根本长期解法仍是升级为语义向量（SBERT），见 Open Questions。
- **[标题预筛误伤泛化标题材料]**（统练/期中/月考等标题不含问题关键词的材料可能被过滤）→ **缓解**：预筛无任何保留时回退全保留；预筛按整份候选材料而非单块判定，仅影响跨章节误排这一特定场景；根本解法仍是升级为本地语义向量（SBERT），见 Open Questions。
- **[分块边界割裂语义]**（定长窗口切进公式/定义中间）→ **已化解**：概念感知分块按标题/加粗子标签切逻辑段，整段 ≤ 300 时保留、超长再按段落贪婪合并并带叠。
- **[全班块全量载入内存计算相似度]** → 班级块基数小，问题不大；块数增长时**缓解**：可按关键词/BM25 预筛后再精确向量排序，留作优化项。
- **[向量化失败致整份材料未索引]** → **缓解**：与既有 parse_error 一致，仅该材料不可检索，不影响其他材料与上传。
- **[本地向量无法覆盖同义改写查询]** → **缓解**：文档化说明其为默认轻量方案，后续可换 embedding 模型提升召回。

## Migration Plan

- 新增 `MaterialChunk` 表（`run_simple_migrations` 或 `create_all` 建表，无历史数据回落风险）。
- 对已 `is_indexed=true` 的存量材料，提供一次性重索引入口（复用教师 reindex 端点改跑分块+向量化）。
- 无破坏性变更；`get_indexed_contexts` 保留为兼容壳，`ask_ai` 切换新检索实现。

## Open Questions

- 是否将 embedder 升级为本地语义模型（SBERT）以提升召回质量——不改变规格与接口，可在任务实施后按质量评估决定，仅影响 `embedding_service` 内部实现。