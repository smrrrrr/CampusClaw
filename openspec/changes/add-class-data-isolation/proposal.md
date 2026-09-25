## Why

CampusClaw 的登录体系已定义双角色和 JWT 会话，RBAC 规约已定义角色权限矩阵和数据隔离原则。但"班级"作为 CampusClaw 最核心的数据隔离维度，尚缺乏完整的数据模型规范——哪些表需要 class_id 字段、哪些数据需严格隔离哪些不需隔离、多娃切换时 class_id 上下文如何重载、后端查询层如何强制过滤、SQLite 如何优化并发读取。没有这些行为契约，班级资料、作业、AI 提问历史、错题本等核心业务数据可能发生跨班泄露。本变更为系统引入完整的班级数据隔离规约，确保实现时有明确的、可验证的数据边界契约。

## What Changes

- 引入班级数据隔离模型：采用共享数据库 + class_id 字段过滤策略，所有与班级相关的数据表（资料、作业布置、作业提交记录、AI 提问记录、错题本）MUST 包含 class_id 字段。
- 明确隔离数据范围：班级资料、作业布置、作业提交记录、AI 提问历史、错题本 MUST 严格隔离；系统公告、学校级公共资源、用户账号基础信息 MUST NOT 隔离。
- 引入教师班级数据范围控制：教师只能查看和操作 teaching_classes 列表中班级的数据，跨班访问直接拒绝。
- 引入学生班级数据范围控制：学生只能查看和操作自己所在班级（class_id）的数据，不能查看其他班级的任何信息。
- 引入多娃切换班级上下文重载：切换孩子时新 JWT 中 class_id MUST 立即更新，前端 Zustand 业务缓存 MUST 全部清空，后续所有 API 请求的数据过滤条件 MUST 由新 class_id 驱动。
- 引入后端数据查询强制隔离：后端在数据查询层 MUST 强制加入 WHERE class_id 条件作为最后一道防线，请求参数中的 class_id MUST 校验是否匹配当前用户权限。
- 引入前端班级数据渲染控制：前端根据 JWT 中的 class_id 显示对应班级的数据，不在请求参数中暴露 class_id。
- 引入无班级分配边界处理：用户未分配班级时前端展示"暂无班级"空状态，后端拒绝所有班级数据查询。
- 引入跨班访问拦截与审计日志：篡改 URL 参数或 API Payload 中 class_id 的跨班访问 MUST 返回 403 Forbidden 并记录审计日志。
- 引入 SQLite 并发读取优化：FastAPI 启动时执行 PRAGMA journal_mode=WAL 提升并发读性能，确保班级隔离查询不因并发阻塞。

## Capabilities

### New Capabilities
- `class-data-isolation`: 班级数据隔离体系，覆盖隔离模型（class_id 字段规范）、隔离范围界定、教师与学生班级数据访问控制、多娃切换班级上下文重载、后端查询强制隔离、前端渲染控制、无班级边界处理、跨班访问拦截与审计、SQLite 并发优化。

### Modified Capabilities
- `rbac-role-permissions`: 班级数据隔离规约为 RBAC 中的"教师任教班级隔离"和"学生个人数据隔离"需求提供具体的数据模型和查询层实现规范。

## Impact

- **后端 (FastAPI)**：所有班级相关数据模型增加 class_id 字段并建索引；数据查询层统一加入 WHERE class_id 隔离条件；启动时执行 PRAGMA journal_mode=WAL；请求参数 class_id 一致性校验与跨班访问拦截；审计日志写入。
- **前端 (Next.js)**：组件根据 JWT 中的 class_id 拉取和渲染对应班级数据；API 请求不暴露 class_id；多娃切换时 Zustand 业务缓存全量清空；无班级时展示空状态。
- **数据库 (SQLite)**：班级相关表增加 class_id 字段和索引；启用 WAL 模式提升并发读性能；配置 wal_autocheckpoint。
- **部署 (Docker)**：无需新增基础设施组件，SQLite 文件挂载不变。
