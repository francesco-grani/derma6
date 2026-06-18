import { useRef, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { useStreamChat, type ChatMessage } from '@/hooks/useStreamChat'
import { useAuth } from '@/lib/auth'
import { useQueryClient } from '@tanstack/react-query'

const SUGGESTIONS = [
  'Analyze my ingredients',
  'Build me a routine',
  'What is skin cycling?',
]

export default function ChatPage() {
  const { username } = useAuth()
  const { messages, streaming, sendMessage } = useStreamChat()
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const qc = useQueryClient()

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Re-focus input when streaming finishes
  useEffect(() => {
    if (!streaming) {
      inputRef.current?.focus()
    }
  }, [streaming])

  // Invalidate profile/routines after each assistant reply (tools may have updated them)
  useEffect(() => {
    if (!streaming && messages.length > 0 && messages[messages.length - 1].role === 'assistant') {
      qc.invalidateQueries({ queryKey: ['profile'] })
      qc.invalidateQueries({ queryKey: ['routines'] })
    }
  }, [streaming])

  function submit(text: string) {
    if (!text.trim() || streaming) return
    setInput('')
    sendMessage(text.trim())
  }

  return (
    <div className="flex flex-col h-screen" style={{ background: '#3E4D3F' }}>
      {/* Messages — constrained width, centred */}
      <div className="flex-1 overflow-y-auto py-6 flex flex-col gap-4">
        <div className="w-full max-w-2xl mx-auto px-4 flex flex-col gap-4 flex-1">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center flex-1 gap-6">
              <p style={{ color: '#9EAD9E', fontSize: 18 }}>How can I help you today?</p>
              <div className="flex gap-2 flex-wrap justify-center">
                {SUGGESTIONS.map(s => (
                  <button
                    key={s}
                    onClick={() => submit(s)}
                    className="px-4 py-2 rounded-full text-sm border transition-colors hover:opacity-80 cursor-pointer"
                    style={{ borderColor: '#4B5A4C', color: '#E0E8E0', background: '#2E3D2F' }}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <MessageBubble key={i} msg={msg} username={username ?? ''} />
          ))}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* Input — same constrained width */}
      <div className="pb-6 pt-2" style={{ background: '#3E4D3F' }}>
        <form
          className="flex gap-2 w-full max-w-2xl mx-auto px-4"
          onSubmit={e => { e.preventDefault(); submit(input) }}
        >
          <input
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Ask about ingredients, routines, or your skin type…"
            autoFocus
            className="flex-1 px-4 py-3 rounded-xl text-sm outline-none"
            style={{
              background: '#2E3D2F',
              border: '1px solid #4B5A4C',
              color: '#E0E8E0',
            }}
          />
          <Button
            type="submit"
            disabled={!input.trim()}
            style={{ background: '#7A9B7D', color: '#1C2520', fontWeight: 600, cursor: 'pointer' }}
            className="px-5"
          >
            {streaming ? '…' : '→'}
          </Button>
        </form>
      </div>
    </div>
  )
}

function MessageBubble({ msg, username }: { msg: ChatMessage; username: string }) {
  const [showRag, setShowRag] = useState(false)
  const [showTools, setShowTools] = useState(false)
  const isUser = msg.role === 'user'

  return (
    <div className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} gap-1 max-w-2xl ${isUser ? 'self-end' : 'self-start'}`}>
      <span className="text-xs px-1" style={{ color: '#9EAD9E' }}>
        {isUser ? username : 'Derma6'}
      </span>
      <div
        className="px-4 py-3 rounded-2xl text-sm whitespace-pre-wrap leading-relaxed"
        style={isUser
          ? { background: '#7A9B7D', color: '#1C2520', borderBottomRightRadius: 4 }
          : { background: '#fff', color: '#1C2520', borderBottomLeftRadius: 4, boxShadow: '0 1px 4px rgba(0,0,0,.12)' }
        }
      >
        {msg.content || <span style={{ opacity: 0.4 }}>●●●</span>}
      </div>

      {/* Citations */}
      {!isUser && msg.citations && msg.citations.length > 0 && (
        <div className="text-xs px-1" style={{ color: '#9EAD9E' }}>
          📚 {msg.citations.join(' · ')}
        </div>
      )}

      {/* RAG toggle */}
      {!isUser && msg.rag_context && msg.rag_context.length > 0 && (
        <div className="w-full">
          <button
            onClick={() => setShowRag(v => !v)}
            className="text-xs px-2 py-1 rounded"
            style={{ color: '#9EAD9E', background: 'none', border: 'none', cursor: 'pointer' }}
          >
            🔍 RAG Retrieval {showRag ? '▲' : '▼'}
          </button>
          {showRag && (
            <div className="flex flex-col gap-2 mt-1 p-2 rounded-lg" style={{ background: '#2E3D2F' }}>
              {msg.rag_context.map((r, i) => (
                <div key={i}>
                  <div className="flex justify-between text-xs" style={{ color: '#E0E8E0' }}>
                    <span>{r.source}</span>
                    <span style={{ color: '#C4933F' }}>{Math.round(r.score * 100)}%</span>
                  </div>
                  <p className="text-xs mt-1" style={{ color: '#9EAD9E' }}>
                    {r.snippet?.slice(0, 150)}…
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Tool results toggle */}
      {!isUser && msg.tool_results && msg.tool_results.length > 0 && (
        <div className="w-full">
          <button
            onClick={() => setShowTools(v => !v)}
            className="text-xs px-2 py-1 rounded"
            style={{ color: '#9EAD9E', background: 'none', border: 'none', cursor: 'pointer' }}
          >
            🔧 Tools ({msg.tool_results.length}) {showTools ? '▲' : '▼'}
          </button>
          {showTools && (
            <div className="flex flex-col gap-1 mt-1 p-2 rounded-lg" style={{ background: '#2E3D2F' }}>
              {msg.tool_results.map((t, i) => (
                <div key={i} className="text-xs" style={{ color: '#9EAD9E' }}>
                  <span style={{ color: '#C4933F' }}>{t.tool_name}</span>
                  {' — '}
                  {t.summary?.slice(0, 100)}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
