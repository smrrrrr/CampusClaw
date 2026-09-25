## 1. 数据模型

- [x] 1.1 在 models.py 新增 MaterialChunk 表（id, material_id FK CASCADE, class_id NOT NULL, chunk_index, content, embedding BLOB, created_at），对 (class_id, material_id) 建索引，验证表通过 create_all 或 run_simple_migrations 创建成功
- [x] 1.2 新增 embedding/chunk 相关配置到 config.py（chunk_size=500, overlap=100, top_k=5, embed_dim=512），验证配置加载正确

## 2. 分块与向量化服务

- [x] 2.1 新建 chunk_service.py 实现文本分块（定长 500 + 重叠 100，边界对齐段落/换行），验证短文本仅 1 块、长文本多块且序号递增
- [x] 2.2 新建 embedding_service.py 实现字符 n-gram 哈希向量化（维数 512，bigram/trigram + TF 加权，输出定长 list[float]），验证同义/近似文本向量相似度高于无关文本
- [x] 2.3 实现向量余弦相似度函数 cosine_similarity(a, b)，验证单位向量自相似度为 1、正交向量为 0

## 3. 检索服务

- [x] 3.1 新建 rag_search_service.py 实现 retrieve_top_k(db, class_ids, query_text, k=5)，仅查 is_indexed=true 且 class_id 匹配 的 MaterialChunk，按余弦相似度降序返回 TOP-K（material_id, filename, chunk_index, content, score），验证召回仅限指定班级且按分数排序
- [x] 3.2 复用 require_student_class_id / require_teacher_classes / check_class_id_consistency 约束检索 scope，验证越权（篡改 class_id）被 403 + 审计

## 4. 索引流程改造

- [x] 4.1 改造 material_service.run_indexing：解析整份纯文本后追加"分块 + 逐块向量化写 MaterialChunk"，全成功才 is_indexed=true、失败保持 false 并存 parse_error，验证上传后异步生成分块与向量、索引标记正确
- [x] 4.2 教师 reindex 端点改为走新索引流程（分块+向量化），验证存量材料可重索引入库并被检索

## 5. AI 解题助手接入

- [x] 5.1 改造 routers/student.py 的 ask_ai：用 rag_search_service.retrieve_top_k 召回块作上下文（带 [n] 引用编号与来源），取代 get_indexed_contexts 整份拼接，验证回答基于召回块生成
- [x] 5.2 AI 响应结构扩展 citations（material_id, filename, chunk_index, excerpt, score），无召回时返回"暂无相关班级资料"提示，验证无依据不臆造、超 403 边界校验
- [x] 5.3 记录 AI 提问日志含 class_id（非空校验），验证 class_id NULL 边界被拒

## 6. 前端溯源展示

- [x] 6.1 AI 解题助手前端回答区新增"参考资料"面板，渲染 citations 列表（来源文件名、块序号、摘要），验证点击可跳转到对应材料预览
- [x] 6.2 无召回分块时前端展示"暂无相关班级资料"空状态，验证降级提示正确
- [x] 6.3 前端类型定义对齐 citations 响应结构（lib/api.ts / 组件 props），验证编译通过

## 7. 集成验证

- [x] 7.1 端到端：教师上传 PDF → 异步解析 → 分块 → 向量化 → is_indexed=true，验证完整索引链路
- [x] 7.2 端到端：学生提问 → 仅召回本班相关分块 → 回答含 citations 溯源，验证溯源与隔离正确
- [x] 7.3 端到端：学生尝试检索其他班材料 / 前往其他班上下文 → 403 + 审计；无素材班级提问 → 降级提示，验证边界
- [x] 7.4 存量材料重索引后可用新检索召回，验证迁移兼容；npm run build 前端编译通过