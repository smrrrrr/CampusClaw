## Purpose

为 CampusClaw 提供材料上传入库行为契约，覆盖教师上传权限、文件类型与大小限制、上传元数据与班级选择、文件存储策略、重名与异常处理、知识库索引关联、材料数据隔离与审计、下载与预览，确保资料管理在权限边界和班级隔离内安全运行，并为 AI 解题助手提供可检索的知识库素材。

## ADDED Requirements

### Requirement: 教师上传权限控制

系统 MUST 仅允许教师（role=teacher）上传资料。学生（含家长代登录，role=student）MUST 仅具备查看和下载权限，MUST NOT 拥有上传入口。后端上传接口 MUST 通过 Depends(get_current_teacher) 拦截，非教师角色调用 MUST 返回 403 Forbidden。

#### Scenario: 教师上传资料成功

- **WHEN** role=teacher 的教师登录后访问上传页面，选择文件并提交上传
- **THEN** 系统接受上传请求，处理文件并存储

#### Scenario: 学生尝试上传被拒

- **WHEN** role=student 的用户尝试访问上传接口
- **THEN** get_current_teacher 依赖校验失败，返回 403 Forbidden，记录审计日志

#### Scenario: 家长代登录尝试上传被拒

- **WHEN** 家长通过验证码登录学生账号后尝试访问上传接口
- **THEN** 系统返回 403 Forbidden，家长享有学生权限无上传入口

#### Scenario: 学生前端无上传入口

- **WHEN** role=student 的用户查看材料页面
- **THEN** 前端不展示上传按钮或上传入口

### Requirement: 文件类型与大小限制

系统 MUST 仅允许以下文件格式：PDF、PPTX、DOCX、JPG、PNG。单文件大小上限 MUST 为 50MB。前端 MUST 通过 accept 属性做初步限制。后端 MUST 校验真实的 MIME 类型（不信任文件扩展名）和文件大小，不合规 MUST 返回 400 Bad Request。

#### Scenario: 上传允许格式的文件成功

- **WHEN** 教师上传一个 PDF 文件（大小 10MB）
- **THEN** 后端校验 MIME 类型为 application/pdf，大小未超限，接受上传

#### Scenario: 上传超大文件被拒

- **WHEN** 教师上传一个 51MB 的 PDF 文件
- **THEN** 后端校验文件大小超过 50MB 上限，返回 400 Bad Request

#### Scenario: 上传不允许的格式被拒

- **WHEN** 教师上传一个 .exe 文件
- **THEN** 后端校验 MIME 类型不在允许列表中，返回 400 Bad Request

#### Scenario: 伪造扩展名被后端 MIME 校验拦截

- **WHEN** 教师将一个 .exe 文件重命名为 .pdf 后上传
- **THEN** 后端校验真实 MIME 类型为 application/x-msdownload 而非 application/pdf，返回 400 Bad Request

#### Scenario: 前端 accept 属性初步限制

- **WHEN** 教师在文件选择器中选择文件
- **THEN** 前端 accept 属性仅显示 PDF/PPTX/DOCX/JPG/PNG 格式的文件，其他格式不可选

### Requirement: 上传元数据与班级选择

教师上传资料时前端 MUST 提供班级选择器，展示该教师 teaching_classes 中的所有任教班级。上传 MUST 附带元数据：文件名、所属 class_id、上传者 user_id、上传时间、文件描述/标签、file_path。后端 MUST 校验目标 class_id 是否在教师 JWT Payload 的 teaching_classes 范围内，不在则返回 403 Forbidden。

#### Scenario: 教师选择任教班级上传成功

- **WHEN** 教师 teaching_classes=[101,102]，选择班级 101 上传一份资料并填写描述和标签
- **THEN** 系统校验 class_id=101 在 teaching_classes 中，接受上传，记录完整元数据

#### Scenario: 多班级教师班级选择器展示所有任教班级

- **WHEN** 教师 teaching_classes=[101,102,103]，打开上传页面
- **THEN** 前端班级选择器展示班级 101、102、103 三个选项

#### Scenario: 教师篡改 class_id 上传非任教班级被拒

- **WHEN** 教师 teaching_classes=[101,102]，尝试在请求中传入 class_id=201 上传资料
- **THEN** 后端校验 201 不在 teaching_classes 中，返回 403 Forbidden

#### Scenario: 上传元数据完整记录

- **WHEN** 教师上传成功后查询材料记录
- **THEN** Material 表记录包含 class_id、uploader_id、filename、file_path、file_type、file_size、description、tags、is_indexed（初始为 false）、created_at

### Requirement: 文件存储策略

系统 MUST 将文件元数据存储在 SQLite 的 Material 表中，文件本体 MUST 存储在 Docker 挂载的宿主机目录（/app/uploads/）中。系统 MUST NOT 将文件二进制流直接存入 SQLite。docker-compose.yml MUST 明确挂载卷 ./uploads:/app/uploads，确保容器重启后文件不丢失。

#### Scenario: 文件存储在挂载目录

- **WHEN** 教师上传一份资料，系统处理完成后
- **THEN** 文件本体存储在 /app/uploads/ 目录中，Material 表中 file_path 字段记录存储路径

#### Scenario: SQLite 仅存储元数据

- **WHEN** 查询 Material 表记录
- **THEN** 表中不包含文件二进制流字段，仅包含元数据字段

#### Scenario: 容器重启后文件不丢失

- **WHEN** Docker 容器重启后教师查询已上传的资料
- **THEN** 文件元数据在 SQLite 中完好，文件本体在 /app/uploads/ 卷挂载目录中完好，可正常下载

#### Scenario: 文件按 class_id 分子目录存储

- **WHEN** 教师上传资料到班级 101
- **THEN** 文件存储在 /app/uploads/101/ 子目录下，便于按班级管理文件

### Requirement: 文件重名与异常处理

系统 MUST NOT 覆盖同名文件，MUST 自动重命名（如加时间戳前缀 1620000000_filename.pdf）。若文件写入成功但数据库记录写入失败，系统 MUST 删除已写入的物理文件（回滚）。网络中断时前端 MUST 提供重试按钮。系统 MUST 对上传文件做基础文件头校验，拒绝含有恶意脚本或伪造文件头的文件。

#### Scenario: 同名文件自动重命名

- **WHEN** 教师上传文件名为"lesson1.pdf"的资料，且 /app/uploads/101/ 下已存在同名文件
- **THEN** 系统自动重命名为 1620000000_lesson1.pdf（时间戳前缀），不覆盖原文件

#### Scenario: DB 写入失败时回滚删除物理文件

- **WHEN** 文件已写入 /app/uploads/ 但 Material 表记录写入失败（如 SQLite 异常）
- **THEN** 系统删除已写入的物理文件，返回上传失败提示，不留下孤立文件

#### Scenario: 网络中断前端提供重试

- **WHEN** 教师上传文件时网络中断，请求未到达后端或响应未返回
- **THEN** 前端展示"上传失败，请重试"提示和重试按钮，教师点击后重新发起上传

#### Scenario: 恶意文件头校验不通过被拒

- **WHEN** 教师上传一个扩展名为 .pdf 但文件头不是 %PDF 的文件
- **THEN** 后端校验文件头不匹配 PDF 格式，返回 400 Bad Request，拒绝上传

### Requirement: 知识库索引关联

上传成功的材料系统 MUST 将其解析为纯文本（异步处理）。解析完成后 MUST 将 Material 表中 is_indexed 字段标记为 true。只有 is_indexed=true 的材料 MUST 被后续 AI 解题助手功能检索并作为上下文提供给大模型。解析失败的材料 MUST 保持 is_indexed=false，MUST NOT 被 AI 检索。

#### Scenario: 上传成功后异步解析为纯文本

- **WHEN** 教师上传一份 PDF 资料成功，Material 记录创建后
- **THEN** 系统异步启动文本解析任务，将文件内容提取为纯文本存储

#### Scenario: 解析完成后标记 is_indexed 为 true

- **WHEN** 异步文本解析任务成功完成
- **THEN** 系统将该材料记录的 is_indexed 字段更新为 true，该材料可被 AI 解题助手检索

#### Scenario: 仅 is_indexed=true 的材料被 AI 检索

- **WHEN** AI 解题助手检索知识库素材作为上下文
- **THEN** 系统仅返回 is_indexed=true 的材料文本内容，is_indexed=false 的材料不被检索

#### Scenario: 解析失败的材料保持未索引

- **WHEN** 异步文本解析任务执行失败（如文件损坏、格式不支持）
- **THEN** 系统将该材料的 is_indexed 保持为 false，记录失败原因，该材料不被 AI 检索

### Requirement: 材料数据隔离

学生 MUST 只能查询和下载自己所在班级（class_id）的材料。教师 MUST 只能查询和下载自己任教班级（teaching_classes）的材料。后端查询 MUST 带 WHERE class_id 隔离条件。任何越权尝试（篡改 class_id 查询或下载其他班材料）MUST 返回 403 Forbidden 并记录审计日志。

#### Scenario: 学生查询本班材料成功

- **WHEN** 学生 class_id=101 请求查看材料列表
- **THEN** 系统返回 class_id=101 的材料，查询带 WHERE class_id = :current_class_id

#### Scenario: 教师查询任教班级材料成功

- **WHEN** 教师 teaching_classes=[101,102] 请求查看材料列表
- **THEN** 系统返回 class_id IN (101,102) 的材料

#### Scenario: 学生篡改 class_id 查询被拒

- **WHEN** 学生 class_id=101，尝试在请求中传入 class_id=102 查询材料
- **THEN** 系统以 JWT 中的 class_id=101 为准，返回 403 Forbidden，记录审计日志

#### Scenario: 学生尝试下载其他班材料被拒

- **WHEN** 学生 class_id=101，尝试下载 class_id=102 的材料
- **THEN** 系统校验材料 class_id=102 与学生 class_id=101 不匹配，返回 403 Forbidden，记录审计日志

### Requirement: 下载与预览

前端 MUST 支持点击在线预览（PDF/图片）或下载材料。下载接口 MUST 校验当前用户的 class_id（学生）或 teaching_classes（教师）是否与材料的 class_id 匹配，不匹配 MUST 返回 403 Forbidden。

#### Scenario: 学生在线预览 PDF 成功

- **WHEN** 学生 class_id=101 点击一份 PDF 材料的预览按钮
- **THEN** 前端校验材料 class_id=101 与学生 class_id=101 匹配，展示 PDF 在线预览

#### Scenario: 学生在线预览图片成功

- **WHEN** 学生 class_id=101 点击一份 JPG 材料的预览按钮
- **THEN** 前端展示图片在线预览

#### Scenario: 学生下载材料成功

- **WHEN** 学生 class_id=101 点击一份材料的下载按钮
- **THEN** 后端校验材料 class_id=101 与学生 class_id=101 匹配，返回文件流供下载

#### Scenario: 学生尝试下载其他班材料被拒

- **WHEN** 学生 class_id=101，尝试下载 class_id=102 的材料
- **THEN** 后端校验材料 class_id=102 与学生 class_id=101 不匹配，返回 403 Forbidden，记录审计日志

#### Scenario: 教师下载任教班级材料成功

- **WHEN** 教师 teaching_classes=[101,102] 下载 class_id=101 的材料
- **THEN** 后端校验 101 在 teaching_classes 中，返回文件流供下载
