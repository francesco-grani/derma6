import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { getToken } from '@/lib/api'

export interface RagItem {
  source: string
  score: number
  snippet: string
}

export interface ToolResultItem {
  tool_name: string
  summary: string
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  citations?: string[]
  rag_context?: RagItem[]
  tool_results?: ToolResultItem[]
}

export function useStreamChat(sessionId: string | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [streaming, setStreaming] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const qc = useQueryClient()

  // Load history whenever sessionId changes
  useEffect(() => {
    if (!sessionId) { setMessages([]); return }
    const token = getToken()
    if (!token) return
    fetch(`/api/me/chat/history?session_id=${encodeURIComponent(sessionId)}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.ok ? r.json() : [])
      .then((history: ChatMessage[]) => setMessages(history))
      .catch(() => {})
  }, [sessionId])

  const sendMessage = useCallback(async (text: string) => {
    if (streaming || !sessionId) return

    const userMsg: ChatMessage = { role: 'user', content: text }
    setMessages(prev => [...prev, userMsg])
    setStreaming(true)
    setMessages(prev => [...prev, { role: 'assistant', content: '' }])

    const ctrl = new AbortController()
    abortRef.current = ctrl

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${getToken()}`,
        },
        body: JSON.stringify({ message: text, session_id: sessionId }),
        signal: ctrl.signal,
      })

      if (!res.ok || !res.body) {
        throw new Error(`Chat request failed: ${res.status}`)
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      const updateLast = (updater: (msg: ChatMessage) => ChatMessage) => {
        setMessages(prev => {
          const copy = [...prev]
          copy[copy.length - 1] = updater(copy[copy.length - 1])
          return copy
        })
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() ?? ''

        for (const part of parts) {
          if (!part.startsWith('data: ')) continue
          const raw = part.slice(6)
          if (raw === '[DONE]') break

          try {
            const event = JSON.parse(raw)
            if (event.type === 'text') {
              updateLast(msg => ({ ...msg, content: msg.content + event.content }))
            } else if (event.type === 'metadata') {
              updateLast(msg => ({
                ...msg,
                citations: event.citations ?? [],
                rag_context: event.rag_context ?? [],
                tool_results: event.tool_results ?? [],
              }))
            } else if (event.type === 'session_title') {
              // Title just became available — refresh the sidebar session list
              qc.invalidateQueries({ queryKey: ['sessions'] })
            } else if (event.type === 'error') {
              updateLast(msg => ({ ...msg, content: msg.content || `⚠️ ${event.content}` }))
            }
          } catch {
            // ignore malformed SSE lines
          }
        }
      }

      // Session list is refreshed via the 'session_title' SSE event (first message only)
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        setMessages(prev => {
          const copy = [...prev]
          copy[copy.length - 1] = {
            ...copy[copy.length - 1],
            content: '⚠️ Connection error. Please try again.',
          }
          return copy
        })
      }
    } finally {
      setStreaming(false)
      abortRef.current = null
    }
  }, [streaming, sessionId, qc])

  const clearMessages = useCallback(() => setMessages([]), [])

  return { messages, streaming, sendMessage, clearMessages }
}
