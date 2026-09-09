# Contributing

感谢你愿意改进 Bilibili Cyber Catgirl。项目接受错误修复、测试、文档、可观察性、人设质量和平台连接器方面的贡献。

## 开发环境

需要 Python 3.11 或 3.12：

```bash
python -m venv .venv
python -m pip install -e '.[dev]'
python -m pytest -q
python -m ruff check src tests
```

## 提交修改

1. Fork 仓库并从 `main` 创建功能分支；
2. 为行为变化先补充失败测试；
3. 保持连接器、服务、Web 和持久化边界清晰；
4. 运行完整测试与 Ruff；
5. 在 Pull Request 中说明安全影响、测试证据和迁移步骤。

## 安全要求

任何扩大平台写入范围的修改必须同时提供：默认关闭的配置、服务层授权检查、幂等与重试策略、限流/风控分类、脱敏审计、kill switch 行为以及允许/拒绝路径测试。

禁止在测试、截图、Issue 或 Pull Request 中使用真实 Cookie、API Key、用户评论数据库或个人身份信息。

## 代码风格

- Python 目标版本为 3.11，Ruff 行宽为 100；
- 服务通过端口依赖平台能力，避免把第三方 SDK 类型泄漏到领域层；
- 错误使用稳定错误码，不把上游原始响应直接暴露给页面；
- 测试优先使用 Fake、MockTransport 和临时 SQLite。

安全漏洞请按 [SECURITY.md](SECURITY.md) 私密报告，不要创建公开 Issue。
