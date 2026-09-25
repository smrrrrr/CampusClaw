## Context

CampusClaw 当前为全新项目，无已有认证体系。技术栈已确定：前端 Next.js，后端 FastAPI（uv 管理环境），数据库 SQLite，Docker 部署。无 Redis，开发阶段不接真实短信服务（SMS_MOCK=true）。本设计为"登录与账号体系"规约中定义的全部行为提供技术实现方案。详见 proposal.md - Why。

## Goals / Non-Goals

**Goals:**

- 提供完整的数据模型设计（User、VerificationCode、LoginAttempt 三张表）
- 确定 JWT 双 Token + Temp Token 的签发、校验与刷新方案
- 确定密码安全（bcrypt、策略校验、强制改密中间件）的实现方式
- 确定验证码生成、存储、防刷与 Mock 模式的实现方式
- 确定手机号多娃选择与切换孩子的前后端交互流程
- 确定前端路由守卫与全局状态管理方案

**Non-Goals:**

- 不实现角色权限矩阵和班级隔离（后续独立规约覆盖）
- 不实现资料上传、作业批改等业务功能
- 不引入 Redis 或任何外部缓存服务
- 不接真实短信服务（生产环境预留接口，开发阶段用 Mock）
- 不实现 OAuth/SSO 第三方登录
- 不实现 Token 黑名单或主动失效机制（无状态 JWT）
- 不创建独立的家长角色——家长通过手机号验证码登录学生账号

## Decisions

### 1. 数据模型：三表设计

**User 表**：统一存储两种角色。字段：id（主键）、role（teacher/student）、identifier（学号/工号）、password_hash（bcrypt）、phone（手机号，非唯一，加索引）、must_change_password（布尔，默认 true）、class_id（外键→班级，学生必填，教师可空）、created_at、updated_at。对 (role, identifier) 建唯一索引。phone 非唯一因为同一手机号可绑定多个学生。

**VerificationCode 表**：验证码存储与防刷。字段：id（主键）、phone（手机号）、code（6位随机数字）、expires_at（过期时间）、attempt_count（错误次数，默认0）、status（pending/used/invalidated）、created_at。查询时按 phone + status=pending 取最新一条。每日发送次数通过按 phone + created_at 范围查询计数实现。

**LoginAttempt 表**：密码登录失败锁定。字段：id（主键）、identifier（学号/工号）、attempt_count（整数）、lock_until（时间戳或 NULL）、last_attempt_at。按 identifier 唯一索引。

**替代方案**：将验证码存 Redis。**未选原因**：无 Redis 基础设施，SQLite 足以支撑校园级并发。

### 2. JWT 三种令牌策略

**正式 Access Token**：有效期 2 小时，Payload 含 user_id/role/class_id/must_change_password。存放在前端内存（Zustand）。

**Refresh Token**：有效期 7 天，存放在 HttpOnly Cookie。Payload 含 phone（用于多娃切换时重新查询学生列表）或 user_id。刷新时签发新的 Access Token。

**Temp Token**：有效期 5 分钟，仅在多娃选择流程中使用。Payload 含 phone，不含 user_id（因为尚未选择学生）。用户选择学生后用 Temp Token + student_id 换取正式 JWT。

切换孩子流程：使用已登录的 Refresh Token（含 phone）调切换端点，后端用 phone 重新查询学生列表并签发新的 Temp Token，前端重新展示选择列表，用户选择后换取新 JWT。

### 3. 验证码生成与 Mock 模式

生成 6 位随机数字验证码，存入 VerificationCode 表（expires_at = now + 5分钟）。SMS_MOCK=true 时验证码直接在 API 响应 JSON 中返回（如 `{"code": "123456", "message": "验证码已发送"}`）。生产环境预留 SMS 服务接口（通过环境变量 SMS_PROVIDER 配置），Mock 模式下跳过实际发送。

### 4. 验证码防刷实现

- **60 秒限制**：发送前查询该 phone 最近一条 pending 验证码的 created_at，若距今 < 60 秒则拒绝。
- **每日 10 次限制**：按 phone 查询当天 0:00 至当前的记录数，达到 10 则拒绝。跨自然日自动重置（因为查询条件是当天范围）。
- **错误 5 次作废**：每次错误验证 attempt_count +1，达到 5 则将 status 置为 invalidated。

### 5. 密码安全：bcrypt + passlib

使用 passlib 的 bcrypt 实现。初始密码生成后立即 bcrypt 哈希存储。改密时正则校验（8+ 位、大小写字母、数字、特殊字符），通过后 bcrypt 哈希存入 password_hash。

### 6. 强制改密中间件：FastAPI 依赖注入

定义 FastAPI 依赖函数，从 JWT 中读取 must_change_password，若为 true 则返回 403。改密端点、登出端点、验证码相关端点显式排除该依赖。验证码登录不触发强制改密（JWT 中 must_change_password 仍为 true 但验证码登录端点返回的 Token 中该字段不影响——前端通过判断登录方式决定是否跳转改密页）。

**设计决策**：验证码登录时后端签发的 JWT 中 must_change_password 保持原值，但前端登录逻辑不因 must_change_password=true 跳转改密页（因为验证码登录无密码概念）。密码登录时仍按 must_change_password 决定跳转。

### 7. CSV 导入：Python 标准库 csv 模块

使用 csv.DictReader 解析上传的 CSV。逐行处理：创建/复用学生账号，若含手机号列则写入 phone 字段。全部操作在单事务中执行，任一行失败则回滚。详见 spec 中的 CSV 相关场景。

### 8. 前端状态管理：Zustand

使用 Zustand 存储：access_token、current_student_info（id/name/class_id）、user_role、must_change_password、is_phone_login（标记是否验证码登录，用于决定是否跳转改密页）。请求拦截器从 store 读取 access_token 注入 Authorization 头。路由守卫根据登录状态、must_change_password + is_phone_login、current_student_info 决定跳转。

## Risks / Trade-offs

- **[JWT 不可主动失效]** → 无状态 JWT 意味着登出后 Token 在过期前仍有效。**缓解**：Access Token 仅 2 小时；多端在线是产品需求。未来需要主动失效可引入 Redis 黑名单。

- **[SQLite 并发写入]** → 验证码发送与登录失败计数并发写入可能竞争。**缓解**：校园级应用并发量有限；启用 WAL 模式；VerificationCode 和 LoginAttempt 按 phone/identifier 索引减少竞争。

- **[初始密码可预测]** → 基于学号生成，未及时修改有风险。**缓解**：强制首次改密（密码登录路径）；验证码登录无密码概念，不受影响。

- **[Temp Token 安全窗口]** → Temp Token 5 分钟有效期内可被截获用于选择学生。**缓解**：Temp Token 仅能选择该手机号绑定的学生，无法越权选择；有效期短。

- **[Mock 模式验证码泄露]** → SMS_MOCK=true 时验证码在 API 响应中返回。**缓解**：仅在开发环境启用，生产环境 SMS_MOCK=false 时验证码不出现在响应中。
