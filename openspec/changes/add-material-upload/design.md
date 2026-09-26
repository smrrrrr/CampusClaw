## Context

CampusClaw 已有登录与账号体系（add-login-and-account-system）定义 JWT 会话和双角色，RBAC 规约（add-rbac-role-permissions）定义角色权限矩阵和数据隔离原则，班级数据隔离规约（add-class-data-isolation）定义 class_id 字段规范和查询层强制隔离。本设计为"材料上传入库"规约中定义的全部行为提供技术实现方案，重点解决文件上传与校验、存储策略、异步索引、数据隔离和下载鉴权。详见 proposal.md - Why。

## Goals / Non-Goals

**Goals:**

- 确定 Material 表结构与字段规范
- 确定文件存储路径与 Docker 卷挂载方案
- 确定文件类型校验（MIME + 文件头）方案
- 确定文件重命名策略
- 确定异步文本解析与 is_indexed 标记方案
- 确定上传回滚机制
- 确定下载与预览鉴权方案

**Non-Goals:**

- 不实现文件分片上传（50MB 以内直接上传）
- 不实现文件断点续传
- 不实现文件版本管理（同名文件重命名而非版本化）
- 不引入对象存储服务（如 MinIO/S3），使用本地文件系统
- 不实现全文搜索引擎（如 Elasticsearch），异步解析为纯文本存储供后续 RAG 使用
- 不实现文件病毒扫描（仅做基础文件头校验）

## Decisions

### 1. Material 表设计

Material 表字段：`id（主键）、class_id（INTEGER, 非 NULL, 建索引, 外键关联班级表）、uploader_id（INTEGER, 外键关联 User 表）、filename（原文件名）、file_path（存储路径, 含子目录和时间戳重命名）、file_type（MIME 类型）、file_size（字节）、description（描述文本）、tags（标签, JSON 数组）、is_indexed（布尔, 默认 false）、created_at（时间戳）`。

class_id 建索引加速按班级查询。is_indexed 建索引加速 AI 检索过滤。对 (class_id, is_indexed) 建联合索引优化"查询某班已索引材料"场景。

### 2. 文件存储路径与 Docker 卷挂载

文件存储在 Docker 容器内 `/app/uploads/` 目录，按 class_id 分子目录：`/app/uploads/{class_id}/{timestamp}_{filename}`。

docker-compose.yml 配置卷挂载：`./uploads:/app/uploads`，确保容器重启后文件持久化。宿主机 `./uploads` 目录由 Docker 自动创建。

**替代方案**：使用对象存储（MinIO/S3）。**未选原因**：校园级应用单机部署足够，本地文件系统简单直接，无额外基础设施成本。

### 3. 文件重命名策略

上传时若同目录下已存在同名文件，系统自动加时间戳前缀：`{unix_timestamp}_{original_filename}`（如 `1620000000_lesson1.pdf`）。时间戳使用 Unix 时间戳（秒级），保证全局唯一性。

file_path 字段存储完整相对路径（如 `101/1620000000_lesson1.pdf`），filename 字段保留原文件名供展示。

### 4. MIME 类型与文件头校验

使用 python-magic 或 filetype 库读取文件头部字节判断真实 MIME 类型，不信任文件扩展名。允许的 MIME 映射：

- PDF: application/pdf → 文件头 %PDF
- PPTX: application/vnd.openxmlformats-officedocument.presentationml.presentation → 文件头 PK（ZIP 格式）
- DOCX: application/vnd.openxmlformats-officedocument.wordprocessingml.document → 文件头 PK
- JPG: image/jpeg → 文件头 \xFF\xD8\xFF
- PNG: image/png → 文件头 \x89PNG

校验流程：先校验文件大小（≤ 50MB）→ 读取文件头校验 MIME 类型 → 通过后写入磁盘。

### 5. 异步文本解析

上传成功后使用 FastAPI BackgroundTasks 异步启动文本解析任务：

- PDF：使用 PyMuPDF（fitz）提取文本
- PPTX/DOCX：使用 python-pptx / python-docx 提取文本
- JPG/PNG：提取图片元数据（文件名、描述）或 OCR（后续优化）

解析成功的纯文本存储在独立字段或独立表（如 MaterialContent 表），is_indexed 标记为 true。解析失败保持 is_indexed=false，记录失败原因。

### 6. 上传回滚机制

上传流程采用 try-except 回滚：

1. 校验文件大小和 MIME 类型 → 失败返回 400
2. 生成 file_path（含重命名）
3. 写入物理文件到 /app/uploads/{class_id}/ → 失败返回 500
4. 写入 Material 表记录 → 失败则删除步骤 3 写入的物理文件，返回 500
5. 启动异步文本解析任务 → 返回上传成功响应

步骤 4 失败时的回滚确保不留下孤立物理文件。

### 7. 下载与预览鉴权

下载接口从 JWT Payload 提取 class_id（学生）或 teaching_classes（教师），校验请求材料的 class_id 是否匹配：

- 学生：材料 class_id == JWT class_id → 允许；否则 403
- 教师：材料 class_id IN teaching_classes → 允许；否则 403

在线预览：
- PDF：前端使用 PDF.js 或 iframe 直接渲染
- 图片（JPG/PNG）：前端使用 img 标签直接渲染
- 预览接口返回文件流，前端根据文件类型选择渲染方式

### 8. 材料列表查询隔离

材料列表查询复用班级数据隔离规约的查询层强制隔离方案：

- 学生：WHERE class_id = :current_class_id
- 教师：WHERE class_id IN (teaching_classes)

支持按 description/tags 模糊搜索、按 created_at 排序、分页。

### 9. 教师删除材料

新增 `DELETE /api/teacher/materials/{material_id}` 端点（Depends(get_current_teacher)），仅教师可删，前端仅对 role=teacher 渲染删除按钮。

权限与隔离：删除前校验 `material.class_id in current.teaching_classes`，不在则 403 + 审计（复用 upload 的 teaching_classes 校验语义），对齐"查询层强制 class_id 隔离作为最终防御"约束。

清理顺序（保证不产生孤立文件）：

1. 显式删除 `material_contents` 与 `material_chunks` 中该 material_id 的行（因 SQLite 未开启 `PRAGMA foreign_keys=ON`，`ondelete=CASCADE` 不会自动触发，必须显式清理，避免残留旧分块进入 AI 检索或留下脏数据）。
2. `db.delete(material)` + commit；该步骤失败则整体 rollback，且 MUST NOT 删除物理文件，返回 500（避免孤立、不可追踪的文件）。
3. DB 提交成功后调用 `material_service.delete_physical_file(file_path)` 删除磁盘文件（幂等，文件不存在静默）。
4. 异步记录成功删除的审计日志。

**并发竞态防护**：删除与首次上传触发的异步 `run_indexing`（BackgroundTasks）可能并发。为确保异步索引不会为已删除材料重建孤立的 `material_contents`/`material_chunks`，`run_indexing` 在写入 content/chunk 前重新校验 `Material` 记录仍存在，已被删除则 rollback 并跳过写入（见 design.md 决策 5 的索引流程）。

删除成功后，AI 检索（`rag_search_service.retrieve_top_k` 的 `JOIN material`）天然不再召回该材料分块，列表/下载/预览因 Material 行不存在返回 404。

**替代方案**：软删除（is_deleted 标记）。**未选原因**：材料为临时学习资料，物理删除更贴合"删除后不可访问"，且无版本回溯需求，避免数据累积与检索过滤漏配。

## Risks / Trade-offs

- **[本地文件存储单机限制]** → 文件存储在单机文件系统，无法水平扩展。**缓解**：校园级应用单机部署足够；Docker 卷挂载宿主机目录可配合宿主机备份。

- **[异步解析可能失败]** → PPTX/DOCX/PDF 解析可能因文件损坏或格式异常失败。**缓解**：is_indexed=false 标记未索引状态；记录失败原因；后续可提供手动重新索引入口。

- **[大文件上传超时]** → 50MB 文件上传可能因网络慢导致超时。**缓解**：配置合理的上传超时时间（如 120s）；前端提供进度条和重试按钮。

- **[PPTX/DOCX 解析依赖]** → 需要额外 Python 库（PyMuPDF、python-pptx、python-docx）。**缓解**：uv 环境管理统一安装；解析失败不影响上传成功，仅影响 AI 检索。

- **[无文件备份]** → 本地存储无冗余备份。**缓解**：Docker 卷挂载到宿主机，可配合宿主机定时备份策略；后续可引入对象存储。
