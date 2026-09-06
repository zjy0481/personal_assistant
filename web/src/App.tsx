import { useEffect, useState } from 'react'
import { addFavorite, deleteFavorite, getFavorites, getLatestReport, getRunStatus, getStatus, getTrends, getWeatherAlerts } from './api'
import { AppShell } from './components/AppShell'
import { ChatPanel } from './components/ChatPanel'
import { EmptyState } from './components/EmptyState'
import { FavoritesPanel } from './components/FavoritesPanel'
import { ReportDashboard } from './components/ReportDashboard'
import { TrendsPanel } from './components/TrendsPanel'
import type { ContentItem, Favorite, Report, RunStatus, TrendPayload, WeatherAlert, WeatherAlertEvent, WeatherAlertRun } from './types'

type View = 'dashboard' | 'weather' | 'news' | 'github' | 'ai' | 'favorites' | 'trends'

interface StatusInfo {
  llm_configured: boolean
  llm_summary_enabled: boolean
  llm_model: string
  web_search_enabled: boolean
}

function App() {
  const [view, setView] = useState<View>('dashboard')
  const [report, setReport] = useState<Report | null>(null)
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null)
  const [weatherAlerts, setWeatherAlerts] = useState<WeatherAlert[]>([])
  const [weatherEvents, setWeatherEvents] = useState<WeatherAlertEvent[]>([])
  const [weatherRun, setWeatherRun] = useState<WeatherAlertRun | null>(null)
  const [status, setStatus] = useState<StatusInfo | null>(null)
  const [favorites, setFavorites] = useState<Favorite[]>([])
  const [trends, setTrends] = useState<TrendPayload | null>(null)
  const [trendDays, setTrendDays] = useState(7)
  const [trendLoading, setTrendLoading] = useState(false)
  const [trendError, setTrendError] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [chatOpen, setChatOpen] = useState(false)
  const [askItem, setAskItem] = useState<ContentItem | null>(null)

  async function refresh() {
    try {
      const [nextReport, nextStatus, nextRunStatus, nextWeather, nextFavorites] = await Promise.all([
        getLatestReport(),
        getStatus(),
        getRunStatus(),
        getWeatherAlerts(),
        getFavorites(),
      ])
      setReport(nextReport)
      setStatus(nextStatus)
      setRunStatus(nextRunStatus)
      setWeatherAlerts(nextWeather.alerts)
      setWeatherEvents(nextWeather.events)
      setWeatherRun(nextWeather.run)
      setFavorites(nextFavorites)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }

  async function loadTrends(days: number) {
    setTrendLoading(true)
    setTrendError('')
    try {
      setTrends(await getTrends(days))
    } catch (err) {
      setTrendError(err instanceof Error ? err.message : '趋势加载失败')
    } finally {
      setTrendLoading(false)
    }
  }

  // oxlint-disable-next-line react/set-state-in-effect
  useEffect(() => {
    // eslint-disable-next-line react/set-state-in-effect
    void refresh()
  }, [])

  function navigate(next: View) {
    setView(next)
    if (next === 'trends') {
      void loadTrends(trendDays)
    }
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  function openQuestion(item: ContentItem) {
    setAskItem(item)
    setChatOpen(true)
  }

  async function toggleFavorite(item: ContentItem | Favorite, blockKind: string) {
    const existing = favorites.find((favorite) => favorite.item_id === item.item_id)
    try {
      if (existing) {
        await deleteFavorite(item.item_id)
        setFavorites((current) => current.filter((favorite) => favorite.item_id !== item.item_id))
      } else {
        const created = await addFavorite({
          item_id: item.item_id,
          report_date: report?.generated_at.slice(0, 10) ?? '',
          block_kind: blockKind,
          title: item.title,
          url: item.url,
          source: item.source,
        })
        setFavorites((current) => current.some((favorite) => favorite.item_id === created.item_id)
          ? current
          : [...current, created])
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '收藏操作失败')
    }
  }

  return (
    <AppShell
      active={view}
      onNavigate={navigate}
      onOpenChat={() => {
        setAskItem(null)
        setChatOpen(true)
      }}
      llmConfigured={status?.llm_configured ?? false}
    >
      {loading ? (
        <LoadingState />
      ) : error ? (
        <EmptyState title="无法连接后端" description={error} />
      ) : view === 'favorites' ? (
        <FavoritesPanel favorites={favorites} onRemove={(item) => toggleFavorite(item, item.block_kind)} />
      ) : view === 'trends' ? (
        <TrendsPanel
          data={trends}
          loading={trendLoading}
          error={trendError}
          days={trendDays}
          onDaysChange={(days) => {
            setTrendDays(days)
            void loadTrends(days)
          }}
        />
      ) : report ? (
        <ReportDashboard
          report={report}
          view={view}
          runStatus={runStatus}
          weatherAlerts={weatherAlerts}
          weatherEvents={weatherEvents}
          weatherRun={weatherRun}
          favorites={favorites}
          trends={trends}
          trendLoading={trendLoading}
          trendError={trendError}
          trendDays={trendDays}
          onTrendDaysChange={(days) => {
            setTrendDays(days)
            void loadTrends(days)
          }}
          onToggleFavorite={toggleFavorite}
          onAsk={openQuestion}
        />
      ) : (
        <EmptyState
          title="暂无日报快照"
          description="请先运行 `uv run python -m assistant daily` 生成日报，或使用现有快照重新生成。"
        />
      )}

      <ChatPanel
        report={report}
        open={chatOpen}
        onClose={() => setChatOpen(false)}
        askItem={askItem}
        onAskConsumed={() => setAskItem(null)}
        webSearchEnabled={status?.web_search_enabled ?? true}
      />
    </AppShell>
  )
}

function LoadingState() {
  return (
    <div className="flex min-h-[50vh] items-center justify-center">
      <div className="flex items-center gap-3 text-sm text-slate-500">
        <span className="h-3 w-3 animate-spin rounded-full border-2 border-slate-300 border-t-emerald-600" />
        正在加载日报…
      </div>
    </div>
  )
}

export default App
