import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Button } from '@/components/ui/button'
import InterruptCard from '@/components/chat/InterruptCard'
import { useStreamChat, type ChatMessage } from '@/hooks/useStreamChat'
import { useAuth } from '@/lib/auth'
import { useSession } from '@/lib/sessionContext'
import { useQueryClient } from '@tanstack/react-query'

const SUGGESTIONS = [
  'Analyze my ingredients',
  'Build me a routine',
  'What is skin cycling?',
]

export default function ChatPage() {
  const { username } = useAuth()
  const { sessionId, resumeOrCreate } = useSession()
  const { messages, streaming, pendingInterrupt, sendMessage, resolveInterrupt } = useStreamChat(sessionId)
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const qc = useQueryClient()

  // On mount, ensure a session is active
  useEffect(() => {
    if (!sessionId) {
      resumeOrCreate()
    }
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    if (!streaming) inputRef.current?.focus()
  }, [streaming])

  useEffect(() => {
    if (!streaming && messages.length > 0 && messages[messages.length - 1].role === 'assistant') {
      qc.invalidateQueries({ queryKey: ['profile'] })
      qc.invalidateQueries({ queryKey: ['routines'] })
    }
  }, [streaming])

  useEffect(() => {
    if (!sessionId) return
    const pending = sessionStorage.getItem('derma6:initial-message')
    if (!pending) return
    sessionStorage.removeItem('derma6:initial-message')
    sendMessage(pending)
  }, [sessionId])

  function submit(text: string) {
    if (!text.trim() || streaming || pendingInterrupt) return
    setInput('')
    sendMessage(text.trim())
  }

  return (
    <div className="flex flex-col h-screen" style={{ background: '#3E4D3F' }}>
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

          {pendingInterrupt && (
            <div className="flex flex-col items-start gap-1 max-w-2xl self-start w-full">
              <span className="text-xs px-1" style={{ color: '#9EAD9E' }}>Derma6</span>
              <InterruptCard
                payload={pendingInterrupt.payload}
                onResolve={(choice, note) => resolveInterrupt(choice, note, pendingInterrupt.run_id)}
                disabled={streaming}
              />
            </div>
          )}

          <div ref={bottomRef} />
        </div>
      </div>

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
            disabled={!input.trim() || !sessionId || !!pendingInterrupt}
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
        className="px-4 py-3 rounded-2xl text-sm leading-relaxed"
        style={isUser
          ? { background: '#7A9B7D', color: '#1C2520', borderBottomRightRadius: 4, whiteSpace: 'pre-wrap' }
          : { background: '#fff', color: '#1C2520', borderBottomLeftRadius: 4, boxShadow: '0 1px 4px rgba(0,0,0,.12)' }
        }
      >
        {!msg.content
          ? (
            <span className="flex gap-1 items-center py-0.5">
              {[0, 150, 300].map(delay => (
                <span
                  key={delay}
                  className="inline-block w-2 h-2 rounded-full animate-bounce"
                  style={{ background: '#1C2520', opacity: 0.35, animationDelay: `${delay}ms` }}
                />
              ))}
            </span>
          )
          : isUser
            ? msg.content
            : (
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                  h1: ({ children }) => <h1 className="text-lg font-bold mb-2 mt-3 first:mt-0">{children}</h1>,
                  h2: ({ children }) => <h2 className="text-base font-bold mb-2 mt-3 first:mt-0">{children}</h2>,
                  h3: ({ children }) => <h3 className="text-sm font-bold mb-1 mt-2 first:mt-0">{children}</h3>,
                  ul: ({ children }) => <ul className="list-disc pl-5 mb-2 flex flex-col gap-0.5">{children}</ul>,
                  ol: ({ children }) => <ol className="list-decimal pl-5 mb-2 flex flex-col gap-0.5">{children}</ol>,
                  li: ({ children }) => <li>{children}</li>,
                  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                  em: ({ children }) => <em className="italic">{children}</em>,
                  code: ({ children, className }) => {
                    const isBlock = !!className
                    return isBlock
                      ? (
                        <code
                          className="block overflow-x-auto rounded-lg px-3 py-2 text-xs font-mono my-2"
                          style={{ background: '#1C2520', color: '#E0E8E0' }}
                        >
                          {children}
                        </code>
                      )
                      : (
                        <code
                          className="rounded px-1 py-0.5 text-xs font-mono"
                          style={{ background: '#E8EDE8', color: '#2E3D2F' }}
                        >
                          {children}
                        </code>
                      )
                  },
                  pre: ({ children }) => <pre className="my-2">{children}</pre>,
                  blockquote: ({ children }) => (
                    <blockquote
                      className="border-l-2 pl-3 my-2 italic"
                      style={{ borderColor: '#7A9B7D', color: '#4A5A4B' }}
                    >
                      {children}
                    </blockquote>
                  ),
                  hr: () => <hr className="my-3" style={{ borderColor: '#E0E0E0' }} />,
                  a: ({ href, children }) => (
                    <a href={href} target="_blank" rel="noopener noreferrer" style={{ color: '#3A6B3D', textDecoration: 'underline' }}>
                      {children}
                    </a>
                  ),
                  table: ({ children }) => (
                    <div className="overflow-x-auto my-2">
                      <table className="text-xs border-collapse w-full">{children}</table>
                    </div>
                  ),
                  th: ({ children }) => (
                    <th className="px-2 py-1 text-left font-semibold border" style={{ borderColor: '#D0D0D0', background: '#F5F5F5' }}>
                      {children}
                    </th>
                  ),
                  td: ({ children }) => (
                    <td className="px-2 py-1 border" style={{ borderColor: '#D0D0D0' }}>{children}</td>
                  ),
                }}
              >
                {msg.content}
              </ReactMarkdown>
            )
        }
      </div>


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
                  <p className="text-xs mt-1" style={{ color: '#9EAD9E' }}>{r.snippet?.slice(0, 150)}…</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

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
                  <span style={{ color: '#C4933F' }}>{t.tool_name}</span>{' — '}
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
