## 1. 数据模型与基础设施

- [x] 1.1 创建 Material 模型（id, class_id, uploader_id, filename, file_path, file_type, file_size, description, tags, is_indexed, created_at），对 class_id 建索引，对 (class_id, is_indexed) 建联合索引，验证表创建成功
- [x] 1.2 在 docker-compose.yml 中配置 ./uploads:/app/uploads 卷挂载，验证容器重启后文件不丢失
- [x] 1.3 创建 /app/uploads/ 存储目录及按 class_id 分子目录的逻辑，验证文件按班级存储

## 2. 文件上传端点

- [x] 2.1 实现 POST /api/teacher/upload-material 端点（Depends(get_current_teacher) 拦截，非教师返回 403），验证教师可上传、学生被拒
- [x] 2.2 实现文件大小校验（≤ 50MB，超限返回 400），验证超大文件被拒
- [x] 2.3 实现 MIME 类型校验（python-magic/filetype 读取文件头，不信任扩展名），验证伪造扩展名被拒
- [x] 2.4 实现文件头 magic number 校验（PDF %PDF, PPTX/DOCX PK, JPG \xFF\xD8\xFF, PNG \x89PNG），验证恶意文件被拒
- [x] 2.5 实现班级选择校验（class_id 在 teaching_classes 范围内，否则 403），验证篡改 class_id 被拒
- [x] 2.6 实现文件自动重命名（时间戳前缀 + 原文件名），验证同名文件不覆盖
- [x] 2.7 实现上传元数据完整写入 Material 表（class_id, uploader_id, filename, file_path, file_type, file_size, description, tags, is_indexed=false, created_at），验证记录完整

## 3. 上传异常处理与回滚

- [x] 3.1 实现 DB 写入失败时回滚删除物理文件（try-except），验证不留下孤立文件
- [x] 3.2 实现网络中断时前端重试按钮，验证教师可重新发起上传
- [x] 3.3 实现前端 accept 属性初步限制（.pdf,.pptx,.docx,.jpg,.png），验证文件选择器仅显示允许格式
- [x] 3.4 实现前端上传进度展示和失败提示，验证用户体验完整

## 4. 知识库索引关联

- [x] 4.1 实现异步文本解析任务（FastAPI BackgroundTasks），验证上传成功后自动启动解析
- [x] 4.2 实现 PDF 文本提取（PyMuPDF/fitz），验证 PDF 内容正确解析为纯文本
- [x] 4.3 实现 PPTX/DOCX 文本提取（python-pptx/python-docx），验证 Office 文档内容正确解析
- [x] 4.4 实现 is_indexed 标记更新（解析成功 → true, 失败 → 保持 false），验证标记正确
- [x] 4.5 验证仅 is_indexed=true 的材料被 AI 检索接口返回，is_indexed=false 不被检索

## 5. 材料列表查询与隔离

- [x] 5.1 实现 GET /api/materials 端点（学生 WHERE class_id = :current_class_id），验证学生仅看到本班材料
- [x] 5.2 实现 GET /api/materials 端点（教师 WHERE class_id IN (teaching_classes)），验证教师仅看到任教班级材料
- [x] 5.3 实现材料列表分页、按 created_at 排序、按 description/tags 模糊搜索，验证查询功能完整
- [x] 5.4 验证学生篡改 class_id 查询被拒 403 + 审计日志

## 6. 下载与预览

- [x] 6.1 实现 GET /api/materials/{id}/download 端点（校验 class_id 匹配，不匹配 403），验证学生/教师可下载本班材料
- [x] 6.2 验证学生尝试下载其他班材料被拒 403 + 审计日志
- [x] 6.3 实现前端 PDF 在线预览（PDF.js 或 iframe），验证 PDF 可在线预览
- [x] 6.4 实现前端图片在线预览（JPG/PNG，img 标签），验证图片可在线预览
- [x] 6.5 实现前端下载按钮（触发下载接口），验证文件可正确下载

## 7. 前端页面

- [x] 7.1 实现教师上传页面（班级选择器从 teaching_classes 读取、文件选择 accept 属性、描述/标签输入、上传进度），验证教师可完整上传
- [x] 7.2 实现材料列表页面（按 class_id 展示材料、预览/下载按钮、搜索框），验证学生和教师可查看材料
- [x] 7.3 实现前端无上传入口控制（role=student 不展示上传按钮），验证学生无上传入口

## 8. 集成验证

- [x] 8.1 端到端验证：教师登录→选择任教班级→上传 PDF（含描述/标签）→文件存储→元数据入库→异步解析→is_indexed=true，验证完整上传流程
- [x] 8.2 端到端验证：学生登录→查看本班材料→在线预览 PDF→下载材料→尝试下载其他班材料被拒 403，验证学生查看下载流程
- [x] 8.3 端到端验证：上传超大文件/不允许格式/伪造扩展名→后端校验返回 400，验证文件校验拦截
- [x] 8.4 端到端验证：同名文件上传→自动重命名→DB 写入失败→物理文件回滚删除，验证异常处理
- [x] 8.5 端到端验证：Docker 容器重启→已上传文件和元数据完好→可正常下载，验证持久化
- [x] 8.6 端到端验证：AI 检索接口仅返回 is_indexed=true 的材料文本，验证知识库索引关联
