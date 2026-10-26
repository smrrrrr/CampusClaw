## ADDED Requirements

### Requirement: 同仓独立 MCP 服务
系统 MUST 在同仓 mcp-server/ 中提供 Compose 可启动的 MCP 服务，暴露 GET /health 与 POST /mcp。/mcp MUST 校验环境变量 MCP_AUTH_TOKEN 的 Bearer 值，令牌 MUST NOT 写入源码、前端、镜像或响应。缺少配置 MUST 拒绝调用。

#### Scenario: 健康检查与缺失令牌
- **WHEN** 客户端访问 /health 并以缺失或错误 Bearer 访问 /mcp
- **THEN** 健康检查返回正常状态，/mcp 返回 HTTP 401，响应不含令牌

### Requirement: 初始化、发现与调用
服务 MUST 实现 JSON-RPC 2.0 initialize、notifications/initialized、tools/list、tools/call。发现 MUST 返回三个工具及 inputSchema；调用 MUST 返回文本 content。未知方法、非法 JSON、非法参数 MUST 返回可读的协议错误；工具运行失败 MUST 返回 isError，MUST NOT 伪装成功。

#### Scenario: 完整协议交互
- **WHEN** 带正确令牌的客户端初始化、发送 initialized 通知、发现并调用 formula_hint
- **THEN** 初始化协商成功，通知返回 202，发现包含三个工具，调用返回非空文本

#### Scenario: 非法调用
- **WHEN** 客户端提供未知方法、未知工具或无效参数
- **THEN** 返回带 code/message 的 JSON-RPC 错误或带 isError 的工具结果，不暴露内部异常

### Requirement: 公式提示
formula_hint MUST 根据 topic 返回受支持的数学/物理公式、适用条件与引导步骤；未知主题 MUST 明确说明未覆盖，MUST NOT 编造公式。

#### Scenario: 查询速度公式
- **WHEN** 调用 topic 为「速度公式」
- **THEN** 文本包含速度、路程、时间的关系及单位和使用条件

### Requirement: 单位换算
unit_convert MUST 接受有限数值 value 与 from_unit/to_unit，支持长度、面积、体积、质量、时间、速度、温度。MUST 校验量纲、温度偏移和物理下界，MUST NOT 执行用户表达式。

#### Scenario: 正确换算与温度偏移
- **WHEN** 分别换算 1 km 到 m 和 0 °C 到 °F
- **THEN** 返回 1000 m 与 32 °F，包含原数值/单位与结果

#### Scenario: 拒绝不相容量纲
- **WHEN** 将米换成千克或传入非有限数值
- **THEN** 返回可读工具错误，不能返回数值成功结果

### Requirement: 真实天气查询
weather_query MUST 使用用户给定 location，通过真实天气供应商查询当前天气与不超过未来 7 天的预报。输出 MUST 包含解析后的地点、时区、日期/数据时间、温度等指标、抓取时间及来源；MUST NOT 自动读取设备位置或用模拟数据伪装成功。

#### Scenario: 查询指定城市天气
- **WHEN** 查询「上海」未来两天天气且供应商可用
- **THEN** 返回匹配城市、两天日期、指标、时区、数据时间及供应商来源链接

#### Scenario: 城市无结果或上游超时
- **WHEN** 地点无法解析或天气供应商请求失败
- **THEN** 返回明确错误，禁止捏造天气；不影响公式与单位工具

### Requirement: 区县地名与行政层级消歧
weather_query MUST 支持供应商可解析的区县。完整行政地名无结果时 MUST 尝试本地名称并校验所属市、省；MUST NOT 静默退回市中心坐标。同名区县无法唯一确定时 MUST 提示补充所属行政区域。响应 MUST 保留用户原始地名、匹配区域及坐标，并说明预报来自匹配地点附近的气象模型网格，不代表街道实测。

#### Scenario: 大兴区按所属北京匹配
- **WHEN** 查询“北京市大兴区”，完整地名无结果且“大兴”返回多个省市的同名候选
- **THEN** 只接受行政标签匹配北京的候选，使用大兴坐标查询预报

#### Scenario: 区县歧义不得猜测
- **WHEN** 区县候选包含不同城市的多个同名地点
- **THEN** 返回需要补充所属城市或省份的可读错误，不用首个候选伪装成功
