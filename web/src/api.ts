import type { ChatHistoryItem, ChatResponse, Favorite, FavoritePayload, Report, RunStatus, TrendPayload, WeatherAlert, WeatherAlertEvent, WeatherAlertRun } from './types'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''
const AUTH_TOKEN =
  localStorage.getItem('assistant_token') ?? import.meta.env.VITE_AUTH_TOKEN ?? ''

async function request<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (AUTH_TOKEN) {
    headers.set('Authorization', `Bearer ${AUTH_TOKEN}`)
  }
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    const message =
      typeof payload === 'object' && payload && 'detail' in payload
        ? String(payload.detail)
        : `请求失败 (${response.status})`
    throw new Error(message)
  }
  return payload as T
}

export async function getLatestReport(): Promise<Report | null> {
  const payload = await request<{ report: Report | null }>('/api/reports/latest')
  return payload.report
}

export async function getRunStatus(): Promise<RunStatus | null> {
  const payload = await request<{ run_status: RunStatus | null }>('/api/run-status')
  return payload.run_status
}
export async function getStatus(): Promise<{
  llm_configured: boolean
  llm_summary_enabled: boolean
  llm_model: string
  web_search_enabled: boolean
  web_search_model: string
  web_daily_limit: number
}> {
  return request('/api/status')
}

export async function askReport(
  message: string,
  sessionId: string,
  mode: string = 'auto',
): Promise<ChatResponse> {
  return request('/api/chat', {
    method: 'POST',
    body: JSON.stringify({ message, session_id: sessionId, mode }),
  })
}

export async function askReportStream(
  message: string,
  sessionId: string,
  mode: string = 'auto',
  onDelta?: (text: string) => void,
  onStage?: (stage: string) => void,
): Promise<ChatResponse> {
  const headers = new Headers({ Accept: 'text/event-stream' })
  headers.set('Content-Type', 'application/json')
  if (AUTH_TOKEN) {
    headers.set('Authorization', `Bearer ${AUTH_TOKEN}`)
  }
  const response = await fetch(`${API_BASE}/api/chat/stream`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ message, session_id: sessionId, mode }),
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    const detail =
      typeof payload === 'object' && payload && 'detail' in payload
        ? String(payload.detail)
        : `请求失败 (${response.status})`
    throw new Error(detail)
  }
  const body = response.body
  if (!body) {
    throw new Error('流式响应不可用')
  }
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let finalResult: ChatResponse | null = null
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let separator = buffer.indexOf('\n\n')
    while (separator >= 0) {
      const block = buffer.slice(0, separator)
      buffer = buffer.slice(separator + 2)
      const parsed = parseSse(block)
      if (parsed?.event === 'delta') {
        onDelta?.(String(parsed.data?.text ?? ''))
      }
      if (parsed?.event === 'status') {
        onStage?.(String(parsed.data?.stage ?? ''))
      }
      if (parsed?.event === 'result') {
        finalResult = parsed.data as unknown as ChatResponse
      }
      if (parsed?.event === 'error') {
        throw new Error(String(parsed.data?.message ?? '问答失败'))
      }
      separator = buffer.indexOf('\n\n')
    }
  }
  if (!finalResult) {
    throw new Error('未收到完整问答结果')
  }
  return finalResult
}

export async function getChatHistory(
  sessionId: string,
): Promise<ChatHistoryItem[]> {
  const payload = await request<{ history: ChatHistoryItem[] }>(
    `/api/chat/history?session_id=${encodeURIComponent(sessionId)}`,
  )
  return payload.history
}
export interface WeatherAlertPayload {
  alerts: WeatherAlert[]
  events: WeatherAlertEvent[]
  run: WeatherAlertRun | null
}

export async function getWeatherAlerts(): Promise<WeatherAlertPayload> {
  return request<WeatherAlertPayload>('/api/weather-alerts')
}

export async function getFavorites(): Promise<Favorite[]> {
  const payload = await request<{ favorites: Favorite[] }>('/api/favorites')
  return payload.favorites
}

export async function addFavorite(
  payload: FavoritePayload,
): Promise<Favorite> {
  const response = await request<{ favorite: Favorite }>('/api/favorites', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return response.favorite
}

export async function deleteFavorite(itemId: string): Promise<void> {
  await request<{ deleted: boolean }>(
    `/api/favorites/${encodeURIComponent(itemId)}`,
    { method: 'DELETE' },
  )
}

export async function getTrends(days: number = 7): Promise<TrendPayload> {
  return request<TrendPayload>(`/api/trends?days=${days}`)
}

function parseSse(block: string): {
  event: string
  data: Record<string, unknown>
} | null {
  let event = 'message'
  let dataText = ''
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataText += line.slice(5).trim()
    }
  }
  if (!dataText) return null
  try {
    return { event, data: JSON.parse(dataText) as Record<string, unknown> }
  } catch {
    return null
  }
}
