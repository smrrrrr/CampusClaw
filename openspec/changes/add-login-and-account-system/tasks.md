## 1. 后端基础设施与数据模型

- [x] 1.1 创建 FastAPI 项目骨架（main.py、router 注册、CORS 配置允许 credentials、SMS_MOCK 环境变量读取），验证 `uv run uvicorn main:app` 启动无报错
- [x] 1.2 定义 User 模型（id, role, identifier, password_hash, phone, must_change_password, class_id, created_at, updated_at），对 (role, identifier) 建唯一索引，对 phone 建普通索引，验证表创建成功
- [x] 1.3 定义 VerificationCode 模型（id, phone, code, expires_at, attempt_count, status, created_at），对 phone 建索引，验证表创建成功
- [x] 1.4 定义 LoginAttempt 模型（id, identifier, attempt_count, lock_until, last_attempt_at），对 identifier 建唯一索引，验证表创建成功
- [x] 1.5 配置 SQLite WAL 模式并在启动时自动建表，验证数据库文件生成且表结构正确

## 2. 密码安全与认证工具

- [x] 2.1 实现 bcrypt 密码哈希工具（passlib CryptContext），验证哈希与校验函数可正确 hash/verify
- [x] 2.2 实现密码策略校验函数（最少8位、大小写字母、数字、特殊字符），验证符合/不符合策略的密码分别通过/被拒
- [x] 2.3 实现初始密码生成函数（学校缩写+学号/工号后6位），验证生成的密码符合预期格式
- [x] 2.4 实现 JWT 签发函数（正式 Access Token 2h、Refresh Token 7d、Temp Token 5min），验证三种 Token 的 Payload 字段正确
- [x] 2.5 实现 JWT 校验 FastAPI 依赖（解析 Authorization 头），验证有效 Token 通过、无效/过期 Token 被拒
- [x] 2.6 实现 require_password_changed 依赖（must_change_password=true 时返回 403），验证未改密请求被拦截、改密端点不受影响

## 3. 密码登录与认证 API

- [x] 3.1 实现 POST /api/auth/login 端点（校验 identifier+password、签发双 Token、Set-Cookie Refresh Token），验证教师/学生均能登录成功
- [x] 3.2 实现登录失败锁定逻辑（查询 LoginAttempt、失败累计、5次锁定15分钟、成功清零），验证连续5次失败后锁定、锁定期间拒绝、过期后恢复
- [x] 3.3 统一登录失败提示为"账号或密码错误"，验证密码错误和账号不存在返回相同提示
- [x] 3.4 实现 POST /api/auth/refresh 端点（从 Cookie 读 Refresh Token、签发新 Access Token），验证过期 Access Token 可自动刷新
- [x] 3.5 实现 POST /api/auth/change-password 端点（校验旧密码、校验新密码策略、bcrypt 哈希、置 must_change_password=false、重新签发 Token），验证改密成功后 must_change_password 变为 false
- [x] 3.6 实现 POST /api/auth/logout 端点（清除 HttpOnly Cookie），验证登出后 Cookie 被清除

## 4. 验证码登录 API

- [x] 4.1 实现 POST /api/auth/send-code 端点（生成6位随机码、存入 VerificationCode 表有效期5分钟、SMS_MOCK=true 时在响应中返回验证码），验证验证码生成成功且 Mock 模式返回验证码
- [x] 4.2 实现验证码防刷逻辑（60秒限制、每日10次限制、跨日重置），验证 60 秒内重复发送被拒、第 11 次被拒、次日重置
- [x] 4.3 实现 POST /api/auth/verify-code 端点（校验验证码、查询该手机号绑定的学生列表），验证单娃直接签发 JWT、多娃返回 Temp Token+学生列表、未绑定学生返回提示
- [x] 4.4 实现验证码错误5次作废逻辑，验证第5次错误后验证码状态变为 invalidated，需重新发送
- [x] 4.5 实现 POST /api/auth/select-student 端点（校验 Temp Token、验证 student_id 属于该手机号、签发正式 JWT），验证选择成功后 JWT 的 user_id 为所选学生 ID
- [x] 4.6 验证 Temp Token 无效/过期被拒、选择的 student_id 不属于该手机号被拒

## 5. CSV 导入与账号预置

- [x] 5.1 实现 POST /api/teacher/import-students 端点（接收 CSV 文件、csv.DictReader 解析、校验表头含"学号"列），验证格式不符时拒绝并返回错误
- [x] 5.2 实现逐行处理逻辑（创建/复用学生账号、若含手机号列则写入 phone 字段），全部在单事务中执行，验证含手机号的学生账号 phone 字段正确写入
- [x] 5.3 实现任一行失败时全事务回滚，验证部分行错误时整个导入回滚、不创建任何账号
- [x] 5.4 实现同一手机号绑定多个学生账号的逻辑，验证 CSV 中两行使用同一手机号时两个学生账号的 phone 字段均正确

## 6. 切换孩子与教师功能 API

- [x] 6.1 实现 POST /api/auth/switch-student 端点（用 Refresh Token 中的 phone 重新查询学生列表、签发新 Temp Token），验证多娃家长可获取学生列表
- [x] 6.2 验证单娃家长调用切换端点返回提示或空列表
- [x] 6.3 验证 Refresh Token 过期时切换端点返回认证失效
- [x] 6.4 实现 POST /api/teacher/reset-password 端点（重置为初始密码、置 must_change_password=true），验证重置后密码可登录且 must_change_password=true

## 7. 前端状态管理与基础设施

- [x] 7.1 创建 Zustand store（access_token, current_student_info, user_role, must_change_password, is_phone_login），验证 store 可正确读写和 reset
- [x] 7.2 实现 HTTP 请求拦截器（注入 Authorization 头、401 自动调用 refresh），验证过期 Access Token 自动刷新成功
- [x] 7.3 实现前端路由守卫（未登录→登录页、密码登录且 must_change_password=true→改密页、验证码登录跳过改密页），验证各状态跳转正确

## 8. 前端页面

- [x] 8.1 实现登录页（双 Tab：密码登录/验证码登录、密码登录表单、验证码登录表单含发送验证码按钮、忘记密码提示"请联系班主任"），验证两种登录方式均能登录、忘记密码显示提示
- [x] 8.2 实现改密页（旧密码+新密码+确认密码、策略提示），验证不符合策略的密码被拒、符合的改密成功
- [x] 8.3 实现多娃选择弹窗（学生列表含 id/name/class_name、选择后调用 select-student），验证列表>1显示弹窗、列表=1直接进入、列表=0显示提示
- [x] 8.4 实现"切换孩子"按钮（仅多娃家长可见、点击调 switch-student 端点、重新展示选择列表），验证切换后页面刷新为新孩子数据
- [x] 8.5 实现登出功能（清除 Zustand 状态、调 /logout 清除 Cookie、重定向登录页），验证登出后状态全部清空

## 9. 集成验证

- [x] 9.1 端到端验证：教师上传 CSV 导入学生（含手机号）→学生用学号+初始密码登录→强制改密→改密后正常访问，验证完整流程
- [x] 9.2 端到端验证：家长输入手机号发送验证码→输入验证码→单娃直接登录或多娃选择→进入系统，验证完整验证码登录流程
- [x] 9.3 端到端验证：多娃家长登录→点击切换孩子→选择另一个孩子→页面刷新，验证切换流程
- [x] 9.4 验证验证码防刷（60秒限制、每日10次、错误5次作废）全部生效
- [x] 9.5 验证密码登录失败5次锁定15分钟，过期后自动恢复
- [x] 9.6 验证同一账号多端登录不互踢，登出仅清除当前端状态
- [x] 9.7 验证 SMS_MOCK=true 时验证码在 API 响应中返回，SMS_MOCK=false 时不返回
