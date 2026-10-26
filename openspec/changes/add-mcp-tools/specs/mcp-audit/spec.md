## ADDED Requirements

### Requirement: 调用元数据与本班审计
SSE meta、done 及历史消息 MUST 包含 tool_calls，至少记录工具引用及 ok/error/denied 状态。教师 MUST 能查看本班调用审计，至少包含 tool@server、状态、用户、时间，可附耗时和脱敏摘要。跨班审计 MUST 不可见。

#### Scenario: 对话成功到审计闭环
- **WHEN** 学生通过技能完成 unit_convert@campus-tools 调用
- **THEN** SSE 和历史可见 ok，教师审计可见该工具、用户、时间，另一班无法查看

### Requirement: Swagger 与自动化验收
MCP 管理/技能保存/审计接口 MUST 带 OpenAPI 描述，并能在浏览器 Swagger 通过 Bearer 试调。apitest MUST 覆盖管理权限及实际 MCP→技能→会话→审计链路，并通过 run_all.py 生成不入 Git 的 HTML 报告。

#### Scenario: 文档试调
- **WHEN** 开启 ENABLE_DOCS 并在浏览器访问 /api/docs
- **THEN** 能查看并授权试调登记、连接、tools、技能保存与审计接口

#### Scenario: 可复现验收
- **WHEN** 运行 MCP 相关接口测试
- **THEN** 覆盖非教师 403、跨班 404、三个工具、断开 denied 及报告生成，不泄露令牌
