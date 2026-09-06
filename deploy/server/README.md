# 云服务器部署说明

本目录是在 Ubuntu Server 24.04 LTS 上部署 `personal-assistant` 使用的 systemd 与 Nginx 配置模板。

## 已配置的服务器结构

- 代码目录：`/opt/personal-assistant/app`
- 运行用户：`personal-assistant`
- 数据目录：`/opt/personal-assistant/app/data`
- 网页：Nginx `80` → FastAPI/Uvicorn `127.0.0.1:8000`
- 日报：`personal-assistant-daily.timer`，每天 08:00（Asia/Shanghai）
- 预警：`personal-assistant-alerts.service`，常驻轮询
- 企业微信智能机器人：`personal-assistant-wecom.service`，长连接常驻
- 防火墙：UFW 放通 `22`、`80`、`443`

## 常用命令

```bash
sudo systemctl status personal-assistant-web.service
sudo journalctl -u personal-assistant-web.service -f
sudo systemctl status personal-assistant-alerts.service
sudo systemctl status personal-assistant-wecom.service
sudo systemctl list-timers personal-assistant-daily.timer
sudo nginx -t && sudo systemctl reload nginx
```

## 配置提醒

- 密钥只放在 `/opt/personal-assistant/app/.env`，权限为 `600`。
- 公网访问由 Nginx Basic Auth 保护；密码保存在 `/etc/nginx/.htpasswd`。
- 若后续使用域名，建议接入 HTTPS（例如 `certbot`）后再开放 `443`。
- 安装依赖时如官方 PyPI 不可达，可使用清华镜像：
  `UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple uv sync --no-dev`。

## V3 联网问答配置

V3 不需要新增 systemd 服务，网页和企业微信智能机器人共用现有服务。

- `web_search_enabled`：全局联网开关，默认 `true`；故障时可立即设为 `false` 并重启 Web/WeCom 服务，网页端与企微都会退回离线问答。
- `web_search_model`：联网问答模型，默认跟随 `llm_model`；可显式设为 `deepseek-v4-flash` 或 `deepseek-v4-pro`。
- `web_search_max_rounds`：单次最多搜索轮数，默认 `2`。
- `web_page_max_reads`：单次最多读取网页数，默认 `3`。
- `web_fetch_timeout_seconds`：单次外部请求超时，默认 `10`。
- `web_page_cache_ttl_seconds`：网页正文缓存时间，默认 `600`。
- `web_daily_limit`：每日联网问答上限，默认 `100`；达到上限后自动降级为离线回答。
- `web_blocked_hosts`：业务黑名单域名列表，默认空。
- `http_proxy` / `https_proxy`：服务器无法直连外部站点时的可选代理，默认空；本机开发无需配置。

以上配置可放在 `/opt/personal-assistant/app/.env` 或同目录 `config.toml`。部署按交接文档的归档同步方式更新代码，保留数据目录和 `.env`，重启 `personal-assistant-web.service` 与 `personal-assistant-wecom.service` 后验证。
