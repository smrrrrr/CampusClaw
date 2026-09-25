## Why

CampusClaw 需要一个封闭式账号体系作为所有业务能力的前置基础：没有可信的"谁登录了"和"以什么身份操作"，班级隔离、资料上传、作业批改等后续能力都无法安全落地。本变更为系统引入从账号预置、双方式登录（密码+验证码）、会话管理到手机号多娃绑定的端到端规约，确保实现时有完整的、可验证的行为契约。

## What Changes

- 引入双角色封闭账号体系（teacher / student），**完全禁止自助注册**，账号由管理员或教师通过 CSV 批量预置。
- 引入两种登录方式：方式一为学号/工号 + 密码；方式二为手机号 + 短信验证码（便捷登录，面向家长）。
- 家长通过手机号验证码登录学生账号，登录后功能与学生完全一致——系统不创建独立的家长角色。
- 引入手机号绑定机制：User 表增加 phone 字段（非唯一），同一手机号可绑定多个学生账号。
- 引入验证码登录多娃选择流程：验证码校验通过后查询该手机号绑定的学生列表，1个直接签发 JWT，多个返回 Temp Token + 学生列表供选择。
- 引入切换孩子交互：多娃家长登录后可通过顶部按钮重新选择孩子。
- 引入初始密码规则：学校三位缩写（全小写）+ 学号/工号后6位。验证码登录无初始密码概念。
- 引入强制首次改密：must_change_password = true，FastAPI 中间件拦截未改密请求。
- 引入密码安全策略：最少 8 位，含大小写字母、数字、特殊字符，bcrypt 哈希加盐存储。
- 引入 JWT 会话：Access Token 2 小时、Refresh Token 7 天（HttpOnly Cookie），Payload 含 user_id / role / class_id / must_change_password。
- 引入验证码防刷：同一手机号 60 秒内一次、每天 10 次上限、错误 5 次作废，全 SQLite 实现。
- 引入密码登录失败锁定：连续 5 次锁定 15 分钟（LoginAttempt 表）。
- 引入教师重置学生密码能力：重置为初始密码并重新置 must_change_password = true。
- 引入登出机制：前端清除 Token，后端清除 HttpOnly Cookie。
- 引入多端在线策略：无状态 JWT，允许同账号多端同时在线。
- 开发阶段 SMS Mock 模式（SMS_MOCK=true）：验证码直接返回在 API 响应中，不接真实短信服务。

## Capabilities

### New Capabilities
- `login-and-account-system`: 封闭式双角色账号体系，覆盖账号 CSV 预置、密码+验证码双方式登录、初始密码与强制改密、密码安全策略、JWT 会话管理、手机号多娃绑定与选择、验证码防刷、登录失败锁定、教师重置密码、多端在线与登出。

### Modified Capabilities
<!-- 无已有 spec，本次为全新能力 -->

## Impact

- **后端 (FastAPI)**：新增 User 表（含 phone 字段）、VerificationCode 表、LoginAttempt 表；新增认证中间件（JWT 校验 + 强制改密拦截）；新增密码登录、验证码发送、验证码登录、选择学生、刷新 Token、登出、改密等 API 端点；新增 CSV 导入时自动绑定手机号逻辑。
- **前端 (Next.js)**：新增登录页（双 Tab：密码登录/验证码登录）、改密页、多娃选择弹窗、切换孩子交互；引入全局状态管理（Context/Zustand）存储 Access Token 与当前选中的 student 信息；引入请求拦截器统一携带 Token；引入路由守卫处理未登录/未改密跳转。
- **数据库 (SQLite)**：新增/扩展 User 表（phone 字段、must_change_password 字段）、VerificationCode 表（phone, code, expires_at, attempt_count）、LoginAttempt 表（identifier, attempt_count, lock_until）。
- **依赖**：新增 JWT 库（python-jose）、bcrypt 库（passlib）；验证码发送开发阶段用 Mock，生产环境预留短信服务接口。
- **部署 (Docker)**：无需新增基础设施组件（无 Redis），SQLite 文件挂载不变，SMS_MOCK 环境变量控制验证码发送模式。
