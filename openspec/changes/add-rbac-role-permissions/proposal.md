## Why

CampusClaw 的登录与账号体系已定义双角色（teacher/student）和 JWT 会话管理，但尚未定义"谁能做什么"和"能看到什么数据"的行为契约。没有角色权限矩阵和数据隔离规则，班级管理、资料上传、作业批改、AI 解题等核心业务功能无法安全落地——教师可能越权操作非任教班级的数据，学生可能越权查看同班甚至兄弟姐妹的数据。本变更为系统引入完整的 RBAC 规约，覆盖角色定义、功能权限矩阵、页面级与接口级双重校验、行列级数据隔离、多娃切换状态重载、越权处理与审计日志，确保实现时有完整的、可验证的行为契约。

## What Changes

- 明确系统仅包含教师（teacher）和学生（student）两种底层角色，家长通过验证码登录学生账号后享有学生全部权限，系统不感知家长身份。
- 引入教师功能权限矩阵：班级管理（创建/管理任教班级，拥有 teaching_classes 列表如 [101, 102]）、资料与作业（上传资料、布置作业、批改作业、查看本班所有学生数据）、AI解题（查看本班学生 AI 提问历史用于了解薄弱知识点，但不可代替学生发起提问）、账号管理（重置本班学生密码、查看学生信息）。
- 引入学生功能权限矩阵（含家长代登录享有同等权限）：学习功能（查看本班资料、提交作业、查看个人错题本、修改个人密码）、AI解题（发起提问、查看自己的提问历史、将 AI 解答加入错题本，每日上限 20 次，限制绑定 student_id）。
- 引入前端路由级权限拦截：Next.js middleware.ts 拦截 /teacher/* 仅教师可访问、/student/* 仅学生可访问，越权跳转 403 提示页。
- 引入后端接口级权限拦截：FastAPI Depends 依赖注入 Depends(get_current_teacher) 拦截教师接口、Depends(get_current_student) 拦截学生接口，越权返回 403 Forbidden。
- 引入教师数据权限隔离：JWT Payload 增加 teaching_classes 字段（任教班级 ID 列表），后端所有涉及班级数据的查询带 WHERE class_id IN (teaching_classes)，教师不能跨班操作。
- 引入学生数据权限隔离：后端所有涉及学生个人数据的查询带 WHERE student_id = :current_user_id，学生（含家长代登录）不能越权查看其他学生数据（包括兄弟姐妹）。
- 引入教师多班级操作交互约束：前端提供班级选择器，后端校验目标 class_id 是否在 teaching_classes 范围内，否则返回 403。
- 引入多娃切换权限与状态重载：切换孩子时签发新 JWT（user_id 为新学生 ID），前端 Zustand 业务缓存（作业、AI 历史、错题本）全量清空并重新拉取，后端使用新 student_id 进行数据隔离。
- 引入权限变更生效机制：SQLite 轻量级方案，不引入实时消息推送，角色或权限变更需用户重新登录或通过 Refresh Token 刷新后生效。
- 引入越权处理与审计日志：前端跳转 403 无权限提示页，后端返回 403 Forbidden 并记录审计日志（含 user_id、role、请求路径、方法、状态码、时间戳、IP）。
- 扩展 User 表：增加 teaching_classes 字段（JSON 数组，仅教师使用，存储任教班级 ID 列表）。
- 扩展 JWT Payload：教师 Token 增加 teaching_classes 字段。
- 新增 AuditLog 表：存储越权行为审计记录。

## Capabilities

### New Capabilities
- `rbac-role-permissions`: 角色权限体系，覆盖双角色定义、教师与学生功能权限矩阵、前端路由级与后端接口级双重校验、教师任教班级数据隔离、学生个人数据隔离、多娃切换权限与状态重载、AI 提问次数限制、权限变更生效机制、越权处理与审计日志。

### Modified Capabilities
- `login-and-account-system`: JWT Payload 扩展——教师 Token 增加 teaching_classes 字段用于后端数据隔离校验；User 表扩展 teaching_classes 字段存储教师任教班级列表。

## Impact

- **后端 (FastAPI)**：扩展 User 模型（增加 teaching_classes JSON 字段）；扩展 JWT 签发逻辑（教师 Token 包含 teaching_classes）；新增权限依赖函数（get_current_teacher、get_current_student、get_current_user）；新增 AuditLog 模型与审计日志异步写入机制；所有涉及班级/学生数据的查询增加 WHERE 隔离条件；新增 AI 提问次数限制校验逻辑。
- **前端 (Next.js)**：新增 middleware.ts 路由守卫（基于 role 拦截 /teacher/* 和 /student/*）；扩展 Zustand store（增加 teaching_classes 字段、多娃切换时全量清空业务缓存）；新增 403 无权限提示页；新增教师班级选择器组件。
- **数据库 (SQLite)**：User 表增加 teaching_classes 字段；新增 AuditLog 表（id, user_id, role, request_path, method, status_code, ip_address, created_at）。
- **部署 (Docker)**：无需新增基础设施组件，SQLite 文件挂载不变。
