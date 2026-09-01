# personal_assistant

个人日报助手：聚合天气、时事新闻、GitHub Trending 与 AI 领域要事，生成每日日报，并通过网页端、企业微信智能机器人、PushPlus 和企业微信群机器人展示同一份快照。目前 V2 功能已完整交付。

## 功能总览

- 每日日报：天气、时事新闻、GitHub 热门、AI 领域要事。
- 前端：React + Vite + Tailwind，提供日报仪表盘、天气、新闻、GitHub、AI、收藏和趋势页面。
- LLM：DeepSeek 中文摘要与日报问答，网页端和企业微信共用统一 LLM 服务。
- 企业微信智能机器人：群聊中 `@` 机器人提问，机器人调用 LLM 回复；支持长连接、心跳、断线重连和消息去重。
- 极端天气预警：独立进程轮询中央气象台/中国天气网，和风天气备用；首次发布和等级升级主动推送。
- 收藏：新闻、AI 要事、GitHub 项目可收藏/取消收藏，数据持久化到 SQLite。
- 数据可视化：新闻热词与 GitHub 热度两张 ECharts 图表，支持最近 7 天/30 天切换；不包含天气趋势。
- 推送：PushPlus 主渠道、企业微信群机器人备用；预警通过企业微信 Webhook 主动推送。
- 数据源降级：单个数据源失败时跳过对应内容块并标记降级，不影响其他内容块。

## 技术栈

- Python 3.12+
- uv
- FastAPI + Uvicorn
- SQLite
- React + Vite + Tailwind + ECharts
- jieba（新闻热词分词）
- DeepSeek API
- 企业微信智能机器人长连接
- systemd + Nginx（云服务器部署）

## 前置条件

- Python 3.12+
- uv
- PushPlus 账号（主推送渠道）
- DeepSeek API Key
- 企业微信智能机器人 BotID/Secret（群聊问答）
- 企业微信群机器人 Webhook（可选备用推送）
- Node.js 20+（仅构建前端时需要）

## 安装

```powershell
uv sync
```

构建前端：

```powershell
cd web
npm install
npm run build
```

开发模式可分别运行：

```powershell
uv run python -m uvicorn assistant.main:app --port 8000
cd web
npm run dev
```

Vite 默认运行在 `http://127.0.0.1:5173/`，并把 `/api` 代理到 `http://127.0.0.1:8000`。

## 配置

复制 `.env.example` 为 `.env`，复制 `config.example.toml` 为 `config.toml`，按需填写。密钥只保存在 `.env`，不要提交到 Git。

### 基础配置

```dotenv
ASSISTANT_PUSHPLUS_TOKEN=你的PushPlus用户token
ASSISTANT_WECOM_GROUP_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key
```

### LLM 配置

```dotenv
ASSISTANT_LLM_PROVIDER=deepseek
ASSISTANT_LLM_API_KEY=你的DeepSeek API Key
ASSISTANT_LLM_BASE_URL=https://api.deepseek.com
ASSISTANT_LLM_MODEL=deepseek-v4-flash
ASSISTANT_LLM_SUMMARY_ENABLED=true
```

摘要与问答共享每日 300 次、每分钟 10 次的限制，连续失败 3 次后熔断。

### 企业微信智能机器人

```dotenv
ASSISTANT_WECOM_AI_ENABLED=true
ASSISTANT_WECOM_AI_MODE=long_connection
ASSISTANT_WECOM_AI_BOT_ID=你的BotID
ASSISTANT_WECOM_AI_BOT_SECRET=你的Secret
ASSISTANT_WECOM_AI_BOT_NAME=雪球日报助手
ASSISTANT_WECOM_AI_ALLOWED_CHAT_IDS=[]
ASSISTANT_WECOM_AI_ALLOWED_USER_IDS=[]
ASSISTANT_WECOM_AI_WS_URL=wss://openws.work.weixin.qq.com
```

群聊/用户白名单初始可留空用于联调。第一次收到消息后，从日志中获取 `chatid` 和 `userid`，再填入白名单。回调模式所需的 `Token`、`EncodingAESKey` 暂不需要，标注在 `.env.example` 中。

### 极端天气预警

```toml
weather_alert_enabled = true
weather_alert_locations = []
weather_alert_interval_seconds = 600
weather_alert_types = []
weather_alert_retention_days = 180
qweather_api_key = ""
qweather_token = ""
qweather_api_host = "https://api.qweather.com"
qweather_location_id = ""
```

`weather_alert_locations` 留空时使用 `location`；和风备用源只有在配置 Key/JWT 后启用。

### 趋势与收藏

```dotenv
ASSISTANT_TREND_RETENTION_DAYS=180
ASSISTANT_NEWS_TREND_MIN_COUNT=1
```

收藏永久保留；趋势快照默认保留 180 天。

## 本地运行

启动网页：

```powershell
uv run python -m assistant
```

访问 `http://127.0.0.1:8000/app` 查看 React 仪表盘。旧的 `/`、`/weather`、`/news`、`/github`、`/ai` Jinja 页面仍保留为兼容入口。

生成并推送日报：

```powershell
uv run python -m assistant daily
```

当日已有快照时默认跳过；强制重跑：

```powershell
uv run python -m assistant daily --force
```

极端天气预警单次检查：

```powershell
uv run python -m assistant alerts --once
```

极端天气预警常驻轮询：

```powershell
uv run python -m assistant alerts
```

企业微信智能机器人：

```powershell
uv run python -m assistant wecom
```

`bot` 是 `wecom` 的别名：

```powershell
uv run python -m assistant bot
```

## API

主要接口：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/reports/latest` | 最新日报快照 |
| GET | `/api/reports/{report_date}` | 指定日期日报 |
| GET | `/api/status` | LLM 与服务状态 |
| GET | `/api/run-status` | 最近一次日报运行状态 |
| GET | `/api/chat/history` | 问答会话历史 |
| POST | `/api/chat` | 日报问答 |
| GET | `/api/weather-alerts` | 当前预警、时间线和最近检查 |
| GET | `/api/favorites` | 收藏列表 |
| POST | `/api/favorites` | 新增/恢复收藏，幂等 |
| DELETE | `/api/favorites/{item_id}` | 取消收藏 |
| GET | `/api/trends?days=7` | 新闻热词与 GitHub 热度趋势 |

## 测试

```powershell
uv run python -m pytest -q
```

验证推送：

```powershell
uv run python tests/verify_push.py
```

预警模拟测试：

```powershell
uv run python tests/manual_alert_flow.py
uv run python tests/check_real_nmc_warning.py --location 金寨
```

`--live` 会真实发送消息，避免重复运行。

## 云服务器部署

部署模板位于 `deploy/server/`，包括：

- `personal-assistant-web.service`：FastAPI 网页服务
- `personal-assistant-daily.service` / `.timer`：每日 08:00 生成并推送日报
- `personal-assistant-alerts.service`：极端天气预警常驻进程
- `personal-assistant-wecom.service`：企业微信智能机器人长连接
- `personal-assistant-nginx.conf`：Nginx 反向代理与 Basic Auth

详细说明见 [deploy/server/README.md](deploy/server/README.md)。

当前项目的 GitHub Actions 日报定时触发已关闭，改为云服务器 systemd timer 执行；GitHub Actions 仅保留手动 `workflow_dispatch`。

公网部署建议使用 Nginx Basic Auth；若启用后端 `web_require_auth=true`，还需要配置 `auth_token`。

## 数据保留

- 日报、预警、趋势快照默认保留 180 天
- 收藏永久保留
- 问答会话保留 7 天

## 关键文档

- [CONTEXT.md](CONTEXT.md)：领域术语与项目边界
- [docs/v2-requirements.md](docs/v2-requirements.md)：V2 需求确认
- [docs/acceptance.md](docs/acceptance.md)：验收清单
- [docs/agents/issue-tracker.md](docs/agents/issue-tracker.md)：Issue 工作流
- [deploy/server/README.md](deploy/server/README.md)：云服务器部署说明
