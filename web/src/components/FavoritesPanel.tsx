import type { Favorite } from '../types'
import { EmptyState } from './EmptyState'

const KIND_LABELS: Record<string, string> = {
  news: '时事新闻',
  ai: 'AI 要事',
  github: 'GitHub 项目',
}

interface FavoritesPanelProps {
  favorites: Favorite[]
  onRemove: (item: Favorite) => void
}

export function FavoritesPanel({ favorites, onRemove }: FavoritesPanelProps) {
  return (
    <section>
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900 sm:text-3xl">我的收藏</h1>
        <p className="mt-2 text-sm text-slate-500">共 {favorites.length} 条收藏，刷新和服务重启后仍会保留。</p>
      </header>

      {favorites.length === 0 ? (
        <EmptyState
          title="暂无收藏"
          description="在新闻、AI 要事或 GitHub 项目卡片上点击收藏按钮即可保存。"
        />
      ) : (
        <div className="space-y-4">
          {favorites.map((item) => (
            <article key={item.item_id} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-base font-semibold text-slate-900">
                      {item.url ? (
                        <a href={item.url} target="_blank" rel="noreferrer" className="hover:text-emerald-700">
                          {item.title}
                        </a>
                      ) : (
                        item.title
                      )}
                    </h2>
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">
                      {KIND_LABELS[item.block_kind] ?? item.block_kind}
                    </span>
                  </div>
                  <p className="mt-2 text-sm text-slate-600">{item.source || '未知来源'}</p>
                  {item.note && <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">备注：{item.note}</p>}
                  <p className="mt-2 text-xs text-slate-400">收藏时间：{formatDate(item.created_at)}</p>
                </div>
                <button
                  type="button"
                  onClick={() => onRemove(item)}
                  className="shrink-0 rounded-lg border border-rose-200 bg-white px-3 py-1.5 text-xs font-medium text-rose-600 shadow-sm transition hover:bg-rose-50"
                >
                  取消收藏
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  )
}

function formatDate(value?: string) {
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
