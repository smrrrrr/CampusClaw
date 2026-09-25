## Why

CampusClaw 的登录体系、RBAC 角色权限和班级数据隔离规约已为系统奠定了安全基础，但核心业务功能"材料上传入库"尚无行为契约。教师需要向任教班级上传学习资料，学生需要查看和下载本班资料，AI 解题助手需要检索已索引的材料作为上下文。没有完整的上传、存储、索引、隔离、下载规约，资料管理功能无法安全落地。本变更为系统引入材料上传入库规约，覆盖上传权限、文件类型与大小限制、元数据与班级选择、存储策略、重名与异常处理、知识库索引关联、数据隔离与审计、下载与预览，确保实现时有完整的、可验证的行为契约。

## What Changes

- 引入教师上传权限控制：仅教师可上传资料，学生（含家长代登录）仅具备查看和下载权限，前端无上传入口。
- 引入文件类型与大小限制：允许 PDF/PPTX/DOCX/JPG/PNG，单文件上限 50MB，前端 accept 属性初步限制，后端校验真实 MIME 类型和文件大小，不合规返回 400。
- 引入上传元数据与班级选择：前端提供班级选择器（从 teaching_classes 读取），上传附带元数据（文件名、class_id、上传者 user_id、上传时间、描述/标签、file_path），后端校验 class_id 在 teaching_classes 范围内。
- 引入文件存储策略：SQLite 仅存储元数据（Material 表），文件本体存储在 Docker 挂载卷 /app/uploads/，docker-compose.yml 明确挂载 ./uploads:/app/uploads。
- 引入文件重名与异常处理：同名文件自动重命名（时间戳前缀），DB 写入失败时回滚删除物理文件，网络中断前端提供重试，后端文件头校验防恶意文件。
- 引入知识库索引关联：上传成功后异步解析为纯文本，is_indexed 标记为 true，仅 is_indexed=true 的材料被 AI 解题助手检索。
- 引入材料数据隔离：学生 WHERE class_id = :current_class_id，教师 WHERE class_id IN (teaching_classes)，越权返回 403 + 审计日志。
- 引入下载与预览：支持在线预览（PDF/图片）和下载，下载接口校验 class_id 匹配。

## Capabilities

### New Capabilities
- `material-upload`: 材料上传入库体系，覆盖教师上传权限、文件类型与大小限制、元数据与班级选择、存储策略、重名与异常处理、知识库索引关联、数据隔离与审计、下载与预览。

### Modified Capabilities
- `class-data-isolation`: 材料上传入库规约为班级数据隔离模型新增 Material 表作为需包含 class_id 字段的业务表实例。

## Impact

- **后端 (FastAPI)**：新增 Material 模型（id, class_id, uploader_id, filename, file_path, file_type, file_size, description, tags, is_indexed, created_at）；新增文件上传端点（MIME 校验、大小校验、文件头校验、自动重命名、物理文件写入、DB 记录写入、回滚机制）；新增异步文本解析任务（is_indexed 标记）；新增材料列表查询端点（class_id 隔离）；新增下载端点（class_id 鉴权）；新增预览端点；审计日志写入。
- **前端 (Next.js)**：新增教师上传页面（班级选择器、文件选择、accept 属性、描述/标签输入、上传进度）；新增材料列表页面（按 class_id 展示）；新增在线预览组件（PDF/图片）；新增下载按钮；网络中断重试按钮。
- **数据库 (SQLite)**：新增 Material 表（class_id 字段建索引，is_indexed 字段，(class_id, is_indexed) 联合索引）。
- **部署 (Docker)**：docker-compose.yml 新增 ./uploads:/app/uploads 卷挂载；确保容器重启后文件不丢失。
