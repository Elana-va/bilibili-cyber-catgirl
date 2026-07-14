# 运行手册

## 安全基线

1. 只使用独立测试账号，不使用主账号；
2. 首次启动保持 `manual_only` 和空自动回复白名单；
3. 服务仅绑定 `127.0.0.1`，不要直接暴露到局域网或公网；
4. 动态、日报和所有中高风险回复始终人工审核；
5. 真实写入前必须完成专用目标上的单次授权探针；
6. 遇到验证码、人机验证、账号异常或未知平台错误，停止自动写入，不尝试绕过。

## 启动与停止

在 PowerShell 中设置非敏感运行项后启动：

```powershell
$env:CATGIRL_RUN_MODE='manual_only'
$env:CATGIRL_KILL_SWITCH='false'
$env:CATGIRL_AUTO_REPLY_ALLOWLIST=''
python -m uvicorn cyber_catgirl.main:app --host 127.0.0.1 --port 8765
```

用 `Ctrl+C` 正常停止。不要同时启动两个使用同一 SQLite 文件的实例。

## 紧急停止

优先在控制台打开 kill switch；也可在本机调用：

```powershell
Invoke-RestMethod -Method Post `
  -Uri 'http://127.0.0.1:8765/api/system/kill-switch' `
  -ContentType 'application/json' `
  -Body '{"enabled":true}'
```

打开后，当前待发布任务会被取消。随后停止进程，检查最近平台写入、发布任务和错误日志。

新版后台在工作台、审核中心、内容计划、互动数据、运行日志和系统设置的右上角均提供同一个
“紧急停止”入口。手机端该按钮保留在页面顶部，不会随底部导航折叠。

## 后台页面值守顺序

1. 打开工作台，确认运行模式、异常任务和连接状态；
2. 进入审核中心，逐条处理低风险回复、动态和日报，禁止批量批准；
3. 在内容计划检查下一次草稿生成时间；保存计划不会直接发布；
4. 在互动数据核对数据库统计，缺失日期显示“无数据”而不是推断值；
5. 在运行日志处理 `failed` 和 `visibility_unknown`；后者禁止重发；
6. 只在系统设置维护非敏感配置。凭证状态仅显示“已配置/未配置”。

管理后台是运营与审核界面，不会自行启动真实 B站轮询或发布工作进程。

## 恢复到人工模式

1. 确认进程已停止；
2. 将 `CATGIRL_RUN_MODE` 设为 `manual_only`，清空 `CATGIRL_AUTO_REPLY_ALLOWLIST`；
3. 排查异常原因，核对 B站实际页面与数据库中的 `platform_id`；
4. 重新启动，仅执行健康检查和只读探针；
5. 保持 kill switch 开启，人工确认无待处理写任务；
6. 关闭 kill switch 后仍保持人工模式至少一个完整值守周期。

不要自动重试 `visibility_unknown`：平台可能已经写入，只是核验暂时失败。

## SQLite 备份与恢复

备份前停止应用，避免复制到事务中间状态：

```powershell
New-Item -ItemType Directory -Force .\backups | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
Copy-Item -LiteralPath .\data\cyber_catgirl.db `
  -Destination ".\backups\cyber_catgirl-$stamp.db"
```

恢复时先保留当前数据库副本，再把一个已经人工核验的备份复制回
`data/cyber_catgirl.db`。恢复后先用 `manual_only` 启动并检查健康接口、待审草稿和发布任务，
不得直接恢复自动写入。

## 凭证设置与轮换

B站凭证变量为 `BILI_SESSDATA`、`BILI_JCT`、`BILI_BUVID3`，模型变量为
`DEEPSEEK_API_KEY`。只在本机受控进程环境或操作系统秘密管理工具中设置。不要把值写入
`.env.example`、Git、SQLite、截图或工单。

轮换步骤：

1. 打开 kill switch 并停止服务；
2. 在 B站侧撤销旧会话，生成测试账号的新会话；
3. 更新本机秘密存储；
4. 只运行健康检查和只读探针；
5. 如需验证写入，重新走专用目标、一次授权、写后核验流程；
6. 确认审计记录中没有凭证字符串后再恢复人工模式。

## 平台异常处置

| 异常 | 含义 | 处置 |
|---|---|---|
| `CredentialsUnavailable` | 缺少登录凭证 | 保持只读，检查本机秘密配置 |
| `PlatformRateLimited` | `-509` 或 HTTP 429 等限流 | 停止写入，延长间隔，次日人工复核 |
| `PlatformRiskControl` | `-412`、`-352`、`-403`、`-102` 等 | 立即切人工并检查账号，不绕过验证 |
| `PlatformUnavailable` | 未分类的平台或网络错误 | 记录脱敏详情，保持人工模式 |
| `visibility_unknown` | 写入返回 ID，但页面核验不确定 | 禁止重发，人工到平台检查 |

## 每日收班检查

- B站实际写入数与成功任务数是否一致；
- 是否存在 `failed`、`visibility_unknown` 或长时间 `executing`；
- 待审草稿是否包含敏感话题、个人信息或模型幻觉；
- 白名单是否仍只包含当日批准的用户 ID；
- 审计日志是否无 Cookie、Token、Authorization 值；
- 当日数据库备份是否可读。
