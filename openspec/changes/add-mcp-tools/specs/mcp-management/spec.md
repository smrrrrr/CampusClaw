## ADDED Requirements

### Requirement: 按班登记与服务端令牌
教师 MUST 能为任教班级登记名称与 Base URL。服务 MUST 属于该班且同班名称唯一。Bearer MUST 仅在服务端从环境变量读取；接口 MUST NOT 返回密钥。Base URL MUST 受服务端允许清单限制且禁止重定向。

#### Scenario: 登记与跨班隔离
- **WHEN** 教师为任教班级登记 campus-tools，随后另一班教师访问该资源
- **THEN** 本班登记成功，跨班访问返回 404，响应无 Bearer 值

#### Scenario: 角色与地址校验
- **WHEN** 学生操作管理接口或教师登记未经允许的 URL
- **THEN** 学生得到 403，非法地址得到明确 400，均不发起远端请求

### Requirement: 握手、工具发现及断开
连接 MUST 真实执行 initialize、initialized 与 tools/list，成功后缓存工具；失败 MUST 给出脱敏错误并清空缓存。断开 MUST 清空工具缓存、标记不可调用，MUST NOT 仅改变前端显示。

#### Scenario: 发现三个自建工具
- **WHEN** 教师连接 Compose 内的 mcp-server
- **THEN** 页面可见 formula_hint、unit_convert、weather_query 及 schema

#### Scenario: 断开后无法调用
- **WHEN** 已绑定技能的服务器被断开
- **THEN** 缓存为空；保存新的对应绑定被拒绝；已有技能下一次调用记为 denied

#### Scenario: 连接失败保留原有聊天
- **WHEN** 服务器不可达或返回鉴权错误
- **THEN** 管理页面显示连接失败，学生原有 RAG 和 SSE 聊天仍可运行
