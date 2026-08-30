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
## V2 Phase 1：网页端、LLM 摘要与问答

### 后端配置

在 `.env` 中补充 DeepSeek 配置：

```dotenv
ASSISTANT_LLM_API_KEY=你的DeepSeek API Key
ASSISTANT_LLM_BASE_URL=https://api.deepseek.com
ASSISTANT_LLM_MODEL=deepseek-v4-flash
ASSISTANT_LLM_SUMMARY_ENABLED=true
```

默认摘要与问答共用每日 300 次、每分钟 10 次限制；连续失败 3 次后熔断。

### 前端构建与运行

```powershell
cd web
npm install
npm run build
```

回到项目根目录启动后端：

```powershell
uv run python -m assistant
```

访问 `http://127.0.0.1:8000/app` 查看新 React 仪表盘；现有 `/`、`/weather` 等 Jinja 页面仍保留为兼容入口。

开发模式下可分别运行：

```powershell
uv run python -m uvicorn assistant.main:app --port 8000
cd web
npm run dev
```

Vite 开发服务默认运行在 `http://127.0.0.1:5173/`，并把 `/api` 代理到 `http://127.0.0.1:8000`。## V2 Phase 2：极端天气预警主动推送

预警监测作为独立进程运行，不受每日 08:00 限制。主源为中央气象台/中国天气网公开实时接口，备用源为和风天气；默认每 10 分钟检查一次，首次发布和等级升级时通过 PushPlus（企业微信群机器人备用）推送，降级与解除只更新网页时间线。

### 配置

在 `config.toml` 或 `.env` 中设置：

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

`weather_alert_locations` 留空时使用 `location`；和风备用源只有在配置 Key/JWT 后才会启用。

### 运行

单次检查（适合测试）：

```powershell
uv run python -m assistant alerts --once
```

常驻监测：

```powershell
uv run python -m assistant alerts
```

根据实际部署服务器配置 systemd、supervisor 或其他进程托管服务。预警监测失败写入 `weather_alert_runs`，网页天气页可查看当前生效预警和完整时间线。

Windows PowerShell 下使用 `uv run` 时，按 `Ctrl+C` 后可能仍出现“终止批处理操作吗(Y/N)？”提示，这是 `uv`/PowerShell 包装行为，不是程序 traceback；按 `Y` 即可。若希望更干净的退出，可改用：

```powershell
.venv\Scripts\python.exe -m assistant alerts
```

监测启动后会打印启动时间和每次检查结果，并显示源、预警数、推送数及下次检查时间。

### 手动验证预警流程

即使当前地区没有真实预警，也可以用模拟预警完整测试首次发布、重复轮询、等级升级、降级和解除：

```powershell
uv run python tests/manual_alert_flow.py
```

脚本默认使用临时数据库和模拟推送，不会发送真实消息，也不会修改 `data/assistant.db`。如果确实要验证推送链路，可以读取当前配置并调用真实推送渠道：

```powershell
uv run python tests/manual_alert_flow.py --live
```

也可以通过 `--location` 和 `--alert-type` 指定测试地区与预警类型。

直接用当前有存活预警的地区验证真实国家气象中心解析：

```powershell
uv run python tests/check_real_nmc_warning.py --location 金寨
```

若同时验证真实推送链路：

```powershell
uv run python tests/check_real_nmc_warning.py --location 金寨 --live
```

注意：`--live` 会真实发送消息；`manual_alert_flow.py --live` 会发送首次发布和升级两条，真实 NMC 检查会按当前生效预警各发送一条，请避免重复运行。