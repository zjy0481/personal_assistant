import { useEffect, useState } from 'react'
import { getLatestReport, getRunStatus, getStatus } from './api'
import { AppShell } from './components/AppShell'
import { ChatPanel } from './components/ChatPanel'
import { EmptyState } from './components/EmptyState'
import { ReportDashboard } from './components/ReportDashboard'
import type { ContentItem, Report, RunStatus } from './types'

type View = 'dashboard' | 'weather' | 'news' | 'github' | 'ai' | 'favorites' | 'trends'

interface StatusInfo {
  llm_configured: boolean
  llm_summary_enabled: boolean
  llm_model: string
}

function App() {
  const [view, setView] = useState<View>('dashboard')
  const [report, setReport] = useState<Report | null>(null)
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null)
  const [status, setStatus] = useState<StatusInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [chatOpen, setChatOpen] = useState(false)
  const [askItem, setAskItem] = useState<ContentItem | null>(null)

  async function refresh() {
    try {
      const [nextReport, nextStatus, nextRunStatus] = await Promise.all([
        getLatestReport(),
        getStatus(),
        getRunStatus(),
      ])
      setReport(nextReport)
      setStatus(nextStatus)
      setRunStatus(nextRunStatus)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }

  // oxlint-disable-next-line react/set-state-in-effect
  useEffect(() => {
    // eslint-disable-next-line react/set-state-in-effect
    void refresh()
  }, [])

  function openQuestion(item: ContentItem) {
    setAskItem(item)
    setChatOpen(true)
  }

  function navigate(next: View) {
    setView(next)
    window.scrollTo({ top: 0, behavior: 'smooth' })
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
      ) : report ? (
        <ReportDashboard
          report={report}
          view={view}
          runStatus={runStatus}
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