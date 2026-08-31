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
export interface WeatherAlert {
  alert_id: string
  location: string
  alert_type: string
  level: string
  title: string
  description: string
  safety_guidance: string
  status: 'active' | 'cancelled'
  event_type?: string
  published_at?: string | null
  started_at?: string | null
  ended_at?: string | null
  source: string
  source_url: string
  raw?: Record<string, unknown>
  push_status: string
  push_attempts: number
  pushed_at?: string | null
  first_seen_at?: string | null
  updated_at?: string | null
  last_event_id: number
}

export type WeatherAlertEventType =
  | 'initial'
  | 'upgraded'
  | 'downgraded'
  | 'cancelled'
  | 'updated'

export interface WeatherAlertEvent {
  event_id: number
  alert_id: string
  location: string
  alert_type: string
  level: string
  event_type: WeatherAlertEventType
  title: string
  description: string
  safety_guidance: string
  source: string
  source_url: string
  occurred_at?: string | null
  created_at?: string | null
  raw?: Record<string, unknown>
  push_status: string
  pushed_at?: string | null
  push_channel: string
}

export interface WeatherAlertRun {
  id: number
  checked_at: string
  status: string
  source: string
  alert_count: number
  fallback: boolean
  message: string
  created_at: string
}

export interface Favorite {
  item_id: string
  report_date: string
  block_kind: BlockKind | string
  title: string
  url: string
  source: string
  note: string
  status: 'active' | 'removed'
  created_at: string
  updated_at: string
  user_id?: string
}

export interface FavoritePayload {
  item_id: string
  report_date: string
  block_kind: string
  title: string
  url: string
  source: string
  note?: string
}

export interface NewsTerm {
  report_date: string
  word: string
  count: number
  rank: number
}

export interface GitHubRepo {
  report_date: string
  repo: string
  stars: number
  new_stars: number | null
  rank: number
  appearances: number
}

export interface TrendPayload {
  days: number
  dates: string[]
  news: NewsTerm[]
  github: GitHubRepo[]
  message?: string
}
