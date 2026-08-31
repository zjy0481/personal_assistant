import type { ContentBlock, ContentItem, Favorite, Report, RunStatus, TrendPayload, WeatherAlert, WeatherAlertEvent, WeatherAlertRun } from '../types'
import { EmptyState } from './EmptyState'
import { FavoritesPanel } from './FavoritesPanel'
import { ItemCard } from './ItemCard'
import { StatusPill } from './StatusPill'
import { TrendsPanel } from './TrendsPanel'

type View = 'dashboard' | 'weather' | 'news' | 'github' | 'ai' | 'favorites' | 'trends'

interface ReportDashboardProps {
  report: Report
  view: View
  runStatus: RunStatus | null
  weatherAlerts: WeatherAlert[]
  weatherEvents: WeatherAlertEvent[]
  weatherRun: WeatherAlertRun | null
  favorites: Favorite[]
  trends: TrendPayload | null
  trendLoading: boolean
  trendError: string
  trendDays: number
  onTrendDaysChange: (days: number) => void
  onToggleFavorite: (item: ContentItem | Favorite, blockKind: string) => void
  onAsk: (item: ContentItem) => void
}

export function ReportDashboard({
  report,
  view,
  runStatus,
  weatherAlerts,
  weatherEvents,
  weatherRun,
  favorites,
  trends,
  trendLoading,
  trendError,
  trendDays,
  onTrendDaysChange,
  onToggleFavorite,
  onAsk,
}: ReportDashboardProps) {
  const visibleBlocks = filterBlocks(report.blocks, view)

  if (view === 'favorites') {
    return (
      <FavoritesPanel
        favorites={favorites}
        onRemove={(item) => onToggleFavorite(item, item.block_kind)}
      />
    )
  }

  if (view === 'trends') {
    return (
      <TrendsPanel
        data={trends}
        loading={trendLoading}
        error={trendError}
        days={trendDays}
        onDaysChange={onTrendDaysChange}
      />
    )
  }

  return (
    <div>
      <header className="mb-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="mb-2 flex items-center gap-2">
              <StatusPill status={runStatus?.status} />
              {report.degraded && <StatusPill status="degraded" />}
            </div>
            <h1 className="text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">
              {report.title}
            </h1>
            <p className="mt-2 text-sm text-slate-500">
              {report.location} · {formatDateTime(report.generated_at)}
            </p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-right shadow-sm">
            <div className="text-xs text-slate-400">最近运行</div>
            <div className="mt-1 text-sm font-medium text-slate-800">
              {runStatus ? `${statusLabel(runStatus.status)} · ${runStatus.message || '无详细信息'}` : '暂无运行记录'}
            </div>
          </div>
        </div>
      </header>

      {(view === 'weather' || view === 'dashboard') && (
        <WeatherAlertPanel
          alerts={weatherAlerts}
          events={weatherEvents}
          run={weatherRun}
        />
      )}

      {visibleBlocks.length === 0 ? (
        <EmptyState title="暂无内容" description="当前日报没有对应板块，等待下一次生成。" />
      ) : (
        <div className="space-y-8">
          {visibleBlocks.map((block) => (
            <BlockSection key={block.kind} block={block} favorites={favorites} onToggleFavorite={onToggleFavorite} onAsk={onAsk} />
          ))}
        </div>
      )}
    </div>
  )
}

function WeatherAlertPanel({
  alerts,
  events,
  run,
}: {
  alerts: WeatherAlert[]
  events: WeatherAlertEvent[]
  run: WeatherAlertRun | null
}) {
  const active = alerts.filter((alert) => alert.status === 'active')
  const timeline = events.slice(0, 30)

  return (
    <section className="mb-8 overflow-hidden rounded-2xl border border-amber-200 bg-amber-50/70 p-6 shadow-sm">
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">极端天气预警</h2>
          <p className="mt-1 text-xs text-slate-500">
            {active.length > 0 ? `当前生效 ${active.length} 条` : '当前没有生效预警'}
            {run ? ` · 最近检查 ${formatDateTime(run.checked_at)}` : ''}
            {run?.fallback ? ' · 备用源' : ''}
          </p>
        </div>
        <span className="rounded-full bg-white px-2.5 py-1 text-xs font-medium text-amber-700 shadow-sm">
          {run ? statusLabel(run.status) : '暂无检查记录'}
        </span>
      </div>

      {active.length > 0 ? (
        <div className="grid gap-4 md:grid-cols-2">
          {active.map((alert) => (
            <article key={`${alert.location}-${alert.alert_type}`} className="rounded-xl border border-amber-200/80 bg-white p-4">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="font-semibold text-slate-900">{alert.title || `${alert.alert_type}预警`}</h3>
                  <p className="mt-1 text-xs text-slate-500">
                    {alert.location} · {sourceLabel(alert.source)} · {formatDateTime(alert.published_at)}
                  </p>
                </div>
                <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${levelClass(alert.level)}`}>
                  {alert.level}
                </span>
              </div>
              {alert.description && (
                <p className="mt-3 max-h-28 overflow-hidden text-sm leading-relaxed text-slate-600">
                  {alert.description}
                </p>
              )}
              {alert.safety_guidance && (
                <div className="mt-3 rounded-lg bg-slate-50 p-3 text-xs leading-relaxed text-slate-500">
                  <span className="font-medium text-slate-700">防御指南：</span>
                  {alert.safety_guidance}
                </div>
              )}
              {alert.source_url && (
                <a
                  href={alert.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-3 inline-block text-sm font-medium text-emerald-700 hover:text-emerald-600"
                >
                  查看官方预警原文 →
                </a>
              )}
            </article>
          ))}
        </div>
      ) : (
        <p className="rounded-xl border border-dashed border-amber-200 bg-white/70 px-4 py-6 text-center text-sm text-slate-500">
          暂无生效预警。监测服务会在配置地区出现极端天气时主动更新并推送。
        </p>
      )}

      <div className="mt-6">
        <h3 className="mb-2 text-sm font-semibold text-slate-700">预警时间线</h3>
        {timeline.length > 0 ? (
          <div className="overflow-x-auto rounded-xl bg-white shadow-sm">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead>
                <tr className="border-b border-slate-100 text-xs text-slate-400">
                  <th className="px-4 py-3 font-medium">时间</th>
                  <th className="px-4 py-3 font-medium">事件</th>
                  <th className="px-4 py-3 font-medium">地区</th>
                  <th className="px-4 py-3 font-medium">类型</th>
                  <th className="px-4 py-3 font-medium">等级</th>
                  <th className="px-4 py-3 font-medium">来源</th>
                  <th className="px-4 py-3 font-medium">推送</th>
                </tr>
              </thead>
              <tbody>
                {timeline.map((event) => (
                  <tr key={event.event_id} className="border-b border-slate-100 last:border-b-0">
                    <td className="whitespace-nowrap px-4 py-3 text-slate-600">{formatDateTime(event.occurred_at)}</td>
                    <td className="px-4 py-3 font-medium text-slate-700">{eventLabel(event.event_type)}</td>
                    <td className="px-4 py-3 text-slate-600">{event.location}</td>
                    <td className="px-4 py-3 text-slate-600">{event.alert_type}</td>
                    <td className="px-4 py-3"><span className={`rounded-full px-2 py-0.5 text-xs font-medium ${levelClass(event.level)}`}>{event.level}</span></td>
                    <td className="px-4 py-3 text-slate-500">{sourceLabel(event.source)}</td>
                    <td className="px-4 py-3 text-slate-500">{pushLabel(event.push_status)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-slate-500">暂无时间线记录。</p>
        )}
      </div>
    </section>
  )
}

function BlockSection({
  block,
  favorites,
  onToggleFavorite,
  onAsk,
}: {
  block: ContentBlock
  favorites: Favorite[]
  onToggleFavorite: (item: ContentItem | Favorite, blockKind: string) => void
  onAsk: (item: ContentItem) => void
}) {
  return (
    <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">{block.title}</h2>
          <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
            <StatusPill status={block.status} />
            {block.message && <span>{block.message}</span>}
            {block.sources?.length ? <span>{block.sources.join(' · ')}</span> : null}
          </div>
        </div>
        <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-500">
          {block.items.length} 条
        </span>
      </div>

      {block.kind === 'weather' ? (
        <WeatherBlock block={block} />
      ) : (
        <div className="divide-y divide-slate-100">
          {block.items.length > 0 ? (
            block.items.map((item) => (
              <ItemCard
                key={item.item_id || item.url || item.title}
                item={item}
                blockKind={block.kind}
                isFavorite={favorites.some((favorite) => favorite.item_id === item.item_id)}
                onFavorite={(target) => onToggleFavorite(target, block.kind)}
                onAsk={onAsk}
              />
            ))
          ) : (
            <p className="py-4 text-sm text-slate-500">暂无条目</p>
          )}
        </div>
      )}
    </section>
  )
}

function WeatherBlock({ block }: { block: ContentBlock }) {
  const details = block.details ?? {}
  const current = (details.current ?? {}) as Record<string, unknown>
  const days = Array.isArray(details.days) ? (details.days as Array<Record<string, unknown>>) : []

  return (
    <div className="grid gap-6 lg:grid-cols-[240px_1fr]">
      <div className="rounded-xl bg-slate-50 p-5">
        <div className="text-xs text-slate-500">当前天气</div>
        <div className="mt-2 text-3xl font-semibold tracking-tight text-slate-900">
          {current.temperature != null ? `${Number(current.temperature).toFixed(0)}°C` : '--'}
        </div>
        <div className="mt-1 text-sm text-slate-600">
          {String(current.description ?? '暂无描述')}
        </div>
        <dl className="mt-4 space-y-1 text-xs text-slate-500">
          <div className="flex justify-between"><dt>湿度</dt><dd>{current.humidity != null ? `${current.humidity}%` : '--'}</dd></div>
          <div className="flex justify-between"><dt>风速</dt><dd>{current.wind_speed != null ? `${current.wind_speed} km/h` : '--'}</dd></div>
          <div className="flex justify-between"><dt>AQI</dt><dd>{String(current.air_quality_aqi ?? '--')}</dd></div>
        </dl>
      </div>
      <div className="min-w-0 overflow-x-auto">
        <table className="w-full min-w-[520px] text-left text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-xs text-slate-400">
              <th className="pb-3 font-medium">日期</th>
              <th className="pb-3 font-medium">天气</th>
              <th className="pb-3 font-medium">最低 / 最高</th>
              <th className="pb-3 font-medium">降水概率</th>
            </tr>
          </thead>
          <tbody>
            {days.map((day, index) => (
              <tr key={String(day.date ?? index)} className="border-b border-slate-100 last:border-b-0">
                <td className="py-3 text-slate-700">{String(day.date ?? '--')}</td>
                <td className="py-3 text-slate-700">{String(day.description ?? '--')}</td>
                <td className="py-3 text-slate-700">
                  {day.temp_min != null && day.temp_max != null
                    ? `${Number(day.temp_min).toFixed(0)}°C ~ ${Number(day.temp_max).toFixed(0)}°C`
                    : '--'}
                </td>
                <td className="py-3 text-slate-700">
                  {day.precipitation_probability != null
                    ? `${day.precipitation_probability}%`
                    : '--'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function filterBlocks(blocks: ContentBlock[], view: View) {
  if (view === 'dashboard') return blocks
  return blocks.filter((block) => block.kind === view)
}

function formatDateTime(value?: string | null) {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function statusLabel(status?: string) {
  const labels: Record<string, string> = {
    ok: '成功',
    failed: '失败',
    skipped: '已跳过',
    pushplus: '已推送',
    wecom_group: '已推送',
    paused: '已暂停',
  }
  return labels[status ?? ''] ?? status ?? '未知'
}

function eventLabel(type: string) {
  const labels: Record<string, string> = {
    initial: '首次发布',
    upgraded: '等级升级',
    downgraded: '等级降级',
    cancelled: '已解除',
    updated: '更新',
  }
  return labels[type] ?? type
}

function pushLabel(status: string) {
  if (status === 'pushed') return '已推送'
  if (status === 'pending' || status === 'failed') return '待重试'
  return '无需推送'
}

function sourceLabel(source: string) {
  const labels: Record<string, string> = {
    nmc: '中央气象台',
    qweather: '和风天气',
  }
  return labels[source] ?? source
}
function levelClass(level: string) {
  const classes: Record<string, string> = {
    '蓝色': 'bg-blue-50 text-blue-700',
    '黄色': 'bg-amber-50 text-amber-700',
    '橙色': 'bg-orange-50 text-orange-700',
    '红色': 'bg-red-50 text-red-700',
  }
  return classes[level] ?? 'bg-slate-50 text-slate-600'
}
