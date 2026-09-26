## 1. 数据模型

- [x] 1.1 在 models.py 新增 MaterialChunk 表（id, material_id FK CASCADE, class_id NOT NULL, chunk_index, content, embedding BLOB, created_at），对 (class_id, material_id) 建索引，验证表通过 create_all 或 run_simple_migrations 创建成功
- [x] 1.2 新增 embedding/chunk 相关配置到 config.py（chunk_size=500, overlap=100, top_k=12, embed_dim=512），验证配置加载正确

## 2. 分块与向量化服务

- [x] 2.1 新建 chunk_service.py 实现文本分块（定长 500 + 重叠 100，边界对齐段落/换行），验证短文本仅 1 块、长文本多块且序号递增
- [x] 2.2 新建 embedding_service.py 实现字符 n-gram 哈希向量化（维数 512，bigram/trigram + TF 加权，输出定长 list[float]），验证同义/近似文本向量相似度高于无关文本
- [x] 2.3 实现向量余弦相似度函数 cosine_similarity(a, b)，验证单位向量自相似度为 1、正交向量为 0

## 3. 检索服务

- [x] 3.1 新建 rag_search_service.py 实现 retrieve_top_k(db, class_ids, query_text, k=None 默认取 config.chunk_top_k=12)，仅查 is_indexed=true 且 class_id 匹配 的 MaterialChunk，按余弦相似度降序返回 TOP-K（material_id, filename, chunk_index, content, score），验证召回仅限指定班级且按分数排序
- [x] 3.2 复用 require_student_class_id / require_teacher_classes / check_class_id_consistency 约束检索 scope，验证越权（篡改 class_id）被 403 + 审计

## 4. 索引流程改造

- [x] 4.1 改造 material_service.run_indexing：解析整份纯文本后追加"分块 + 逐块向量化写 MaterialChunk"，全成功才 is_indexed=true、失败保持 false 并存 parse_error，验证上传后异步生成分块与向量、索引标记正确
- [x] 4.2 教师 reindex 端点改为走新索引流程（分块+向量化），验证存量材料可重索引入库并被检索

## 5. AI 解题助手接入

- [x] 5.1 改造 routers/student.py 的 ask_ai：用 rag_search_service.retrieve_top_k 召回块作上下文（带 [n] 引用编号与来源），取代 get_indexed_contexts 整份拼接，验证回答基于召回块生成
- [x] 5.2 AI 响应结构扩展 citations（material_id, filename, chunk_index, excerpt, score），无召回时返回"暂无相关班级资料"提示，验证无依据不臆造、超 403 边界校验
- [x] 5.3 记录 AI 提问日志含 class_id（非空校验），验证 class_id NULL 边界被拒

## 6. 前端溯源展示

- [x] 6.1 AI 解题助手前端回答区新增"参考资料"面板，渲染 citations 列表（仅显示来源文件名，不带块序号/摘要），验证点击可跳转到对应材料预览
- [x] 6.2 无召回分块时前端展示"暂无相关班级资料"空状态，验证降级提示正确
- [x] 6.3 前端类型定义对齐 citations 响应结构（lib/api.ts / 组件 props），验证编译通过

## 7. 集成验证

- [x] 7.1 端到端：教师上传 PDF → 异步解析 → 分块 → 向量化 → is_indexed=true，验证完整索引链路
- [x] 7.2 端到端：学生提问 → 仅召回本班相关分块 → 回答含 citations 溯源，验证溯源与隔离正确
- [x] 7.3 端到端：学生尝试检索其他班材料 / 前往其他班上下文 → 403 + 审计；无素材班级提问 → 降级提示，验证边界
- [x] 7.4 存量材料重索引后可用新检索召回，验证迁移兼容；npm run build 前端编译通过

## 8. 回答渲染与布局分离

- [x] 8.1 新增 markdown-answer 组件（react-markdown + remark-math + rehype-katex），在 layout 引入 katex CSS，回答以 Markdown 富文本渲染且 LaTeX 公式渲染为数学符号；验证公式与列表/加粗正确显示
- [x] 8.2 student 页将「回答卡片」与「参考资料卡片」拆分为两个独立视觉区域，无引用时不渲染空的参考资料卡片；验证 npm run build 编译通过
- [x] 8.3 llm_service.SYSTEM_PROMPT 将公式定界符限定为 `$...$`（行内）/`$$...$$`（独立独占一行），并提供 `\frac{}{}`、`\sqrt{}`、`\vec{a}` 等写法示例；验证模型输出能被 remark-math 识别渲染，不再透传 `\(...\)`/`\[...\]` 源码
- [x] 8.4 SYSTEM_PROMPT 增加元话语禁令（「据资料重建」「公式本体未收录」「文档格式限制」「仅保留标题」「教材标准公式」「召回文本未含公式本体」「资料检索」「按标准形式给出」等），允许资料仅提及知识点时直接以标准 LaTeX 呈现公式并 `[n]` 标源；验证回答正文不再出现内部处理/检索过程说明
- [x] 8.5 参考资料条目仅显示来源文件名（去掉块序号与原文摘要）；验证卡片简洁、不因大段摘要被撑高
- [x] 8.6 参考资料按文件名去重：同一份材料多分块召回时只显示一次；验证同资料不再重复出现
- [x] 8.7 提高检索召回（config.chunk_top_k 5→12）：题干相关但未进前 5 的材料（如 .pdf 与 .docx 同内容的两份总结）也能被召回并被参考资料列出；验证多份相关材料在参考资料中各出现一次、各自可跳转
- [x] 8.8 跨章节检索预筛（rag_search_service._prefilter_materials）：向量排序前按问题与材料标题的字符二元组重叠过滤候选材料，排除「字面重叠但章节不同」的材料（如空间几何问题排除平面解析几何），无保留时回退全保留。验证对「空间中点到直线的距离公式」仅召回空间向量材料（id6 docx + id9 pdf），参考资料不含解析几何条目