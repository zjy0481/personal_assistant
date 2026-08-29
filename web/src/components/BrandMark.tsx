export function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-3">
      <div
        aria-hidden="true"
        className={`flex shrink-0 items-center justify-center rounded-xl bg-slate-900 font-semibold tracking-tight text-white ${
          compact ? 'h-8 w-8 text-xs' : 'h-10 w-10 text-sm'
        }`}
      >
        PA
      </div>
      {!compact && (
        <div className="leading-tight">
          <div className="text-sm font-semibold text-slate-900">个人助手</div>
          <div className="text-xs text-slate-500">日报 · 摘要 · 问答</div>
        </div>
      )}
    </div>
  )
}