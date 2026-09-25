## Context

CampusClaw 的登录与账号体系（add-login-and-account-system）已定义双角色（teacher/student）、JWT 会话管理（Access Token 2h / Refresh Token 7d / Temp Token 5min）和手机号验证码多娃登录流程。本设计为"角色权限（RBAC）"规约中定义的全部行为提供技术实现方案，重点解决角色功能矩阵、双重权限校验、行列级数据隔离、多娃切换状态重载和越权审计。详见 proposal.md - Why。

## Goals / Non-Goals

**Goals:**

- 确定 teaching_classes 的数据结构与存储方式
- 确定 JWT Payload 扩展方案（教师 Token 增加 teaching_classes）
- 确定 FastAPI 权限依赖函数（get_current_teacher / get_current_student）的实现方案
- 确定数据隔离的查询级 WHERE 过滤方案
- 确定前端 Next.js middleware.ts 路由守卫方案
- 确定多娃切换时 Zustand 状态重载方案
- 确定 AuditLog 审计日志表与异步写入方案
- 确定 AI 提问次数限制的计数方案

**Non-Goals:**

- 不引入 RBAC 中间件框架（如 Casbin），使用 FastAPI 原生 Depends
- 不实现 ORM 级别的行级权限自动注入，使用查询级 WHERE 过滤
- 不引入实时权限推送（WebSocket / SSE）
- 不实现细粒度按钮级权限控制（仅页面级 + 接口级）
- 不实现权限组或自定义角色（仅固定两种角色）
- 不实现 Token 黑名单或主动失效（沿用登录体系的无状态 JWT）

## Decisions

### 1. teaching_classes 存储：User 表 JSON 字段

在 User 表增加 `teaching_classes` 字段（TEXT 类型，存储 JSON 数组，如 `[101, 102]`）。仅教师用户使用此字段，学生用户此字段为 NULL。选择 JSON 字段而非独立关联表的原因：教师任教班级数量有限（通常 1-5 个），JSON 数组读写简单，避免多表 JOIN 开销。JWT 签发时从此字段读取并写入 Payload。

**替代方案**：独立 TeacherClass 关联表。**未选原因**：增加查询复杂度，班级数量少无需关联表规范。

### 2. JWT Payload 扩展

教师 Access Token Payload 增加 `teaching_classes` 字段（整数数组）。完整教师 Payload：`{user_id, role: "teacher", class_id: null, teaching_classes: [101, 102], must_change_password}`。学生 Payload 保持不变：`{user_id, role: "student", class_id: 101, must_change_password}`。Refresh Token 同步扩展（用于刷新时重新签发含 teaching_classes 的 Access Token）。

### 3. FastAPI 权限依赖函数

定义三个依赖函数：

- `get_current_user`：解析 JWT，返回 user_id / role / class_id / teaching_classes / must_change_password。所有需认证的接口共用。
- `get_current_teacher`：调用 get_current_user，校验 role == "teacher"，否则 raise 403。
- `get_current_student`：调用 get_current_user，校验 role == "student"，否则 raise 403。

数据隔离校验在接口业务逻辑中完成（非依赖函数中），因为不同接口的隔离条件不同（教师按 class_id，学生按 student_id）。

### 4. 数据隔离：查询级 WHERE 过滤

不使用 ORM 行级权限自动注入。开发者在每个查询中显式添加 WHERE 条件：

- 教师查询：`WHERE class_id IN (teaching_classes)`，teaching_classes 从 JWT Payload 获取。
- 学生查询：`WHERE student_id = :current_user_id`，current_user_id 从 JWT Payload 的 user_id 获取。

后端 MUST NOT 信任请求体参数中的 class_id 或 student_id，MUST 以 JWT Payload 为唯一可信来源。

**替代方案**：ORM 级行级权限（如 SQLAlchemy event listener 自动注入 WHERE）。**未选原因**：增加隐式行为复杂度，显式 WHERE 更易审计和调试。

### 5. 前端路由守卫：Next.js middleware.ts

middleware.ts 匹配 `/teacher/*` 和 `/student/*` 路由。从请求 Cookie 或内存 Token 中解析 role 字段：

- `/teacher/*` 路由：role != "teacher" → 重定向到 /403
- `/student/*` 路由：role != "student" → 重定向到 /403
- 无 Token 或 Token 无效 → 重定向到 /login

前端 403 页面为 `/403`，展示"您无权访问该页面"提示和返回首页按钮。

### 6. 前端状态重载：Zustand store

Zustand store 扩展字段：`teaching_classes`（教师用）。多娃切换时调用 `resetBusinessState()` 方法，清空以下缓存：

- 作业列表
- AI 提问历史
- 错题本列表
- 班级相关数据

清空后立即触发数据重新拉取（useEffect 或页面级数据请求）。Access Token 同步替换为新 JWT。

### 7. AuditLog 表与异步写入

**AuditLog 表**：`id（主键）、user_id、role、request_path、method、status_code、ip_address、created_at`。

**异步写入**：使用 FastAPI BackgroundTasks 在返回 403 响应后异步写入审计日志。审计日志写入失败 MUST NOT 影响主请求流程（catch-and-log）。

查询审计日志时按 user_id / request_path / created_at 范围过滤，支持按角色和状态码筛选。

### 8. AI 提问次数限制实现

在 SQLite 中通过查询 AI 提问记录表（后续业务规约定义）按 student_id + 当日日期范围计数实现。每次提问前查询当日次数，达到 20 则拒绝。限制绑定 student_id 而非手机号，确保多娃切换后独立计算。次日自动重置（查询条件为当天 0:00 至当前，跨自然日自动从 0 开始）。

## Risks / Trade-offs

- **[查询级隔离依赖开发者自觉]** → 不使用 ORM 自动注入，开发者可能遗漏 WHERE 条件导致数据泄露。**缓解**：代码审查重点关注数据查询是否带隔离条件；后续可引入 SQLAlchemy event listener 做自动注入作为安全网。

- **[权限生效延迟最长 2 小时]** → 权限变更后需等 Access Token 过期刷新才生效，最长延迟 2 小时。**缓解**：校园场景权限变更低频，2 小时延迟可接受；紧急场景可通知用户重新登录。

- **[JWT Payload 变大]** → 教师 Token 增加 teaching_classes 数组，Token 体积增大。**缓解**：教师任教班级数量有限（通常 1-5 个），对 Token 大小影响可忽略。

- **[审计日志 SQLite 写入性能]** → 高频越权请求可能产生大量审计日志写入。**缓解**：异步写入不阻塞响应；校园级并发有限；可定期清理超过 90 天的审计日志。

- **[前端缓存清空导致闪烁]** → 多娃切换时全量清空缓存重新拉取，页面短暂空白。**缓解**：展示 loading 状态；切换是低频操作，用户体验影响可控。
