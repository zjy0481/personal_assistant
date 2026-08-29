import type { ContentItem } from '../types'
import { StatusPill } from './StatusPill'

interface ItemCardProps {
  item: ContentItem
  onAsk: (item: ContentItem) => void
}

export function ItemCard({ item, onAsk }: ItemCardProps) {
  const summary = item.llm_summary || item.summary || '暂无摘要'
  const canAsk = item.url || item.title

  return (
    <article className="border-b border-slate-100 py-5 first:pt-0 last:border-b-0 last:pb-0">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[15px] font-semibold leading-6 text-slate-900">
              {canAsk ? (
                <a
                  href={item.url}
                  target="_blank"
                  rel="noreferrer"
                  className="transition-colors hover:text-emerald-700"
                >
                  {item.title}
                </a>
              ) : (
                item.title
              )}
            </h3>
            <StatusPill status={item.summary_status} />
          </div>
          <p className="mt-2 text-sm leading-6 text-slate-600">{summary}</p>
        </div>
        <button
          type="button"
          onClick={() => onAsk(item)}
          className="shrink-0 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm transition hover:border-emerald-200 hover:text-emerald-700"
        >
          对此条提问
        </button>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-400">
        <span>{item.source || '未知来源'}</span>
        {item.category && <span>{item.category}</span>}
        {item.language && <span>{item.language}</span>}
        {item.stars != null && <span>⭐ {Number(item.stars).toLocaleString()}</span>}
        {item.published_at && (
          <span>{new Date(item.published_at).toLocaleDateString('zh-CN')}</span>
        )}
      </div>
    </article>
  )
}