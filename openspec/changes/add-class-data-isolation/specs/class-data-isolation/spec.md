## Purpose

为 CampusClaw 提供班级数据隔离行为契约，覆盖隔离模型（class_id 字段规范）、隔离范围界定、教师与学生班级数据访问控制、多娃切换班级上下文重载、后端查询强制隔离、前端渲染控制、无班级边界处理、跨班访问拦截与审计、SQLite 并发优化，确保班级数据在共享数据库中严格按 class_id 隔离，不发生跨班泄露。

## ADDED Requirements

### Requirement: 班级数据隔离模型与字段规范

系统 MUST 采用共享数据库 + class_id 字段过滤的隔离策略。所有与班级相关的数据表 MUST 包含 class_id 字段（整数类型，非 NULL，外键关联班级表）。需包含 class_id 字段的表 MUST 至少覆盖：班级资料表、作业布置表、作业提交记录表、AI 提问记录表、错题本表。class_id 字段 MUST 建索引以提升隔离查询性能。记录创建后 class_id MUST NOT 变更。

#### Scenario: 班级资料表按 class_id 隔离

- **WHEN** 系统创建班级资料表
- **THEN** 该表 MUST 包含 class_id 字段（INTEGER, 非 NULL, 建索引），查询资料时按 class_id 过滤

#### Scenario: 作业布置表按 class_id 隔离

- **WHEN** 系统创建作业布置表
- **THEN** 该表 MUST 包含 class_id 字段（INTEGER, 非 NULL, 建索引），教师布置作业时关联到任教班级

#### Scenario: 作业提交记录表按 class_id 隔离

- **WHEN** 系统创建作业提交记录表
- **THEN** 该表 MUST 包含 class_id 字段（INTEGER, 非 NULL, 建索引），学生提交作业时记录所在班级

#### Scenario: AI 提问记录表按 class_id 隔离

- **WHEN** 系统创建 AI 提问记录表
- **THEN** 该表 MUST 包含 class_id 字段（INTEGER, 非 NULL, 建索引），AI 提问记录关联到学生所在班级

#### Scenario: 错题本表按 class_id 隔离

- **WHEN** 系统创建错题本表
- **THEN** 该表 MUST 包含 class_id 字段（INTEGER, 非 NULL, 建索引），错题记录关联到学生所在班级

### Requirement: 隔离数据范围界定

系统 MUST 严格隔离以下数据：班级资料、作业布置、作业提交记录、AI 提问历史、错题本。系统 MUST NOT 隔离以下数据：系统公告、学校级公共资源、用户账号基础信息。

#### Scenario: 班级资料严格隔离

- **WHEN** 班级 101 的学生请求查看资料列表
- **THEN** 系统仅返回 class_id=101 的资料，不返回其他班级的资料

#### Scenario: 系统公告不隔离

- **WHEN** 任何班级的用户请求查看系统公告
- **THEN** 系统返回所有系统公告，不按 class_id 过滤

#### Scenario: 学校级公共资源不隔离

- **WHEN** 任何班级的用户请求查看学校级公共资源
- **THEN** 系统返回所有公共资源，不按 class_id 过滤

#### Scenario: 用户账号基础信息不隔离

- **WHEN** 用户查看自己的账号基础信息（姓名、学号等）
- **THEN** 系统返回该用户的账号信息，不按 class_id 过滤

### Requirement: 教师班级数据范围控制

教师 MUST 只能查看和操作自己任教班级（teaching_classes 列表）范围内的数据。跨班访问 MUST 直接拒绝并返回 403 Forbidden。teaching_classes 来源于 JWT Payload，后端 MUST NOT 信任请求参数中的 class_id。

#### Scenario: 教师查看任教班级资料成功

- **WHEN** 教师 teaching_classes=[101,102]，请求查看班级 101 的资料列表
- **THEN** 系统返回 class_id IN (101,102) 范围内的资料

#### Scenario: 教师查看非任教班级资料被拒

- **WHEN** 教师 teaching_classes=[101,102]，请求查看班级 201 的资料
- **THEN** 系统校验 201 不在 teaching_classes 中，返回 403 Forbidden

#### Scenario: 教师跨班布置作业被拒

- **WHEN** 教师 teaching_classes=[101,102]，尝试为班级 201 布置作业
- **THEN** 系统拒绝该操作并返回 403 Forbidden

### Requirement: 学生班级数据范围控制

学生（含家长代登录）MUST 只能查看和操作自己所在班级（class_id）的数据。学生 MUST NOT 查看其他班级的任何信息。class_id 来源于 JWT Payload，后端 MUST NOT 信任请求参数中的 class_id。

#### Scenario: 学生查看本班资料成功

- **WHEN** 学生 class_id=101，请求查看资料列表
- **THEN** 系统返回 class_id=101 的资料，不返回其他班级的资料

#### Scenario: 学生尝试查看其他班级资料被拒

- **WHEN** 学生 class_id=101，尝试在请求参数中传入 class_id=102 查看资料
- **THEN** 系统以 JWT 中的 class_id=101 为准，返回 403 Forbidden

#### Scenario: 学生提交作业关联到本班

- **WHEN** 学生 class_id=101 提交一份作业
- **THEN** 系统将作业提交记录关联到 class_id=101，不允许篡改为其他班级

### Requirement: 多娃切换班级上下文重载

家长从"小明（class_id=101）"切换到"小红（class_id=102）"时，系统 MUST 签发新 JWT 且 class_id MUST 立即更新为 102。前端 Zustand 中的业务缓存（作业、AI 历史、错题本）MUST 全部清空。后续所有 API 请求的数据过滤条件 MUST 由新的 class_id 驱动。系统 MUST NOT 出现"切换后还能看到旧班级数据"的情况。

#### Scenario: 切换孩子后 class_id 更新

- **WHEN** 家长从 class_id=101 的孩子切换到 class_id=102 的孩子
- **THEN** 新 JWT 中 class_id 为 102，旧 JWT 中的 class_id=101 不再有效

#### Scenario: 切换后前端缓存全量清空

- **WHEN** 家长切换孩子成功后
- **THEN** 前端 Zustand 中的作业列表、AI 提问历史、错题本等业务缓存全部清空，立即以新 class_id=102 拉取数据

#### Scenario: 切换后后端使用新 class_id 过滤

- **WHEN** 切换孩子后，家长请求查看资料列表，携带新 JWT（class_id=102）
- **THEN** 后端从 JWT 提取 class_id=102，查询 WHERE class_id=102，返回新班级的资料

#### Scenario: 切换后旧班级数据不可见

- **WHEN** 切换孩子后，家长尝试访问旧班级（class_id=101）的资料
- **THEN** 系统以新 JWT 中的 class_id=102 为准，不返回旧班级 101 的任何数据

### Requirement: 后端数据查询强制隔离

后端 FastAPI MUST 在数据查询层强制加入 WHERE class_id 隔离条件作为最后一道防线。当请求参数中包含 class_id 时，后端 MUST 校验该 class_id 是否等于当前用户的 class_id（学生）或属于其 teaching_classes（教师），不匹配则返回 403 Forbidden。后端 MUST NOT 信任请求参数中的 class_id 作为数据过滤依据，MUST 以 JWT Payload 中的 class_id 或 teaching_classes 为唯一可信来源。

#### Scenario: 后端查询强制带 class_id 过滤

- **WHEN** 后端执行任何班级相关数据的查询
- **THEN** 查询 MUST 包含 WHERE class_id = :current_class_id（学生）或 WHERE class_id IN (teaching_classes)（教师）

#### Scenario: 请求参数 class_id 与 JWT 不符被拒

- **WHEN** 学生 JWT 中 class_id=101，但请求参数中传入 class_id=102
- **THEN** 后端校验请求参数 class_id 与 JWT 不匹配，返回 403 Forbidden

#### Scenario: 后端不信任请求参数中的 class_id

- **WHEN** 请求参数中的 class_id 与 JWT Payload 中的 class_id 一致
- **THEN** 后端以 JWT Payload 中的 class_id 为准执行查询，请求参数仅做一致性校验

### Requirement: 前端班级数据渲染控制

前端 Next.js MUST 根据 JWT 中的 class_id 显示对应班级的数据。前端组件 MUST NOT 渲染其他班级的数据。前端 MUST NOT 将 class_id 作为可配置参数暴露给用户。前端 API 请求 MUST NOT 在 URL 参数或请求体中显式传入 class_id。

#### Scenario: 前端根据 class_id 渲染班级数据

- **WHEN** 学生 class_id=101 登录后访问资料页面
- **THEN** 前端从 JWT 中读取 class_id=101，请求后端返回班级 101 的资料并渲染

#### Scenario: 前端不渲染其他班级数据

- **WHEN** 前端组件渲染资料列表
- **THEN** 仅渲染当前 class_id 对应的资料，不展示其他班级的资料

#### Scenario: 前端不暴露 class_id 为可配置参数

- **WHEN** 前端发起 API 请求拉取班级数据
- **THEN** 前端不在 URL 参数或请求体中显式传入 class_id（由后端从 JWT 中提取），防止用户篡改

### Requirement: 无班级分配边界处理

当用户未分配班级时（class_id 为 NULL 或 teaching_classes 为空），前端 MUST 展示"暂无班级"空状态，后端 MUST 拒绝所有班级数据查询。

#### Scenario: 学生未分配班级前端展示空状态

- **WHEN** 学生登录后 class_id 为 NULL，访问资料页面
- **THEN** 前端展示"暂无班级"空状态，不发起数据请求

#### Scenario: 学生未分配班级后端拒绝查询

- **WHEN** 学生 class_id 为 NULL，后端收到班级数据查询请求
- **THEN** 后端返回提示"您尚未分配班级"，拒绝执行查询

#### Scenario: 教师未分配任教班级前端展示空状态

- **WHEN** 教师登录后 teaching_classes 为空列表，访问班级管理页面
- **THEN** 前端展示"暂无任教班级"空状态，不展示任何班级数据

#### Scenario: 教师未分配任教班级后端拒绝查询

- **WHEN** 教师 teaching_classes 为空，后端收到班级数据查询请求
- **THEN** 后端返回提示"您尚未分配任教班级"，拒绝执行查询

### Requirement: 跨班访问拦截与审计日志

当用户尝试篡改 URL 参数或 API Payload 中的 class_id 进行跨班访问时，后端 MUST 返回 403 Forbidden 并记录审计日志。审计日志 MUST 复用 RBAC 规约中的 AuditLog 表，包含 user_id、role、request_path、method、status_code、ip_address、created_at 字段。

#### Scenario: 篡改 URL 参数跨班访问被拦截

- **WHEN** 学生 class_id=101，尝试通过 URL 参数 ?class_id=102 访问其他班级资料
- **THEN** 后端校验 URL 参数中的 class_id=102 与 JWT 中的 class_id=101 不匹配，返回 403 Forbidden，记录审计日志

#### Scenario: 篡改 API Payload 中 class_id 被拦截

- **WHEN** 学生 class_id=101，尝试在 API 请求体中传入 class_id=102 提交作业
- **THEN** 后端校验请求体中的 class_id=102 与 JWT 中的 class_id=101 不匹配，返回 403 Forbidden，记录审计日志

#### Scenario: 教师篡改 class_id 跨班访问被拦截

- **WHEN** 教师 teaching_classes=[101,102]，尝试在请求中传入 class_id=201 访问非任教班级数据
- **THEN** 后端校验 201 不在 teaching_classes 中，返回 403 Forbidden，记录审计日志

#### Scenario: 跨班访问审计日志记录完整

- **WHEN** 任何跨班访问被拦截时
- **THEN** 审计日志记录包含 user_id、role、request_path、method、status_code=403、ip_address、created_at，异步写入不影响响应性能

### Requirement: SQLite 并发读取优化

系统 MUST 在 FastAPI 启动时执行 PRAGMA journal_mode=WAL 提升 SQLite 并发读性能。班级隔离查询（SELECT）MUST NOT 因并发问题阻塞。WAL 模式下读操作 MUST NOT 阻塞写操作，写操作 MUST NOT 阻塞读操作。

#### Scenario: 启动时启用 WAL 模式

- **WHEN** FastAPI 应用启动并连接 SQLite 数据库
- **THEN** 系统执行 PRAGMA journal_mode=WAL，验证 journal_mode 返回 wal

#### Scenario: 并发读取不阻塞

- **WHEN** 多个用户同时查询不同班级的数据（并发 SELECT）
- **THEN** 所有查询并行执行互不阻塞，WAL 模式允许并发读

#### Scenario: 读写不互相阻塞

- **WHEN** 教师正在上传资料（INSERT/UPDATE）的同时学生查询资料列表（SELECT）
- **THEN** 写操作不阻塞读操作，学生查询正常返回数据（可能不含最新写入的数据，但不会超时或报错）
