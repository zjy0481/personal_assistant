export type BlockKind = 'weather' | 'news' | 'github' | 'ai'

export interface ContentItem {
  title: string
  url: string
  source: string
  published_at?: string | null
  summary: string
  language?: string
  category?: string
  stars?: number | null
  metadata?: Record<string, unknown>
  item_id: string
  llm_summary?: string
  summary_status?: string
  summary_model?: string
}

export interface ContentBlock {
  kind: BlockKind
  title: string
  status: string
  items: ContentItem[]
  details?: Record<string, unknown>
  sources?: string[]
  message?: string | null
}

export interface Report {
  title: string
  generated_at: string
  location: string
  timezone: string
  blocks: ContentBlock[]
  degraded: boolean
}

export interface RunStatus {
  report_date: string
  status: string
  channel?: string
  short_code?: string
  message?: string
  created_at?: string
}

export interface ChatResponse {
  answer: string
  session_id: string
  citations: Array<{ title: string; url: string }>
}

export interface ChatHistoryItem {
  role: 'user' | 'assistant'
  content: string
}