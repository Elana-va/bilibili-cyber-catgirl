# DeepSeek 安全接入设计

日期：2026-07-15  
状态：已获用户口头确认，待实施计划复核

## 目标

在本地管理台完成 DeepSeek API Key 的安全接入、无对话费用的认证验证和 V4 模型选择，为后续“评论生成回复草稿”能力提供连接基础。

本阶段不调用聊天生成接口，不读取 B 站评论，不生成回复草稿，也不改变现有 `manual_only` 人工审核与发布策略。

## 已确认方案

采用管理台本地录入方案：用户在设置页输入 API Key，后端先通过 DeepSeek 官方 `GET /models` 接口验证，再使用当前 Windows 用户的 DPAPI 加密保存。设置页和后端接口永不回显原始 Key。

未采用的方案：

- `.env` 明文保存：实现简单，但不满足本机密钥保护目标。
- 仅内存保存：不落盘，但每次服务重启都需重新输入，操作成本较高。

## 用户界面

设置页的“连接状态”区域新增独立的 DeepSeek 卡片。

未连接状态包含：

- 密码型 API Key 输入框，不预填并关闭浏览器自动完成；
- 模型选择框，提供 `deepseek-v4-flash` 和 `deepseek-v4-pro`；
- “验证并连接”按钮；
- 说明文字：连接会向 DeepSeek 官方 `/models` 发起一次认证请求，但不会发起对话生成。

已连接状态包含：

- 已连接徽标；
- 当前模型；
- 最近一次验证时间；
- “重新验证”和“断开连接”按钮。

无论成功或失败，前端完成请求后都立即清空 API Key 输入框。页面刷新和接口查询均不能恢复或显示原始 Key。

## 后端组件

### 凭证数据

新增 DeepSeek 凭证数据结构：

- `api_key`：原始 API Key，仅存在于请求处理内存和 DPAPI 解密后的短生命周期对象中；
- `model`：选定模型；
- `verified_at`：最近成功验证的 UTC 时间。

新增独立凭证存储，路径为 `data/secrets/deepseek-credential.bin`。它复用现有 `DataProtector` / `DpapiProtector` 抽象，但不与 B 站凭证混存，避免生命周期和删除操作互相影响。

写入继续采用“临时文件后原子替换”，断开连接仅删除 DeepSeek 密文文件。

### DeepSeek 连接探针

新增连接探针，向配置的基础地址发送：

```http
GET /models
Authorization: Bearer <api-key>
Accept: application/json
```

成功条件：

- HTTP 200；
- 返回 JSON 中存在模型列表；
- 用户选择的模型出现在列表中。

默认基础地址为 `https://api.deepseek.com`。本阶段 UI 不开放自定义基础地址，降低把密钥误发给第三方地址的风险；测试可通过依赖注入替换探针。

### 模型默认值

新连接默认选择 `deepseek-v4-flash`，可切换到 `deepseek-v4-pro`。现有 `DeepSeekClient` 默认模型同步改为 `deepseek-v4-flash`，避免继续依赖官方计划于 2026-07-24 停用的 `deepseek-chat` 别名。

## API 设计

### `GET /api/deepseek/connection`

返回非敏感状态：

```json
{
  "configured": true,
  "verified": true,
  "source": "local_encrypted",
  "model": "deepseek-v4-flash",
  "verified_at": "2026-07-15T08:00:00Z"
}
```

`source` 仅允许为 `local_encrypted`、`environment` 或 `none`。响应不得包含 API Key、Key 前后缀、密文路径或上游响应头。

### `POST /api/deepseek/connection`

请求：

```json
{
  "api_key": "用户输入的密钥",
  "model": "deepseek-v4-flash"
}
```

处理顺序：

1. 校验请求字段和模型白名单；
2. 使用请求中的 Key 调用 `/models`；
3. 只有验证成功且所选模型可用时才加密保存；
4. 返回不含 Key 的连接状态。

如果已有有效凭证而新 Key 验证失败，保留旧凭证，不覆盖。

### `POST /api/deepseek/verify`

使用已保存凭证重新调用 `/models`。成功后更新 `verified_at`；失败时保留密文，但返回 `verified: false`，供用户决定重连或断开。

### `POST /api/deepseek/disconnect`

删除 DeepSeek 密文并返回未连接状态。该操作不影响 B 站凭证和运行策略。

## 错误处理

面向 UI 使用稳定、非敏感的中文错误：

- 401：API Key 无效；
- 402：账户余额不足（若 `/models` 返回该状态）；
- 429：请求过于频繁，请稍后重试；
- 5xx：DeepSeek 服务暂时不可用；
- 超时或连接失败：当前无法连接 DeepSeek；
- DPAPI 错误：本机安全存储不可用或凭证无法解密；
- 所选模型缺失：该模型当前不可用，请重新选择。

响应与日志不记录上游 `Authorization` 请求头、用户提交体、API Key、密文内容或包含敏感信息的原始异常文本。

## 配置兼容性

现有 `DEEPSEEK_API_KEY` 与 `DEEPSEEK_BASE_URL` 仅保留给已有的环境变量部署，不在页面回显，并在状态中标记为“环境变量托管”。环境变量托管的 Key 不能通过页面删除；用户可选择提交一个本机加密 Key 作为优先凭证。

从设置页提交的新 Key 及其后续重新验证始终使用固定的 `https://api.deepseek.com`，不读取可变的 `DEEPSEEK_BASE_URL`。这样即使旧部署配置了兼容代理，也不会把用户在页面输入的新 Key 发送给第三方地址。

凭证优先级：本机 DPAPI 凭证优先，其次为环境变量。这样不会破坏已有部署，同时使新用户默认走安全存储。

## 安全边界

- 服务继续仅监听本机回环地址；
- API Key 不进入数据库、模板上下文、浏览器存储、URL、日志或模型上下文；
- API Key 表单不预填，提交结束立即清空；
- 只向固定 DeepSeek 官方基础地址发送验证请求；
- API 响应只暴露布尔状态、模型和时间；
- DPAPI 密文只能由当前 Windows 用户在本机解密；
- 本阶段没有任何 B 站写操作和模型生成操作。

## 测试与验收

自动化测试覆盖：

- DeepSeek 凭证加密保存、读取、覆盖和删除；
- 正确 Key 验证后保存；
- 错误 Key、超时、限流和服务错误不保存；
- 新 Key 验证失败时保留旧凭证；
- 模型白名单与模型可用性检查；
- 状态、验证和断开接口不泄露 Key；
- 环境变量兼容与凭证优先级；
- 设置页具有密码输入、模型选择及连接状态组件；
- `DeepSeekClient` 默认使用 `deepseek-v4-flash`；
- 服务重启后可从 DPAPI 密文恢复非敏感连接状态；
- 现有 B 站连接和全部回归测试保持通过。

人工验收：

1. 在本地设置页输入真实 DeepSeek API Key；
2. 连接成功后确认页面仅显示状态、模型和验证时间；
3. 刷新页面与重启服务，确认连接状态仍存在；
4. 重新验证连接；
5. 断开后确认状态清除；
6. 检查服务日志和浏览器控制台，确认不存在原始 Key。

## 官方依据

- DeepSeek API 使用 Bearer Token 认证，默认 OpenAI 兼容基础地址为 `https://api.deepseek.com`；
- 官方提供 `GET /models` 列出当前可用模型；
- 当前推荐模型为 `deepseek-v4-flash` 与 `deepseek-v4-pro`；
- `deepseek-chat` 和 `deepseek-reasoner` 计划于 2026-07-24 停用。

参考：

- https://api-docs.deepseek.com/
- https://api-docs.deepseek.com/api/list-models
- https://api-docs.deepseek.com/quick_start/error_codes
