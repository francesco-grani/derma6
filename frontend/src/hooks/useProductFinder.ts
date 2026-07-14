import { useEffect, useState } from 'react'
import { buildProductFindStreamRequest, type ProductFindResponse, type ProductFindSource } from '@/lib/api'

/**
 * State shape returned by `useProductFind` (product-finder-streaming Req 9,
 * 10). `stagePhrase` is the most recently received stage phrase (Req 7.5,
 * 10.1) — `null` before the first stage event arrives, and cleared back to
 * `null` once the terminal (`result`) event lands (Req 10.3).
 */
export interface ProductFindStreamState {
  isPending: boolean
  isError: boolean
  isSuccess: boolean
  data: ProductFindResponse | undefined
  stagePhrase: string | null
}

const IDLE_STATE: ProductFindStreamState = {
  isPending: false,
  isError: false,
  isSuccess: false,
  data: undefined,
  stagePhrase: null,
}

const PENDING_STATE: ProductFindStreamState = {
  isPending: true,
  isError: false,
  isSuccess: false,
  data: undefined,
  stagePhrase: null,
}

/**
 * Consumes the streamed (`stream=true`) `GET /api/products/find` response
 * for a single per-source request (Req 9), following `useStreamChat.ts`'s
 * established `fetch()` + `response.body.getReader()` + `TextDecoder`
 * pattern rather than the native `EventSource` API (Req 9.1-9.3 —
 * `EventSource` cannot carry the custom `Authorization` header this
 * endpoint requires).
 *
 * A self-contained `useEffect`-driven hook rather than a `useQuery` wrapper
 * (Focus Area 6 of design.md): TanStack Query's caching had already been
 * fully disabled for this hook (`staleTime: 0`/`refetchOnMount: 'always'`)
 * before this feature, and it has no built-in concept of intermediate
 * progress updates before a final value — once the caching behavior it
 * provides is already turned off, keeping it as the transport layer adds
 * machinery without adding value.
 *
 * The exported function's name and call signature are unchanged
 * (`useProductFind(name, brand, enabled, source)`), so
 * `ProductFinderPopover.tsx`'s three call sites need no changes beyond
 * consuming the new `stagePhrase` field.
 */
export function useProductFind(
  name: string | null,
  brand: string | null,
  enabled: boolean,
  source?: ProductFindSource
): ProductFindStreamState {
  // Req 7.3: reset to idle/pending synchronously during render whenever the
  // request key changes, rather than via a `setState` call inside the
  // effect body below — following `useStreamChat.ts`'s existing "adjusting
  // state when a prop changes" pattern
  // (https://react.dev/learn/you-might-not-need-an-effect). This leaves the
  // effect itself to do only what an effect should: synchronize with the
  // external fetch/stream, updating state from asynchronous callbacks as
  // the stream progresses (inside the `async` IIFE below, after its first
  // `await`), never synchronously at the top of the effect body. The lazy
  // initializer below (rather than always starting from `IDLE_STATE`) makes
  // this correct on the very first render too, when `enabled`/`name` may
  // already be truthy on mount.
  const requestKey = `${String(enabled)}|${name ?? ''}|${brand ?? ''}|${source ?? ''}`
  const [state, setState] = useState<ProductFindStreamState>(() =>
    enabled && name ? PENDING_STATE : IDLE_STATE
  )
  const [prevRequestKey, setPrevRequestKey] = useState(requestKey)
  if (requestKey !== prevRequestKey) {
    setPrevRequestKey(requestKey)
    setState(enabled && name ? PENDING_STATE : IDLE_STATE)
  }

  useEffect(() => {
    if (!enabled || !name) {
      return
    }

    let cancelled = false
    const ctrl = new AbortController()

    ;(async () => {
      try {
        const { url, init } = await buildProductFindStreamRequest(name, brand, source)
        if (cancelled) return
        const res = await fetch(url, { ...init, signal: ctrl.signal })
        if (!res.ok || !res.body) {
          throw new Error(`Product find stream failed: ${res.status}`)
        }

        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let gotResult = false

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
              if (event.type === 'stage' && !cancelled) {
                // Req 9.4: update without waiting for the stream to finish.
                setState((s) => ({ ...s, stagePhrase: event.message }))
              } else if (event.type === 'result' && !cancelled) {
                gotResult = true
                setState({
                  isPending: false,
                  isError: false,
                  isSuccess: true,
                  data: event.result,
                  stagePhrase: null,
                })
              }
            } catch {
              // Ignore malformed SSE line, same tolerance as useStreamChat.ts.
            }
          }
        }

        // Req 11.2: stream ended with no terminal "result" event -> treat as
        // "unavailable", the same outcome as any other request-level failure.
        if (!gotResult && !cancelled) {
          setState({ isPending: false, isError: true, isSuccess: false, data: undefined, stagePhrase: null })
        }
      } catch (err) {
        if ((err as Error).name !== 'AbortError' && !cancelled) {
          setState({ isPending: false, isError: true, isSuccess: false, data: undefined, stagePhrase: null })
        }
      }
    })()

    return () => {
      cancelled = true
      ctrl.abort()
    }
  }, [name, brand, enabled, source])

  return state
}
