# 采用数据库重建替代 default 数据迁移

- 状态：已接受
- 日期：2026-09-16
- 取代：ADR-0006 中「现有日报、收藏、趋势、预警、聊天等数据必须迁移到首次用户，部分表需要补充 user_id」的条款（部分取代）

V4 不再把 `default` 历史数据迁移到首个用户，而是由 `user bootstrap` 在备份后直接重建数据库 schema。

这样决定的前提是：当前部署仍处于小范围测试阶段，库内数据全部为测试期产物（重建前实测 3292 行，其中日报快照 18 份、内容条目 514 条、预警轮询记录 2403 条、问答历史 34 条），没有需要长期保留的业务数据。同时旧 schema 本身存在结构问题——`content_items.item_id` 是全局唯一约束，`report_snapshots`、`daily_runs`、`content_items`、`chat_messages` 缺少 `user_id`——在 SQLite 上修改唯一约束必须重建表，逐表 ALTER 加回填的复杂度高于直接重建，而且回填逻辑属于一次性代码，没有复用价值。

选择重建而不是迁移，是因为迁移路径的唯一价值在于保住历史数据，而当历史数据没有保留价值时，迁移代码只剩下引入缺陷的机会成本。

## 影响

- `user bootstrap` 的职责从「迁移 default 数据」变为「备份后重建 schema 并创建首个用户」；重建前的时间戳备份是唯一的回退材料。
- V3 验收期产生的测试数据（历史日报、问答历史、预警时间线）在重建后不再可查；已关闭的 V3 验收与部署结论不受影响。
- 新 schema 一次性修正结构问题：4 张表补齐 `user_id`，`content_items` 改为 `UNIQUE(user_id, item_id)`。
- 文档同步修改：`docs/v4-requirements.md`、`docs/v4-acceptance.md`、`docs/v4-migration-guide.md`。
- ADR-0006 的其余决策（服务端会话归属、Argon2id、Fernet、IMAP 增量同步、日报与简报分离、通知只提示不推正文等）继续有效。
- 后续版本若需要在保留数据的前提下演进 schema，必须重新引入迁移路径，不能沿用本次的重建做法。