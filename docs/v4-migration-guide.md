# V4 人工迁移指引

> 本文件用于 V4 实现完成后，在服务器上执行首次多用户迁移和邮件账户初始化。

## 0. 开始前

应用路径：`/opt/personal-assistant/app`
应用用户：`personal-assistant`
数据库：`/opt/personal-assistant/app/data/assistant.db`

建议在服务器维护一个单独的运维目录，例如 `/opt/personal-assistant/ops`，用于保存备份、密钥副本和部署日志。**不要把密钥备份提交到 Git。**

## 1. 备份与停服

在迁移前停止服务，避免迁移期间定时任务写入数据库：

```bash
sudo systemctl stop personal-assistant-web.service \
  personal-assistant-wecom.service \
  personal-assistant-alerts.service \
  personal-assistant-daily.service
sudo systemctl stop personal-assistant-daily.timer
sudo mkdir -p /opt/personal-assistant/ops/backups
sudo cp -a /opt/personal-assistant/app/.env /opt/personal-assistant/ops/backups/env.bak.$(date +%Y%m%d-%H%M%S)
sudo cp -a /opt/personal-assistant/app/data/assistant.db /opt/personal-assistant/ops/backups/assistant.db.bak.$(date +%Y%m%d-%H%M%S)
```

同时保留旧代码归档，以支持回退。

## 2. 生成与保存密钥

在服务器上为每个密钥生成一个随机值：

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

将两个值分别写入 `/opt/personal-assistant/app/.env`：

```bash
SECRET_KEY=<生成值1>
ENCRYPTION_KEY=<生成值2>
```

设置权限：

```bash
sudo chown personal-assistant:personal-assistant /opt/personal-assistant/app/.env
sudo chmod 600 /opt/personal-assistant/app/.env
```

不要在终端历史、日志或 Issue 中暴露这两个值。

## 3. 同步依赖与代码

部署 V4 代码后，在应用目录同步依赖：

```bash
cd /opt/personal-assistant/app
sudo -u personal-assistant env HOME=/opt/personal-assistant UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple uv sync --no-dev
```

依赖同步后会创建或更新 `.venv`。不要覆盖项目的 `data/`、`.env` 和服务端 `config.toml`。

## 4. 初始化首个用户并迁移旧数据

```bash
cd /opt/personal-assistant/app
sudo -u personal-assistant env HOME=/opt/personal-assistant \
  .venv/bin/python -m assistant user bootstrap \
  --username <用户名> \
  --email <邮箱>
```

命令会：

- 检查两个密钥是否存在。
- 备份数据库并创建新表。
- 为 `report_snapshots`、`daily_runs`、`content_items`、`chat_messages` 补充 `user_id`。
- 把旧 `default` 数据迁移到新用户。
- 通过交互输入设置密码，不把密码写进命令或日志。

运行成功后，确认 `user list` 中该用户状态为 `active`。

## 5. 登录与个人设置

打开网页登录页，使用用户名或邮箱 + 密码登录。

确认以下设置：

- 时区：例如 `Asia/Shanghai`
- 地区：例如 `上海`
- 日报时间
- 邮件简报时间
- 通知渠道（企业微信群 Webhook 或 PushPlus token）
- 启用状态：`active`

完成应用内登录后，再决定是否关闭旧的全局 token 鉴权或 Nginx Basic Auth。建议先保持旧鉴权一段时间，登录功能稳定后再关闭。

## 6. 添加邮件账户

进入“邮件账户”页面添加账户。

- QQ/163：填写邮箱地址、登录账号和授权码。
- Gmail/Outlook：填写邮箱地址、登录账号和应用专用密码。
- 不要填写网页登录普通密码。
- 如服务商不是预设项，手动填写 IMAP 主机、端口和 SSL/TLS。
- 保存前点击“测试连接”；失败时不会保存错误账户。

## 7. 验证邮件简报

在“邮件简报”页点击“立即生成”：

- 确认能显示最近 7 天内的邮件。
- 确认促销/排除规则的邮件未进入简报。
- 确认重要度排序、追踪提升和降级标记正确。
- 确认通知中只包含“邮件简报已生成，请前往网页端登录查看”，没有邮件正文。

## 8. 回退

如果迁移或功能出现严重问题：

1. 恢复数据库备份。
2. 恢复旧代码归档。
3. 恢复 `.env` 备份。
4. 重启 Web、企业微信、预警和日报服务。

回退后需要重新验证 `/health`、`/app` 和 `/api/status`，并检查日志中是否还有异常。
