const STATUS_STYLES: Record<string, string> = {
  ok: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  degraded: 'bg-amber-50 text-amber-700 border-amber-200',
  failed: 'bg-rose-50 text-rose-700 border-rose-200',
  skipped: 'bg-slate-100 text-slate-600 border-slate-200',
  not_configured: 'bg-slate-100 text-slate-500 border-slate-200',
  not_generated: 'bg-slate-100 text-slate-500 border-slate-200',
}

const STATUS_LABELS: Record<string, string> = {
  ok: '正常',
  degraded: '降级',
  failed: '失败',
  skipped: '已跳过',
  not_configured: '未配置',
  not_generated: '未生成',
}

export function StatusPill({ status }: { status?: string }) {
  if (!status) return null
  const normalized = status.toLowerCase()
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${
        STATUS_STYLES[normalized] ?? 'bg-slate-100 text-slate-600 border-slate-200'
      }`}
    >
      {STATUS_LABELS[normalized] ?? status}
    </span>
  )
}