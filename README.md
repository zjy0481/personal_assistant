# personal_assistant

个人日报助手，用于汇总天气、时事新闻、GitHub Trending 与 AI 领域要事，并通过 PushPlus 推送、企业微信群机器人备用和网页端展示同一份日报快照。

## V1 范围

- 单用户每日日报。
- 内容板块：天气、时事新闻、GitHub 热门、AI 领域要事。
- 推送：PushPlus 微信服务号为主渠道，企业微信群机器人为备用渠道。
- 网页：首页及天气、新闻、GitHub、AI 四个独立页面。
- 数据源：单个数据源失败时跳过对应内容块并标记降级，不影响其他内容块和日报整体生成。
- 来源追溯：新闻、AI 要事和 GitHub 榜单条目均保留原始链接或来源标识。

## 前置条件

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) 包管理器
- PushPlus 账号并完成微信实名认证（用于主渠道）
- 可选：企业微信群机器人 Webhook（用于备用渠道）

## 安装

```powershell
uv sync
```

## 配置

复制 `.env.example` 为 `.env` 并填写：

```dotenv
ASSISTANT_PUSHPLUS_TOKEN=你的PushPlus用户token
ASSISTANT_WECOM_GROUP_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key
```

复制 `config.example.toml` 为 `config.toml`，按需修改地区、时区、数据源白名单、推送渠道和重试配置。

密钥只保存在 `.env` 或 GitHub Secrets，不应提交到 Git。

## 本地运行

生成日报快照：

```powershell
uv run python tests/manual_generate_report.py
```

启动网页：

```powershell
uv run python -m assistant
```

访问 http://127.0.0.1:8000/ 查看日报。

## 生成并推送日报

```powershell
uv run python -m assistant daily
```

当日已有日报快照时默认跳过，避免重复推送：

```powershell
uv run python -m assistant daily --force
```

`--force` 会重新生成并覆盖当日快照，适合手动测试或补救推送。

## 运行测试与验证推送

运行全量测试：

```powershell
uv run python -m pytest -q
```

验证 PushPlus 与企业微信群机器人：

```powershell
uv run python tests/verify_push.py
```

PushPlus 接口返回 `code=200` 只表示请求已接受，仍需在微信中人工确认是否收到消息。

## 调度与云端部署

- GitHub Actions 工作流：`.github/workflows/daily-report.yml`，每天 08:00（Asia/Shanghai）生成并推送日报。
- GitHub Actions Secrets：`ASSISTANT_PUSHPLUS_TOKEN`、`ASSISTANT_WECOM_GROUP_WEBHOOK`。
- 后续若租赁云服务器，可将同一入口迁移为 systemd/cron 或 APScheduler；业务代码和配置模型无需改动。
- 公网网页部署时应设置 `web_require_auth=true` 并配置 `auth_token`。

## 关键文档

- [CONTEXT.md](CONTEXT.md)：领域术语与 V1 边界。
- [docs/adr/0003-pushplus-push-channel.md](docs/adr/0003-pushplus-push-channel.md)：推送渠道决策。
- [docs/acceptance.md](docs/acceptance.md)：V1 验收清单。