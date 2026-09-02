import type { ReactNode } from 'react'
import { BrandMark } from './BrandMark'

type View = 'dashboard' | 'weather' | 'news' | 'github' | 'ai' | 'favorites' | 'trends'

const NAV_ITEMS: Array<{ id: View; label: string }> = [
  { id: 'dashboard', label: '日报仪表盘' },
  { id: 'weather', label: '天气' },
  { id: 'news', label: '新闻' },
  { id: 'github', label: 'GitHub 热门' },
  { id: 'ai', label: 'AI 要事' },
  { id: 'favorites', label: '收藏' },
  { id: 'trends', label: '趋势' },
]

interface AppShellProps {
  active: View
  children: ReactNode
  onNavigate: (view: View) => void
  onOpenChat: () => void
  llmConfigured: boolean
}

export function AppShell({
  active,
  children,
  onNavigate,
  onOpenChat,
  llmConfigured,
}: AppShellProps) {
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-slate-200/80 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-8">
          <BrandMark />
          <div className="flex items-center gap-3">
            <span className={`hidden rounded-full px-2.5 py-1 text-xs font-medium sm:inline-flex ${llmConfigured ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
              {llmConfigured ? 'LLM 已连接' : 'LLM 未配置'}
            </span>
            <button
              type="button"
              onClick={onOpenChat}
              className="rounded-xl bg-emerald-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-emerald-500"
            >
              问我
            </button>
          </div>
        </div>
        <nav className="mx-auto max-w-7xl overflow-x-auto px-4 sm:px-8">
          <div className="flex min-w-max gap-1 pb-2">
            {NAV_ITEMS.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => onNavigate(item.id)}
                className={`rounded-lg px-3 py-2 text-sm transition ${
                  active === item.id
                    ? 'bg-slate-900 text-white'
                    : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
        </nav>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-8 sm:py-10">
        {children}
      </main>
    </div>
  )
}