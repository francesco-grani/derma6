import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { getAccessToken } from '@/lib/api'
import type { InterruptPayload } from '@/components/chat/InterruptCard'

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
  working?: boolean
}

export interface PendingInterrupt {
  payload: InterruptPayload
  run_id: string
}

export function useStreamChat(sessionId: string | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [streaming, setStreaming] = useState(false)
  const [pendingInterrupt, setPendingInterrupt] = useState<PendingInterrupt | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const streamingRef = useRef(false)
  const qc = useQueryClient()

  // Abort any in-flight stream and reset streaming state whenever the session
  // changes, so a still-running response from the *previous* session can't
  // block (or get mistaken for) the newly-selected session's history load.
  useEffect(() => {
    return () => {
      abortRef.current?.abort()
      streamingRef.current = false
      setStreaming(false)
    }
  }, [sessionId])

  // Load history whenever sessionId changes
  useEffect(() => {
    setPendingInterrupt(null)
    if (!sessionId) { setMessages([]); return }
    let cancelled = false
    getAccessToken().then(token => {
      if (!token || cancelled) return
      return fetch(`/api/me/chat/history?session_id=${encodeURIComponent(sessionId)}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
        .then(r => r.ok ? r.json() : [])
        .then((history: ChatMessage[]) => {
          // Don't overwrite messages if a send already started (e.g. initial-message from sessionStorage)
          if (!cancelled && !streamingRef.current) setMessages(history)
        })
    }).catch(() => {})
    return () => {
      cancelled = true
    }
  }, [sessionId])

  const sendMessage = useCallback(async (text: string) => {
    if (streamingRef.current || !sessionId) return
    streamingRef.current = true

    const userMsg: ChatMessage = { role: 'user', content: text }
    setMessages(prev => [...prev, userMsg])
    setStreaming(true)
    setMessages(prev => [...prev, { role: 'assistant', content: '' }])

    const ctrl = new AbortController()
    abortRef.current = ctrl

    try {
      const token = await getAccessToken()
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
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
              updateLast(msg => ({ ...msg, content: msg.content + event.content, working: false }))
            } else if (event.type === 'tool_start') {
              updateLast(msg => ({ ...msg, working: true }))
            } else if (event.type === 'clear_text') {
              updateLast(msg => ({ ...msg, content: '', working: false }))
            } else if (event.type === 'metadata') {
              updateLast(msg => ({
                ...msg,
                citations: event.citations ?? [],
                rag_context: event.rag_context ?? [],
                tool_results: event.tool_results ?? [],
                working: false,
              }))
            } else if (event.type === 'session_title') {
              qc.invalidateQueries({ queryKey: ['sessions'] })
            } else if (event.type === 'interrupt') {
              // Drop the empty assistant placeholder; InterruptCard takes its place.
              // Control has passed to the user now, so clear any lingering "working"
              // indicator on the message that triggered this (e.g. save_routine_tool).
              setMessages(prev => {
                const last = prev[prev.length - 1]
                if (last?.role !== 'assistant') return prev
                if (last.content === '') return prev.slice(0, -1)
                const copy = [...prev]
                copy[copy.length - 1] = { ...last, working: false }
                return copy
              })
              setPendingInterrupt({ payload: event as InterruptPayload, run_id: event.run_id as string })
            } else if (event.type === 'error') {
              updateLast(msg => ({ ...msg, content: msg.content || `⚠️ ${event.content}`, working: false }))
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
      streamingRef.current = false
      setStreaming(false)
      abortRef.current = null
    }
  }, [sessionId, qc])

  const clearMessages = useCallback(() => setMessages([]), [])

  const resolveInterrupt = useCallback(async (choice: string, note: string, run_id: string) => {
    if (!sessionId) return
    streamingRef.current = true

    const option = pendingInterrupt?.payload.options.find(o => o.value === choice)
    const displayContent = note.trim() || option?.label || choice
    const userMsg: ChatMessage = { role: 'user', content: displayContent }

    setPendingInterrupt(null)
    setStreaming(true)
    setMessages(prev => [...prev, userMsg, { role: 'assistant', content: '' }])

    try {
      const token = await getAccessToken()
      const res = await fetch('/api/chat/resume', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ session_id: sessionId, run_id, choice, note }),
      })

      if (!res.ok || !res.body) throw new Error(`Resume failed: ${res.status}`)

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
              updateLast(msg => ({ ...msg, content: msg.content + event.content, working: false }))
            } else if (event.type === 'tool_start') {
              updateLast(msg => ({ ...msg, working: true }))
            } else if (event.type === 'clear_text') {
              updateLast(msg => ({ ...msg, content: '', working: false }))
            } else if (event.type === 'metadata') {
              updateLast(msg => ({
                ...msg,
                citations: event.citations ?? [],
                rag_context: event.rag_context ?? [],
                tool_results: event.tool_results ?? [],
                working: false,
              }))
              qc.invalidateQueries({ queryKey: ['routines'] })
            } else if (event.type === 'interrupt') {
              // Backend hit another interrupt right away (e.g. a second parallel
              // tool call awaiting its own confirmation) — chain into a new card
              // instead of silently dropping the event and leaving the UI stuck.
              // Also clear any lingering "working" indicator now that control has
              // passed back to the user.
              setMessages(prev => {
                const last = prev[prev.length - 1]
                if (last?.role !== 'assistant') return prev
                if (last.content === '') return prev.slice(0, -1)
                const copy = [...prev]
                copy[copy.length - 1] = { ...last, working: false }
                return copy
              })
              setPendingInterrupt({ payload: event as InterruptPayload, run_id: event.run_id as string })
            } else if (event.type === 'error') {
              updateLast(msg => ({ ...msg, content: msg.content || `⚠️ ${event.content}`, working: false }))
            }
          } catch { /* ignore malformed SSE */ }
        }
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        setMessages(prev => {
          const copy = [...prev]
          copy[copy.length - 1] = { ...copy[copy.length - 1], content: '⚠️ Resume failed. Please try again.' }
          return copy
        })
      }
    } finally {
      streamingRef.current = false
      setStreaming(false)
    }
  }, [sessionId, qc, pendingInterrupt])

  return { messages, streaming, pendingInterrupt, sendMessage, resolveInterrupt, clearMessages }
}
