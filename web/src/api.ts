import type { ChatHistoryItem, ChatResponse, Report, RunStatus, WeatherAlert, WeatherAlertEvent, WeatherAlertRun } from './types'

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
}> {
  return request('/api/status')
}

export async function askReport(
  message: string,
  sessionId: string,
): Promise<ChatResponse> {
  return request('/api/chat', {
    method: 'POST',
    body: JSON.stringify({ message, session_id: sessionId }),
  })
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