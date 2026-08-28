# GitHub Trending 官方页面作为主源

V1 的 GitHub 热门榜单以官方 `github.com/trending` 按周页面作为主数据源，GitHub Search API 仅作为结构变化或网络不可用时的降级方案。

原因是需求要求“近 7 天新增 star”口径，而 GitHub 没有官方 Trending API，Search API 只能按 star 总数、更新时间等维度排序，无法直接计算新增 star；解析官方页面能保持榜单口径，Search API 降级时必须标记为近似数据。
