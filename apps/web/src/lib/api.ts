/**
 * Client for the AgriN streaming API.
 *
 * Uses fetch + ReadableStream rather than EventSource because the chat
 * endpoint is a POST (it carries the message body and session identifiers)
 * and EventSource is GET-only. The trade-off is that we parse the SSE framing
 * ourselves, which is done here once.
 */

export type StreamEvent =
  | { type: 'session'; conversation_id: string; farmer_id: string; field_id: string | null }
  | { type: 'text'; delta: string }
  | { type: 'tool_start'; name: string; input: Record<string, unknown> }
  | { type: 'tool_result'; name: string; ok: boolean; abstain_reason?: string; error?: string }
  | { type: 'card'; card: string; [k: string]: unknown }
  | { type: 'done'; evidence: EvidenceEntry[]; cards: unknown[]; tool_calls: number; elapsed_ms: number }
  | { type: 'error'; message: string; kind?: string }

export interface EvidenceEntry {
  tool: string
  input: Record<string, unknown>
  evidence: Record<string, any>
}

export interface ChatRequest {
  message: string
  conversation_id?: string | null
  farmer_id?: string | null
  field_id?: string | null
  language?: string
  latitude?: number
  longitude?: number
}

/**
 * POST a message and yield parsed events as they arrive.
 *
 * The SSE frame parser holds a buffer across chunk boundaries: a network
 * chunk can split a JSON payload mid-token, and naively parsing per-chunk
 * drops characters in exactly the situation streaming exists to handle.
 */
export async function* streamChat(
  req: ChatRequest,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
    signal,
  })

  if (!response.ok || !response.body) {
    throw new Error(`Chat request failed: ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })

    // SSE frames are separated by a blank line.
    let boundary: number
    while ((boundary = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)

      const line = frame.split('\n').find((l) => l.startsWith('data: '))
      if (!line) continue
      const payload = line.slice(6)
      if (payload === '[DONE]') return

      try {
        yield JSON.parse(payload) as StreamEvent
      } catch {
        // A malformed frame should not kill the stream; skip it.
        continue
      }
    }
  }
}

export interface LanguageInfo {
  code: string
  name: string
  assistant_name: string
  suggestions: string[]
}

export async function fetchLanguages(): Promise<LanguageInfo[]> {
  const r = await fetch('/api/languages')
  const d = await r.json()
  return d.languages
}

export async function fetchHealth() {
  const r = await fetch('/api/health')
  return r.json()
}

export async function saveField(
  farmerId: string,
  latitude: number,
  longitude: number,
  name?: string,
): Promise<string> {
  const r = await fetch('/api/field', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ farmer_id: farmerId, latitude, longitude, name }),
  })
  const d = await r.json()
  return d.field_id
}

/** Persist session identity so a returning farmer keeps their field and history. */
export const session = {
  get farmerId() {
    return localStorage.getItem('agrin.farmer_id')
  },
  set farmerId(v: string | null) {
    if (v) localStorage.setItem('agrin.farmer_id', v)
  },
  get fieldId() {
    return localStorage.getItem('agrin.field_id')
  },
  set fieldId(v: string | null) {
    if (v) localStorage.setItem('agrin.field_id', v)
  },
  get language() {
    return localStorage.getItem('agrin.language') || ''
  },
  set language(v: string) {
    localStorage.setItem('agrin.language', v)
  },
}
