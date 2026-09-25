## Purpose

为 CampusClaw 提供封闭式双角色账号体系，覆盖账号 CSV 预置、密码与验证码双方式登录、手机号多娃绑定与选择、强制改密、JWT 会话管理、验证码防刷与登录失败锁定等行为契约，作为所有后续业务能力的安全前置基础。

## ADDED Requirements

### Requirement: 封闭注册与账号预置

系统 MUST 完全禁止自助注册。系统仅包含教师（teacher）和学生（student）两种角色，不设独立的家长角色。教师和学生账号由管理员或教师通过 CSV 批量导入预置。系统 MUST NOT 提供任何公开注册入口。CSV 表头 MUST 至少包含学号、学生姓名，可选包含手机号列。导入时若包含手机号列，系统 MUST 将手机号写入对应学生账号的 phone 字段完成绑定。同一手机号可绑定多个学生账号。

#### Scenario: 未登录用户无法注册

- **WHEN** 未登录用户访问系统任意页面
- **THEN** 系统重定向到登录页，页面上不显示任何注册链接或按钮

#### Scenario: 教师通过 CSV 批量导入学生含手机号

- **WHEN** 教师上传 CSV 文件，某行包含学号 S001、学生姓名张三、手机号 13800001111
- **THEN** 系统创建学号为 S001 的学生账号，初始密码按规则生成，并将手机号 13800001111 写入该账号的 phone 字段

#### Scenario: 同一手机号绑定多个学生

- **WHEN** CSV 中两行学生的手机号均为 13800001111
- **THEN** 系统将 13800001111 分别写入两个学生账号的 phone 字段，该手机号后续可登录任一学生账号

#### Scenario: CSV 缺少学号列被拒绝

- **WHEN** 教师上传的 CSV 文件缺少"学号"列
- **THEN** 系统拒绝导入并返回明确的错误提示，不创建任何账号

### Requirement: 密码登录

教师和学生 MUST 使用学号/工号 + 密码登录。登录失败时系统 MUST 返回统一的错误提示"账号或密码错误"，不区分账号不存在和密码错误，防止账号枚举。登录成功后系统 MUST 根据 must_change_password 决定跳转到改密页或主页。

#### Scenario: 教师用工号和密码登录成功

- **WHEN** 教师输入正确的工号和密码提交登录
- **THEN** 系统验证通过，签发 JWT 双 Token，根据 must_change_password 决定跳转到改密页或主页

#### Scenario: 学生用学号和密码登录成功

- **WHEN** 学生输入正确的学号和密码提交登录
- **THEN** 系统验证通过，签发 JWT 双 Token，进入后续流程

#### Scenario: 密码错误登录失败

- **WHEN** 用户输入正确的账号但错误的密码提交登录
- **THEN** 系统返回"账号或密码错误"，累计密码登录失败次数

#### Scenario: 账号不存在登录失败

- **WHEN** 用户输入系统中不存在的学号或工号提交登录
- **THEN** 系统返回"账号或密码错误"，与密码错误时返回的提示完全相同

### Requirement: 手机号验证码登录

用户 MUST 能使用手机号 + 短信验证码登录（便捷登录，主要面向家长）。验证码为 6 位随机数字，存入 VerificationCode 表，有效期 5 分钟。开发阶段（SMS_MOCK=true）验证码 MUST 直接返回在 API 响应中。验证码校验通过后，系统 MUST 查询该手机号绑定的所有学生账号：若绑定 1 个学生则直接签发正式 JWT；若绑定多个学生则返回 Temp Token 和学生列表。

#### Scenario: 发送验证码成功

- **WHEN** 用户输入手机号 13800001111 并点击发送验证码
- **THEN** 系统生成 6 位随机验证码存入 VerificationCode 表（有效期 5 分钟），若 SMS_MOCK=true 则验证码在 API 响应中返回

#### Scenario: 验证码登录单娃直接签发 JWT

- **WHEN** 用户输入手机号 13800001111 和正确的验证码，该手机号仅绑定 1 个学生账号
- **THEN** 系统校验验证码有效，直接签发正式 JWT（Payload 中 user_id 为该学生 ID），设置 Refresh Token Cookie

#### Scenario: 验证码登录多娃返回 Temp Token 和学生列表

- **WHEN** 用户输入手机号 13800001111 和正确的验证码，该手机号绑定 2 个学生账号
- **THEN** 系统返回 Temp Token 和学生列表（含 id、name、class_name），前端弹出选择框"请选择当前要查看的孩子"

#### Scenario: 验证码错误登录失败

- **WHEN** 用户输入手机号和错误的验证码提交登录
- **THEN** 系统返回"验证码错误"，累计验证码错误次数

#### Scenario: 验证码过期登录失败

- **WHEN** 用户输入手机号和已过期（超过 5 分钟）的验证码提交登录
- **THEN** 系统返回"验证码已过期，请重新发送"

#### Scenario: 手机号未绑定任何学生

- **WHEN** 用户输入手机号 13900000000 和正确的验证码，但该手机号未绑定任何学生账号
- **THEN** 系统返回提示"该手机号未绑定学生，请联系班主任绑定"

### Requirement: 验证码防刷限制

系统 MUST 对验证码发送实施防刷限制：同一手机号 60 秒内只能发送一次；同一手机号每天最多发送 10 次；同一验证码错误输入 5 次后作废，需重新发送。所有限制 MUST 用 SQLite 实现，不依赖 Redis。

#### Scenario: 60 秒内重复发送被拒

- **WHEN** 用户对手机号 13800001111 在 60 秒内第二次点击发送验证码
- **THEN** 系统拒绝发送并提示"请60秒后再试"

#### Scenario: 每日发送次数超限

- **WHEN** 用户对手机号 13800001111 当天已发送 10 次验证码，第 11 次点击发送
- **THEN** 系统拒绝发送并提示"今日发送次数已达上限"

#### Scenario: 验证码错误5次后作废

- **WHEN** 用户对某验证码连续第 5 次输入错误
- **THEN** 系统将该验证码标记为已作废，用户必须重新发送验证码

#### Scenario: 次日发送次数重置

- **WHEN** 跨自然日后用户对手机号 13800001111 点击发送验证码
- **THEN** 系统清零该手机号的当日发送计数，允许重新发送

### Requirement: 多娃选择与 Temp Token

当手机号绑定多个学生时，系统 MUST 返回 Temp Token 和学生列表供用户选择。用户选择后前端 MUST 携带 Temp Token 和 student_id 调用选择端点，系统校验后签发正式 JWT，JWT Payload 中的 user_id MUST 锁定为所选学生 ID。Temp Token MUST 有独立有效期且仅在多娃选择流程中使用。

#### Scenario: 选择学生后签发正式 JWT

- **WHEN** 用户从学生列表中选择某个学生，前端携带 Temp Token 和 student_id 提交
- **THEN** 系统校验 Temp Token 有效且该 student_id 确实绑定于该手机号，签发正式 JWT（user_id 为所选学生 ID），设置 Refresh Token Cookie

#### Scenario: Temp Token 无效被拒

- **WHEN** 前端携带无效或过期的 Temp Token 调用选择端点
- **THEN** 系统返回"临时令牌已过期，请重新登录"，拒绝签发正式 JWT

#### Scenario: 选择的 student_id 不属于该手机号

- **WHEN** 前端携带有效 Temp Token 但提交的 student_id 不在该手机号绑定的学生列表中
- **THEN** 系统拒绝签发 JWT 并返回"无权选择该学生"

### Requirement: 切换孩子

多娃家长登录后前端顶部 MUST 提供"切换孩子"按钮。点击后系统 MUST 重新调起选择流程，使用已登录的 Refresh Token 换取新的 Temp Token 和学生列表，用户选择另一个孩子后签发新的正式 JWT。

#### Scenario: 切换孩子成功

- **WHEN** 已登录的家长（绑定多个学生）点击"切换孩子"按钮，从列表中选择另一个孩子
- **THEN** 系统签发新的正式 JWT（user_id 为新选择的学生 ID），前端更新全局状态，页面刷新为新孩子的数据

#### Scenario: 单娃家长无切换按钮

- **WHEN** 已登录的家长（仅绑定 1 个学生）查看页面
- **THEN** 前端顶部不显示"切换孩子"按钮

#### Scenario: Refresh Token 过期无法切换

- **WHEN** 家长点击"切换孩子"但 Refresh Token 已过期
- **THEN** 系统返回认证失效响应，前端清除 Token 并重定向到登录页

### Requirement: 初始密码规则

教师和学生的初始密码 MUST 为"学校三位缩写（全小写）+ 学号/工号后6位"（例如 thu123456）。验证码登录方式不需要初始密码。教师重置密码时 MUST 重置为该规则生成的初始密码。

#### Scenario: 学生账号初始密码生成

- **WHEN** CSV 导入学号为 20230001 的学生，学校缩写为 thu
- **THEN** 该账号初始密码为 thu230001（学校缩写 + 学号后6位）

#### Scenario: 教师账号初始密码生成

- **WHEN** 管理员创建工号为 T2023001 的教师账号，学校缩写为 thu
- **THEN** 该账号初始密码为 thu023001（学校缩写 + 工号后6位）

### Requirement: 密码安全策略与存储

密码 MUST 至少 8 位，且必须同时包含大写字母、小写字母、数字和特殊字符。密码 MUST 使用 bcrypt 哈希加盐存储，系统 MUST NOT 以明文或可逆加密形式存储密码。

#### Scenario: 符合策略的密码被接受

- **WHEN** 用户在改密时输入密码 "Abc@1234"（8位，含大小写字母、数字、特殊字符）
- **THEN** 系统接受该密码，bcrypt 哈希后存入数据库

#### Scenario: 不符合策略的密码被拒绝

- **WHEN** 用户在改密时输入密码 "12345678"（仅数字，缺少字母和特殊字符）
- **THEN** 系统拒绝该密码并返回明确的策略提示，密码不被修改

#### Scenario: 密码长度不足被拒绝

- **WHEN** 用户在改密时输入密码 "Ab1!"（仅4位）
- **THEN** 系统拒绝该密码并提示密码长度不足

### Requirement: 强制首次改密

所有新账号和被重置密码的账号 MUST 将 must_change_password 设为 true。FastAPI 中间件 MUST 拦截所有业务请求，当 must_change_password 为 true 时仅允许调用修改密码接口，其他业务接口返回需要改密的响应。用户成功修改密码后 MUST 将 must_change_password 设为 false。验证码登录方式不触发强制改密（因无密码概念）。

#### Scenario: 首次密码登录被拦截要求改密

- **WHEN** 用户使用初始密码登录成功，must_change_password 为 true
- **THEN** 系统跳转到修改密码页面，不允许访问其他业务页面

#### Scenario: 未改密时访问业务接口被拦截

- **WHEN** 用户 must_change_password 为 true，携带有效 Access Token 调用非改密的业务接口
- **THEN** 系统返回"请先修改初始密码"的提示，拒绝处理该业务请求

#### Scenario: 改密成功后恢复正常访问

- **WHEN** 用户在改密页输入符合策略的新密码并提交成功
- **THEN** 系统将 must_change_password 设为 false，重新签发不含改密标记的 Token，用户可正常访问业务接口

#### Scenario: 验证码登录不触发强制改密

- **WHEN** 家长通过手机号验证码登录成功（该学生 must_change_password 为 true）
- **THEN** 系统允许直接访问业务页面，不强制跳转改密页

### Requirement: JWT 会话管理

系统 MUST 使用 JWT 进行会话管理。Access Token 有效期 MUST 为 2 小时，Refresh Token 有效期 MUST 为 7 天且存放在 HttpOnly Cookie 中。正式 JWT Payload MUST 包含字段：user_id、role、class_id、must_change_password。当 Access Token 过期时，前端 MUST 能使用 HttpOnly Cookie 中的 Refresh Token 自动刷新获取新的 Access Token。

#### Scenario: 登录成功签发双 Token

- **WHEN** 用户登录认证通过（密码登录或验证码单娃直接登录）
- **THEN** 系统返回 Access Token（2小时有效）到响应体，同时通过 Set-Cookie 设置 Refresh Token（7天有效，HttpOnly）

#### Scenario: Access Token 过期自动刷新

- **WHEN** 前端请求携带过期的 Access Token，浏览器自动携带 HttpOnly Cookie 中的 Refresh Token
- **THEN** 系统验证 Refresh Token 有效后签发新的 Access Token，原请求重试成功

#### Scenario: Refresh Token 过期需重新登录

- **WHEN** Refresh Token 已过期（超过7天），用户发起请求
- **THEN** 系统返回认证失效响应，前端清除本地 Token 并重定向到登录页

#### Scenario: JWT Payload 包含必要字段

- **WHEN** 系统签发正式 Access Token
- **THEN** Token 解码后包含 user_id、role、class_id、must_change_password 四个字段

### Requirement: 密码登录失败锁定

系统 MUST 对密码登录连续失败 5 次的账号锁定 15 分钟。锁定基于 LoginAttempt 表（字段：identifier、attempt_count、lock_until）实现。锁定期间即使输入正确密码也 MUST 拒绝登录。锁定时间到期后 MUST 自动解除锁定。登录成功时 MUST 清零该账号的失败计数。验证码登录的失败限制由验证码防刷规则处理，不使用 LoginAttempt 表。

#### Scenario: 连续5次密码失败后锁定

- **WHEN** 某账号连续第 5 次输入错误密码
- **THEN** 系统将该账号的 lock_until 设为当前时间 +15 分钟，返回"账号或密码错误"

#### Scenario: 锁定期间正确密码也被拒

- **WHEN** 某账号处于锁定期间（lock_until 未过期），用户输入正确的账号和密码
- **THEN** 系统拒绝登录并提示"账号已锁定，请15分钟后重试"

#### Scenario: 锁定过期后可正常登录

- **WHEN** 某账号锁定时间已过（lock_until 已过期），用户输入正确的账号和密码
- **THEN** 系统验证通过，清零失败计数，签发 Token，登录成功

#### Scenario: 密码登录成功清零失败计数

- **WHEN** 某账号之前有 3 次密码失败记录，用户输入正确密码登录成功
- **THEN** 系统将该账号的 attempt_count 清零并清除 lock_until

### Requirement: 忘记密码与重置密码

系统 MUST NOT 提供短信验证码找回密码功能。用户忘记密码时系统 MUST 提示"请联系班主任重置"。教师后台 MUST 提供"重置密码"按钮，点击后将学生密码重置为初始密码，并重新置 must_change_password = true。

#### Scenario: 用户忘记密码看到提示

- **WHEN** 用户在登录页点击"忘记密码"
- **THEN** 系统显示提示"请联系班主任重置"，不提供任何自助重置入口

#### Scenario: 教师重置学生密码

- **WHEN** 教师在后台对某学生账号点击"重置密码"
- **THEN** 系统将该学生密码重置为初始密码规则生成的值，must_change_password 设为 true

### Requirement: 多端在线与登出

系统 MUST 允许同一账号多端同时在线（无状态 JWT，不引入黑名单）。登出时前端 MUST 清除内存中的 Access Token 和全局状态，后端 MUST 清除 HttpOnly Cookie 中的 Refresh Token。

#### Scenario: 同一账号多端登录都成功

- **WHEN** 同一学生账号在浏览器 A 和浏览器 B 同时登录
- **THEN** 两端均获得有效的 Access Token 和 Refresh Token，互不影响，不互踢

#### Scenario: 登出清除所有 Token 和状态

- **WHEN** 用户点击登出
- **THEN** 前端清除内存中的 Access Token 和全局状态，后端清除 HttpOnly Cookie，用户被重定向到登录页
