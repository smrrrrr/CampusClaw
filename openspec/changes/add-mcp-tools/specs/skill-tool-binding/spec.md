## ADDED Requirements

### Requirement: 技能文件与合法引用
教师 MUST 能保存按班级隔离的技能文件，包含名称、触发词、工具及指令。工具 MUST 支持 knowledge_search 与 tool@server。保存时 MUST 验证 MCP 引用属于本班已连接且已发现工具，否则拒绝保存。技能 MUST 可列出、编辑和启停。

#### Scenario: 保存合法技能
- **WHEN** 教师保存含 formula_hint@campus-tools 的技能且工具已在本班发现
- **THEN** 保存成功，文件正文与绑定可重新读取

#### Scenario: 无效绑定不入库
- **WHEN** 工具未发现、服务未连接或引用其他班服务
- **THEN** 保存返回可读 400，原技能保持不变

### Requirement: 服务端受控工具调用
学生问题命中启用技能时，服务端 MUST 重新校验班级、服务连接和工具缓存，并用服务端 Bearer 真实调用 tools/call。学生或模型 MUST NOT 自行指定服务 URL/令牌/任意工具。工具结果 MUST 作为数据注入 user 消息，MUST NOT 当作 system 指令。

#### Scenario: 技能触发实际工具
- **WHEN** 学生提问「速度公式是什么」命中公式技能
- **THEN** 实际远端调用 formula_hint，结果用于回答，记录工具标识及 ok

#### Scenario: 断开与越权明确拒绝
- **WHEN** 已有技能引用的服务断开或当前班级校验不通过
- **THEN** 禁止远端调用，记录 denied，回答中不声明工具成功

#### Scenario: 工具文本包含指令
- **WHEN** 工具返回要求忽略系统规则的文本
- **THEN** 文本仍只作为外部数据，系统/教师指令保持独立

### Requirement: 失败降级和资源上限
工具执行 MUST 有超时、响应长度与每轮调用数限制。参数不完整 MUST 明确说明；工具错误 MUST NOT 阻断既有 RAG/SSE 流程。没有模型密钥时 MUST 仍能展示已成功的工具结果。

#### Scenario: 天气上游失败
- **WHEN** 命中天气技能但供应商超时
- **THEN** tool_calls 状态为 error，学生得到可读提示，仍可继续对话
