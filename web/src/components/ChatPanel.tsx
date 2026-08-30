import { useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { askReport, getChatHistory } from '../api'
import type { ChatHistoryItem, ContentItem, Report } from '../types'

interface ChatPanelProps {
  report: Report | null
  open: boolean
  onClose: () => void
  askItem: ContentItem | null
  onAskConsumed: () => void
}

interface Message {
  role: 'user' | 'assistant'
  content: string
}

const SESSION_KEY = 'assistant_session_id'

function createSessionId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  const bytes = new Uint8Array(16)
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    crypto.getRandomValues(bytes)
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256)
    }
  }
  return Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
}


export function ChatPanel({
  report,
  open,
  onClose,
  askItem,
  onAskConsumed,
}: ChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [sessionId] = useState(() => {
    const stored = localStorage.getItem(SESSION_KEY)
    if (stored) return stored
    const next = createSessionId()
    localStorage.setItem(SESSION_KEY, next)
    return next
  })
  const messageListRef = useRef<HTMLDivElement | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const pendingAssistantScroll = useRef(false)

  useEffect(() => {
    if (!open) return
    getChatHistory(sessionId)
      .then((history: ChatHistoryItem[]) => {
        setMessages(history)
        scrollListToBottom()
      })
      .catch(() => {
        setMessages([])
        scrollListToBottom()
      })
  }, [open, sessionId])

  useEffect(() => {
    if (!open || !askItem) return
    // eslint-disable-next-line react/set-state-in-effect
    setInput(`@${askItem.title} `)
    requestAnimationFrame(() => textareaRef.current?.focus())
  }, [askItem, open])

  useEffect(() => {
    if (!pendingAssistantScroll.current) return
    pendingAssistantScroll.current = false
    scrollToAssistantStart()
  }, [messages])

  const canSend = useMemo(
    () => Boolean(input.trim()) && Boolean(report) && !loading,
    [input, loading, report],
  )

  async function submit() {
    if (!canSend) return
    const question = input.trim()
    if (!question) return
    setLoading(true)
    setError('')
    const userMessage: Message = { role: 'user', content: question }
    setMessages((current) => [...current, userMessage])
    setInput('')
    onAskConsumed()
    scrollListToBottom()
    try {
      const response = await askReport(question, sessionId)
      const assistantMessage: Message = {
        role: 'assistant',
        content: response.answer,
      }
      pendingAssistantScroll.current = true
      setMessages((current) => [...current, assistantMessage])
    } catch (err) {
      setError(err instanceof Error ? err.message : '问答请求失败')
    } finally {
      setLoading(false)
    }
  }

  function scrollListToBottom() {
    const list = messageListRef.current
    if (!list) return
    requestAnimationFrame(() => {
      list.scrollTo({ top: list.scrollHeight, behavior: 'smooth' })
    })
  }

  function scrollToAssistantStart() {
    const list = messageListRef.current
    if (!list) return
    const assistants = Array.from(
      list.querySelectorAll<HTMLElement>('div.justify-start'),
    )
    const assistant = assistants[assistants.length - 1]
    if (!assistant) {
      scrollListToBottom()
      return
    }
    const listRect = list.getBoundingClientRect()
    const itemRect = assistant.getBoundingClientRect()
    const nextTop = list.scrollTop + itemRect.top - listRect.top
    list.scrollTo({ top: nextTop, behavior: 'smooth' })
  }

  if (!open) return null

  return (
    <section className="fixed inset-x-0 bottom-0 z-30 mx-auto max-w-6xl px-4 pb-4 sm:px-8">
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl shadow-slate-900/10">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
          <div>
            <h2 className="text-sm font-semibold text-slate-900">日报问答</h2>
            <p className="mt-0.5 text-xs text-slate-500">
              {report ? `基于 ${report.title}` : '等待日报数据'}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-2 py-1 text-sm text-slate-500 hover:bg-slate-100 hover:text-slate-800"
          >
            收起
          </button>
        </div>

        <div
          ref={messageListRef}
          className="max-h-[42vh] min-h-[180px] overflow-y-auto px-5 py-4"
        >
          {messages.length === 0 && (
            <p className="text-sm leading-6 text-slate-500">
              可以直接问“今天有什么值得关注”，也可以从条目旁点击“对此条提问”。
            </p>
          )}
          {messages.map((message, index) => (
            <div
              key={`${message.role}-${index}`}
              className={`mb-4 flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`max-w-[82%] rounded-2xl px-4 py-2.5 text-sm leading-6 ${
                  message.role === 'user'
                    ? 'bg-emerald-600 text-white'
                    : 'markdown-content bg-slate-100 text-slate-800'
                }`}
              >
                {message.role === 'assistant' ? (
                  <MarkdownContent text={message.content} />
                ) : (
                  message.content
                )}
              </div>
            </div>
          ))}
          {loading && (
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-500" />
              正在思考中…
            </div>
          )}
          {error && <p className="text-sm text-rose-600">{error}</p>}
        </div>

        <div className="border-t border-slate-100 p-4">
          <div className="flex items-end gap-3">
            <textarea
              ref={textareaRef}
              autoFocus
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey && canSend) {
                  event.preventDefault()
                  void submit()
                }
              }}
              rows={2}
              placeholder="对最新日报提问"
              className="min-h-[58px] flex-1 resize-none rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-800 outline-none transition focus:border-emerald-300 focus:bg-white focus:ring-2 focus:ring-emerald-100"
            />
            <button
              type="button"
              disabled={!canSend}
              onClick={() => void submit()}
              className="rounded-xl bg-slate-900 px-5 py-3 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              发送
            </button>
          </div>
        </div>
      </div>
    </section>
  )
}

function MarkdownContent({ text }: { text: string }) {
  return (
    <div className="markdown-content">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  )
}