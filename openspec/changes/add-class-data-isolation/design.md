## Context

CampusClaw 已有登录与账号体系（add-login-and-account-system）定义 JWT 会话和 User 表 class_id 字段，RBAC 规约（add-rbac-role-permissions）定义角色权限矩阵和数据隔离原则。本设计为"班级数据隔离"规约中定义的全部行为提供技术实现方案，重点解决 class_id 字段规范、隔离范围界定、查询层强制过滤、多娃切换 class_id 重载和 SQLite 并发优化。详见 proposal.md - Why。

## Goals / Non-Goals

**Goals:**

- 确定 class_id 字段在所有班级相关表上的规范
- 确定隔离与非隔离数据的范围边界
- 确定后端查询层强制 WHERE class_id 过滤方案
- 确定多娃切换时 class_id 上下文重载方案
- 确定无班级分配时的边界处理方案
- 确定 SQLite WAL 模式配置方案

**Non-Goals:**

- 不实现独立数据库/Schema per class 的隔离（使用共享数据库 + class_id 过滤）
- 不实现 ORM 级行级权限自动注入（使用查询级 WHERE 过滤，与 RBAC 规约一致）
- 不引入 Redis 缓存层
- 不实现数据库分片或分区
- 不定义具体业务表结构（仅定义 class_id 字段要求，具体表结构由后续业务规约覆盖）

## Decisions

### 1. 隔离策略：共享数据库 + class_id 字段过滤

采用共享数据库方案，所有班级相关表增加 class_id 字段，查询时通过 WHERE class_id 过滤实现隔离。

**替代方案**：独立数据库 per class。**未选原因**：班级数量有限且动态变化，独立数据库管理复杂、连接池开销大、跨班查询（教师任教多班）困难。

### 2. class_id 字段规范

所有班级相关表 MUST 包含 class_id 字段：

- 类型：INTEGER，非 NULL（记录创建时必须填入）
- 外键：关联班级表主键
- 索引：每张表对 class_id 建普通索引，加速 WHERE class_id 过滤
- 不可变：记录创建后 class_id MUST NOT 变更（学生不会换班是当前设计前提）

需包含 class_id 的表：班级资料表、作业布置表、作业提交记录表、AI 提问记录表、错题本表。

不需 class_id 的表：系统公告表、学校级公共资源表、User 表（已有 class_id 但用于用户归属，非数据隔离）。

### 3. 后端查询强制隔离方案

在数据查询层（Service 或 Repository 层）统一加入 WHERE class_id 过滤：

- 学生查询：`WHERE class_id = :current_class_id`，current_class_id 从 JWT Payload 的 class_id 获取
- 教师查询：`WHERE class_id IN (teaching_classes)`，teaching_classes 从 JWT Payload 获取

请求参数中的 class_id 仅做一致性校验（与 JWT 中的 class_id/teaching_classes 对比），不作为查询条件。不匹配则返回 403。

与 RBAC 规约的数据隔离原则一致，本规约补充了 class 级别（非个人级别）的隔离要求。

### 4. 前端 class_id 渲染方案

前端从 JWT 解析 class_id 存入 Zustand store。组件渲染时：

- 不在 URL 或请求体中暴露 class_id 参数
- API 请求不携带 class_id（由后端从 JWT 提取）
- 页面数据由后端返回的已过滤数据驱动渲染

多娃切换时：新 JWT 覆盖 store 中的 class_id，调用 resetBusinessState() 清空缓存，重新拉取数据。

### 5. 无班级分配边界处理

- 学生 class_id 为 NULL：前端展示"暂无班级"空状态，不发 API 请求；后端收到请求时返回提示并拒绝查询
- 教师 teaching_classes 为空：前端展示"暂无任教班级"空状态；后端拒绝查询

### 6. 跨班访问拦截

请求参数中的 class_id 与 JWT Payload 对比：

- 学生：请求参数 class_id != JWT class_id → 403 + 审计日志
- 教师：请求参数 class_id 不在 JWT teaching_classes 中 → 403 + 审计日志

审计日志复用 RBAC 规约的 AuditLog 表和异步写入机制。

### 7. SQLite WAL 模式

FastAPI 启动时执行 `PRAGMA journal_mode=WAL;`。WAL 模式优势：

- 读操作不阻塞写操作，写操作不阻塞读操作
- 适合读多写少的班级数据查询场景
- 校园级并发量有限，WAL 性能充足

配置 `PRAGMA wal_autocheckpoint=1000;`（默认 1000 页）控制 WAL 文件大小。

## Risks / Trade-offs

- **[查询级隔离依赖开发者自觉]** → 开发者可能遗漏 WHERE class_id 条件导致跨班泄露。**缓解**：代码审查重点关注；可引入 SQLAlchemy event listener 自动注入作为安全网（后续优化）。

- **[class_id 索引影响写入性能]** → 每张表增加 class_id 索引，写入时需更新索引。**缓解**：校园级写入量有限，影响可忽略；读多写少场景下索引收益远大于成本。

- **[共享数据库单表数据增长]** → 所有班级数据在同一表中，数据量随班级增多而增长。**缓解**：校园级数据量有限（千级学生、万级记录）；class_id 索引保证查询效率。

- **[WAL 模式 checkpoint 延迟]** → WAL 文件增长到阈值后触发 checkpoint，可能短暂影响性能。**缓解**：配置合理的 wal_autocheckpoint；校园级写入量有限，checkpoint 频率低。

- **[class_id 不可变假设]** → 当前设计假设学生不会换班，class_id 创建后不变。**缓解**：若未来支持换班，需增加换班时数据迁移逻辑；当前阶段不预留此复杂度。
