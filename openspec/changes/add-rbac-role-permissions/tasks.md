## 1. 数据模型扩展

- [x] 1.1 在 User 模型增加 teaching_classes 字段（TEXT 类型存储 JSON 数组，默认 NULL），验证教师记录可正确存储和读取 [101, 102] 格式
- [x] 1.2 创建 AuditLog 模型（id, user_id, role, request_path, method, status_code, ip_address, created_at），验证表创建成功
- [x] 1.3 配置 AuditLog 表按 created_at 建索引，验证按时间范围查询效率

## 2. JWT Payload 扩展

- [x] 2.1 扩展 JWT 签发函数：教师 Access Token Payload 增加 teaching_classes 字段，验证教师 Token 解码后包含 teaching_classes
- [x] 2.2 扩展 Refresh Token Payload：教师 Refresh Token 增加 teaching_classes，验证刷新后新 Access Token 包含正确的 teaching_classes
- [x] 2.3 验证学生 Token Payload 不包含 teaching_classes 字段，保持不变

## 3. 后端权限依赖函数

- [x] 3.1 实现 get_current_user 依赖（解析 JWT、返回 user_id/role/class_id/teaching_classes/must_change_password），验证有效 Token 正确解析
- [x] 3.2 实现 get_current_teacher 依赖（调用 get_current_user、校验 role=="teacher"、失败 raise 403），验证教师通过、学生被拒
- [x] 3.3 实现 get_current_student 依赖（调用 get_current_user、校验 role=="student"、失败 raise 403），验证学生通过、教师被拒
- [x] 3.4 验证无效/过期 Token 调用权限依赖时返回 401 而非 403

## 4. 数据隔离查询

- [x] 4.1 在教师查询班级数据的接口中实现 WHERE class_id IN (teaching_classes) 隔离，验证教师只能查询任教班级数据
- [x] 4.2 在学生查询个人数据的接口中实现 WHERE student_id = :current_user_id 隔离，验证学生只能查询自己的数据
- [x] 4.3 验证后端不信任请求体中的 class_id / student_id 参数，以 JWT Payload 为准
- [x] 4.4 验证教师跨班操作（class_id 不在 teaching_classes 中）返回 403

## 5. 审计日志

- [x] 5.1 实现审计日志异步写入工具（FastAPI BackgroundTasks），验证越权请求返回 403 后异步写入 AuditLog
- [x] 5.2 验证审计日志包含 user_id、role、request_path、method、status_code、ip_address、created_at 字段
- [x] 5.3 验证审计日志写入失败不影响主请求响应（catch-and-log）
- [x] 5.4 实现审计日志查询接口（按 user_id / request_path / created_at 范围 / role / status_code 筛选），验证查询结果正确

## 6. 前端路由守卫

- [x] 6.1 实现 Next.js middleware.ts 路由拦截（/teacher/* 仅教师、/student/* 仅学生、未登录重定向登录页），验证各角色跳转正确
- [x] 6.2 创建 /403 无权限提示页（展示"您无权访问该页面"和返回首页按钮），验证越权访问跳转到该页面
- [x] 6.3 验证未登录用户访问 /teacher/* 和 /student/* 均重定向到登录页

## 7. 前端状态管理与多娃切换重载

- [x] 7.1 扩展 Zustand store 增加 teaching_classes 字段（教师用），验证 store 可正确读写
- [x] 7.2 实现 resetBusinessState() 方法（清空作业列表、AI 历史、错题本、班级数据缓存），验证调用后缓存为空
- [x] 7.3 在多娃切换成功后调用 resetBusinessState() 并重新拉取数据，验证页面刷新为新孩子数据
- [x] 7.4 验证切换后旧 Access Token 被替换为新 Token，残留旧 Token 请求被拦截

## 8. 教师班级选择器

- [x] 8.1 实现班级选择器组件（从 teaching_classes 读取并展示任教班级列表），验证多班级教师看到所有任教班级
- [x] 8.2 在教师上传资料、布置作业等操作页面集成班级选择器，验证选择班级后 class_id 正确传入后端
- [x] 8.3 验证教师选择非任教班级（篡改请求）时后端返回 403

## 9. AI 提问次数限制

- [x] 9.1 实现 AI 提问当日次数计数（按 student_id + 当日日期范围查询），验证当日提问次数正确累计
- [x] 9.2 实现达到 20 次上限拒绝并返回提示，验证第 21 次提问被拒
- [x] 9.3 验证跨自然日后计数自动重置
- [x] 9.4 验证多娃切换后按新 student_id 独立计算，不受前一孩子影响

## 10. 集成验证

- [x] 10.1 端到端验证：教师登录→访问 /teacher/* 路由通过→管理任教班级→查看本班学生数据→尝试跨班操作被拒 403，验证教师完整权限流程
- [x] 10.2 端到端验证：学生登录→访问 /student/* 路由通过→查看资料/提交作业/发起 AI 提问→尝试查看他人数据被拒 403，验证学生完整权限流程
- [x] 10.3 端到端验证：家长验证码登录学生账号→享有学生全部权限→切换孩子→缓存清空重新拉取→新孩子数据隔离，验证多娃切换完整流程
- [x] 10.4 端到端验证：学生发起 20 次 AI 提问→第 21 次被拒→次日重置，验证提问次数限制
- [x] 10.5 端到端验证：越权访问（学生访问教师路由/接口、教师跨班操作）→前端跳转 403 页/后端返回 403→审计日志记录正确，验证越权处理与审计
- [x] 10.6 验证权限变更（调整 teaching_classes）后重新登录或 Refresh Token 刷新后新权限生效
