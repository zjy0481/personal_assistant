# V1 验收清单

本文档用于人工确认 V1 日报助手的核心能力。

## 自动验收

```powershell
cd "D:\strange tools\personal assistant"
uv sync
uv run python -m pytest -q
```

所有测试应通过，且不依赖真实 API Key。

## 人工验收项

- [x] 完整生成：运行 `uv run python -m assistant daily` 后，日报包含天气、时事新闻、GitHub 热门、AI 领域要事。
- [x] 网页展示：运行 `uv run python -m assistant`，打开 `http://127.0.0.1:8000/` 可看到同一份日报快照。
- [x] 推送：企业微信群机器人可收到日报；PushPlus 备用渠道可用。
- [x] 降级：关闭或模拟一个数据源失败时，其他内容块仍可生成，日报显示降级状态。
- [x] 来源可追溯：新闻、AI 要事和 GitHub 榜单条目均保留原始链接或来源标识。
- [x] 失败状态：制造推送失败后，首页显示最近一次运行失败，日志保留错误信息。
- [x] 同日去重：同一天再次运行 `uv run python -m assistant daily` 时跳过重复生成与推送。
- [x] 强制重跑：运行 `uv run python -m assistant daily --force` 可重新生成并覆盖当日快照。
