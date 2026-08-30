# 云服务器部署说明

本目录是在 Ubuntu Server 24.04 LTS 上部署 `personal-assistant` 使用的 systemd 与 Nginx 配置模板。

## 已配置的服务器结构

- 代码目录：`/opt/personal-assistant/app`
- 运行用户：`personal-assistant`
- 数据目录：`/opt/personal-assistant/app/data`
- 网页：Nginx `80` → FastAPI/Uvicorn `127.0.0.1:8000`
- 日报：`personal-assistant-daily.timer`，每天 08:00（Asia/Shanghai）
- 预警：`personal-assistant-alerts.service`，常驻轮询
- 防火墙：UFW 放通 `22`、`80`、`443`

## 常用命令

```bash
sudo systemctl status personal-assistant-web.service
sudo journalctl -u personal-assistant-web.service -f
sudo systemctl status personal-assistant-alerts.service
sudo systemctl list-timers personal-assistant-daily.timer
sudo nginx -t && sudo systemctl reload nginx
```

## 配置提醒

- 密钥只放在 `/opt/personal-assistant/app/.env`，权限为 `600`。
- 公网访问由 Nginx Basic Auth 保护；密码保存在 `/etc/nginx/.htpasswd`。
- 若后续使用域名，建议接入 HTTPS（例如 `certbot`）后再开放 `443`。
- 安装依赖时如官方 PyPI 不可达，可使用清华镜像：
  `UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple uv sync --no-dev`。
