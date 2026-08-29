import type { ContentBlock, ContentItem, Report, RunStatus } from '../types'
import { EmptyState } from './EmptyState'
import { ItemCard } from './ItemCard'
import { StatusPill } from './StatusPill'

type View = 'dashboard' | 'weather' | 'news' | 'github' | 'ai' | 'favorites' | 'trends'

interface ReportDashboardProps {
  report: Report
  view: View
  runStatus: RunStatus | null
  onAsk: (item: ContentItem) => void
}

export function ReportDashboard({
  report,
  view,
  runStatus,
  onAsk,
}: ReportDashboardProps) {
  const visibleBlocks = filterBlocks(report.blocks, view)

  if (view === 'favorites' || view === 'trends') {
    return (
      <EmptyState
        title={view === 'favorites' ? '收藏功能将在第三阶段提供' : '趋势可视化将在第三阶段提供'}
        description="Phase 1 已完成日报展示、摘要与问答，收藏和图表可作为后续开发入口。"
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

      {visibleBlocks.length === 0 ? (
        <EmptyState title="暂无内容" description="当前日报没有对应板块，等待下一次生成。" />
      ) : (
        <div className="space-y-8">
          {visibleBlocks.map((block) => (
            <BlockSection key={block.kind} block={block} onAsk={onAsk} />
          ))}
        </div>
      )}
    </div>
  )
}

function BlockSection({
  block,
  onAsk,
}: {
  block: ContentBlock
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
              <ItemCard key={item.item_id || item.url || item.title} item={item} onAsk={onAsk} />
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

function formatDateTime(value: string) {
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

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    ok: '成功',
    failed: '失败',
    skipped: '已跳过',
    pushplus: '已推送',
    wecom_group: '已推送',
  }
  return labels[status] ?? status
}