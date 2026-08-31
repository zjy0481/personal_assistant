import * as echarts from 'echarts'
import { useEffect, useRef, type RefObject } from 'react'
import type { GitHubRepo, NewsTerm, TrendPayload } from '../types'
import { EmptyState } from './EmptyState'

interface TrendsPanelProps {
  data: TrendPayload | null
  loading: boolean
  error: string
  days: number
  onDaysChange: (days: number) => void
}

export function TrendsPanel({ data, loading, error, days, onDaysChange }: TrendsPanelProps) {
  const newsRef = useRef<HTMLDivElement | null>(null)
  const githubRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const node = newsRef.current
    if (!node) return
    const chart = echarts.init(node)
    chart.setOption(buildNewsOption(data))
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      chart.dispose()
    }
  }, [data])

  useEffect(() => {
    const node = githubRef.current
    if (!node) return
    const chart = echarts.init(node)
    chart.setOption(buildGithubOption(data))
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => {
      window.removeEventListener('resize', resize)
      chart.dispose()
    }
  }, [data])

  return (
    <section>
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">趋势可视化</h1>
          <p className="mt-2 text-sm text-slate-500">仅展示新闻热词与 GitHub 热度，数据来自日报快照，不实时访问外部源。</p>
        </div>
        <div className="flex gap-2">
          {[7, 30].map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => onDaysChange(value)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium transition ${days === value ? 'bg-slate-900 text-white' : 'border border-slate-200 bg-white text-slate-600 hover:bg-slate-50'}`}
            >
              最近 {value} 天
            </button>
          ))}
        </div>
      </header>

      {loading ? (
        <EmptyState title="正在加载趋势…" description="正在从历史日报快照聚合指标。" />
      ) : error ? (
        <EmptyState title="趋势加载失败" description={error} />
      ) : !data || data.dates.length === 0 || (data.news.length === 0 && data.github.length === 0) ? (
        <EmptyState title="暂无趋势数据" description="生成日报后会在这里展示新闻热词与 GitHub 热度。" />
      ) : (
        <div className="grid gap-6 xl:grid-cols-2">
          <ChartCard title="新闻热词变化" description="每日 Top 10 热词中最常出现的 Top 5" refNode={newsRef} />
          <ChartCard title="GitHub 热度变化" description="每日 star 数量最多的 Top 5 仓库" refNode={githubRef} />
        </div>
      )}
    </section>
  )
}

function ChartCard({
  title,
  description,
  refNode,
}: {
  title: string
  description: string
  refNode: RefObject<HTMLDivElement | null>
}) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-lg font-semibold text-slate-900">{title}</h2>
      <p className="mt-1 text-xs text-slate-500">{description}</p>
      <div ref={refNode} className="mt-4 h-80 w-full" />
    </div>
  )
}

function buildNewsOption(data: TrendPayload | null): any {
  const dates = data?.dates ?? []
  const terms = data?.news ?? []
  const words = topWords(terms)
  return {
    tooltip: { trigger: 'axis' },
    legend: { top: 0, data: words },
    grid: { left: 36, right: 16, top: 40, bottom: 28 },
    xAxis: { type: 'category', data: dates },
    yAxis: { type: 'value' },
    series: words.map((word) => ({
      name: word,
      type: 'line',
      smooth: true,
      symbolSize: 6,
      data: dates.map((date) => terms.find((term) => term.report_date === date && term.word === word)?.count ?? null),
    })),
  }
}

function buildGithubOption(data: TrendPayload | null): any {
  const dates = data?.dates ?? []
  const repos = data?.github ?? []
  const names = topRepos(repos)
  return {
    tooltip: { trigger: 'axis' },
    legend: { top: 0, data: names },
    grid: { left: 36, right: 16, top: 40, bottom: 28 },
    xAxis: { type: 'category', data: dates },
    yAxis: { type: 'value' },
    series: names.map((repo) => ({
      name: repo,
      type: 'line',
      smooth: true,
      symbolSize: 6,
      data: dates.map((date) => repos.find((item) => item.report_date === date && item.repo === repo)?.stars ?? null),
    })),
  }
}

function topWords(terms: NewsTerm[]): string[] {
  const totals = new Map<string, number>()
  terms.forEach((term) => totals.set(term.word, (totals.get(term.word) ?? 0) + term.count))
  return [...totals.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 5).map(([word]) => word)
}

function topRepos(repos: GitHubRepo[]): string[] {
  const totals = new Map<string, number>()
  repos.forEach((item) => totals.set(item.repo, (totals.get(item.repo) ?? 0) + item.stars))
  return [...totals.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 5).map(([repo]) => repo)
}
