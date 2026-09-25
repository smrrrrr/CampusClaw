## 1. 数据模型 class_id 字段规范

- [x] 1.1 班级资料表增加 class_id 字段（INTEGER, 非 NULL, 外键关联班级表, 建索引），验证资料记录按 class_id 隔离
- [x] 1.2 作业布置表增加 class_id 字段（INTEGER, 非 NULL, 外键关联班级表, 建索引），验证作业按 class_id 隔离
- [x] 1.3 作业提交记录表增加 class_id 字段（INTEGER, 非 NULL, 外键关联班级表, 建索引），验证提交记录按 class_id 隔离
- [x] 1.4 AI 提问记录表增加 class_id 字段（INTEGER, 非 NULL, 外键关联班级表, 建索引），验证提问记录按 class_id 隔离
- [x] 1.5 错题本表增加 class_id 字段（INTEGER, 非 NULL, 外键关联班级表, 建索引），验证错题记录按 class_id 隔离

## 2. 后端查询强制隔离

- [x] 2.1 在学生数据查询层实现 WHERE class_id = :current_class_id 过滤（class_id 从 JWT 获取），验证学生只能查询本班数据
- [x] 2.2 在教师数据查询层实现 WHERE class_id IN (teaching_classes) 过滤（teaching_classes 从 JWT 获取），验证教师只能查询任教班级数据
- [x] 2.3 实现请求参数 class_id 一致性校验（与 JWT Payload 对比，不匹配返回 403），验证篡改 class_id 被拒
- [x] 2.4 验证后端不信任请求参数中的 class_id 作为查询依据，以 JWT Payload 为准

## 3. 跨班访问拦截与审计

- [x] 3.1 实现学生跨班访问拦截（请求参数 class_id != JWT class_id → 403 + 审计日志），验证篡改 URL/Payload 被拦截
- [x] 3.2 实现教师跨班访问拦截（请求参数 class_id 不在 teaching_classes → 403 + 审计日志），验证非任教班级访问被拦截
- [x] 3.3 验证审计日志复用 RBAC 规约的 AuditLog 表，包含完整字段（user_id, role, request_path, method, status_code, ip_address, created_at）
- [x] 3.4 验证审计日志异步写入不影响 403 响应性能

## 4. 前端班级数据渲染控制

- [x] 4.1 实现前端从 JWT 解析 class_id 存入 Zustand store，验证组件可正确读取 class_id
- [x] 4.2 实现前端 API 请求不携带 class_id 参数（由后端从 JWT 提取），验证请求不暴露 class_id
- [x] 4.3 实现前端组件仅渲染当前 class_id 对应的数据，验证不展示其他班级数据

## 5. 多娃切换班级上下文重载

- [x] 5.1 验证切换孩子后新 JWT 中 class_id 更新为新班级，旧 class_id 不再有效
- [x] 5.2 实现切换后 Zustand 业务缓存（作业、AI 历史、错题本）全量清空，验证缓存为空后重新拉取
- [x] 5.3 验证切换后后端使用新 class_id 过滤，旧班级数据不可见
- [x] 5.4 验证切换后前端组件渲染新班级数据，不残留旧班级内容

## 6. 无班级分配边界处理

- [x] 6.1 实现学生 class_id 为 NULL 时前端展示"暂无班级"空状态，验证不发 API 请求
- [x] 6.2 实现学生 class_id 为 NULL 时后端拒绝查询并返回提示，验证不返回任何班级数据
- [x] 6.3 实现教师 teaching_classes 为空时前端展示"暂无任教班级"空状态，验证不发 API 请求
- [x] 6.4 实现教师 teaching_classes 为空时后端拒绝查询并返回提示，验证不返回任何班级数据

## 7. SQLite 并发读取优化

- [x] 7.1 在 FastAPI 启动时执行 PRAGMA journal_mode=WAL，验证 journal_mode 返回 wal
- [x] 7.2 配置 PRAGMA wal_autocheckpoint=1000，验证 WAL 文件大小可控
- [x] 7.3 验证并发 SELECT 不互相阻塞（多用户同时查询不同班级数据）
- [x] 7.4 验证读写不互相阻塞（教师上传资料时学生查询不超时）

## 8. 集成验证

- [x] 8.1 端到端验证：学生登录→查看本班资料/作业/错题本→尝试篡改 class_id 跨班访问被拒 403，验证学生班级隔离完整流程
- [x] 8.2 端到端验证：教师登录→查看任教班级数据→尝试跨班操作被拒 403，验证教师班级隔离完整流程
- [x] 8.3 端到端验证：家长切换孩子（class_id 101→102）→缓存清空→新班级数据加载→旧班级数据不可见，验证多娃切换隔离重载
- [x] 8.4 端到端验证：未分配班级用户访问→前端空状态+后端拒绝查询，验证无班级边界处理
- [x] 8.5 端到端验证：并发场景下多用户查询不同班级数据→互不阻塞→数据隔离正确，验证 SQLite WAL 并发优化
