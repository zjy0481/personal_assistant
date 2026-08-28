# personal_assistant

个人日报助手，用于汇总天气、新闻、GitHub Trending 与 AI 领域要事，并提供日报快照查看能力。

## 推送机制

- **主渠道：PushPlus**。通过微信服务号接收日报，不需要域名、服务器、公网 IP 或本机内网穿透；需完成 PushPlus 微信实名认证并保存 token。
- **备用渠道：企业微信群机器人 Webhook**。PushPlus 失败时按顺序尝试，不受企业微信可信 IP 限制。
- 默认渠道顺序为 `pushplus`、`wecom_group`，可通过 `push_channels` 配置。
- 日报正文统一使用 Markdown，每个板块默认推送 5 条，可配置 `push_max_items` 调整。
- 当前已确定方案记录在 [ADR-0003](docs/adr/0003-pushplus-push-channel.md)；原企业微信自建应用方案见 [ADR-0002](docs/adr/0002-wechat-push-channel.md)，已标记为被取代。

## 配置

1. 复制 `.env.example` 为 `.env`，并填写 `ASSISTANT_PUSHPLUS_TOKEN`。
2. 在 PushPlus 获取用户 token，完成实名认证。
3. 如需备用渠道，在企业微信中创建群机器人并填写其完整 Webhook URL 到 `ASSISTANT_WECOM_GROUP_WEBHOOK`。
4. 复制 `config.example.toml` 为 `config.toml`，按需修改地区、时区和数据源。
5. 密钥只保存在 `.env` 或 GitHub Secrets，不应提交到 Git。

## 本地运行

```powershell
uv sync
uv run python tests/manual_generate_report.py
uv run python -m assistant
```

生成并推送当天日报：

```powershell
uv run python -m assistant daily
```

访问 `http://127.0.0.1:8000/` 查看日报快照。

## 验证推送

先在 `.env` 中配置至少一个推送凭证，然后运行：

```powershell
uv run python tests/verify_push.py
```

脚本会依次验证 PushPlus 与企业微信群机器人。PushPlus 接口只返回“请求已接受”，因此还需要在微信中人工确认是否收到验证消息；群机器人验证后请在对应企业微信群中确认。


## 后续计划

- 实现 PushPlus 与企业微信群机器人推送适配器，并接入现有 `PushAdapter` 边界。
- 已提供 `.github/workflows/daily-report.yml`，每天 08:30（Asia/Shanghai）生成并推送日报。
- 后续若租赁服务器，将同一入口迁移为服务器定时任务，不改动业务代码。