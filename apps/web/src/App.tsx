/**
 * AgriN — the whole interface.
 *
 * Opens as a blank page with one input, the way a conversation starts. There
 * is no dashboard, no navigation, no tour, no settings to configure before
 * the first question. Everything the platform can do is reachable by asking
 * for it in your own language, and results appear inline as they are
 * produced.
 *
 * The design constraints that shaped this file, in order:
 *   1. The user may not read. Voice in, voice out, pictograms, large targets.
 *   2. The connection may be poor. Streaming, so words appear immediately.
 *   3. The phone may be cheap. No heavy dependencies, no map until asked.
 *   4. The user is standing in a field in the sun. High contrast, big type.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { RenderCard, EvidenceLedger } from './components/Cards'
import { streamChat, fetchLanguages, fetchHealth, session,
         type LanguageInfo, type EvidenceEntry } from './lib/api'

interface Msg {
  role: 'user' | 'assistant'
  text: string
  cards: any[]
  evidence: EvidenceEntry[]
  tools: { name: string; done: boolean; ok?: boolean }[]
  error?: string
}

/* Human-readable labels for the "working on it" strip. Naming the actual
   data source rather than showing a generic spinner makes the wait feel
   purposeful and quietly teaches what the system is doing. */
const TOOL_LABEL: Record<string, string> = {
  get_soil_profile: 'Reading the soil survey for your field',
  get_weather: 'Checking the weather model',
  get_irrigation_advice: 'Running the water balance',
  assess_crop_suitability: 'Matching crops to your land',
  compare_regenerative_practices: 'Projecting your soil carbon',
  diagnose: 'Looking at your photo and checking disease pressure',
  get_crop_health: 'Reading the satellite view of your field',
  get_mandi_prices: 'Checking today\'s mandi rates',
}

export default function App() {
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [languages, setLanguages] = useState<LanguageInfo[]>([])
  const [lang, setLang] = useState(session.language || 'en')
  const [coords, setCoords] = useState<{ lat: number; lon: number } | null>(null)
  const [locating, setLocating] = useState(false)
  const [listening, setListening] = useState(false)
  const [health, setHealth] = useState<any>(null)
  const [showLangPicker, setShowLangPicker] = useState(false)

  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const recognitionRef = useRef<any>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const current = languages.find((l) => l.code === lang)
  const assistantName = current?.assistant_name || 'Saathi'

  useEffect(() => { fetchLanguages().then(setLanguages).catch(() => {}) }, [])
  useEffect(() => { fetchHealth().then(setHealth).catch(() => {}) }, [])
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) },
            [messages, busy])

  /* ---------------------------------------------------------------- */
  /* Location                                                          */
  /* ---------------------------------------------------------------- */

  const requestLocation = useCallback(() => {
    if (!navigator.geolocation) return
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setCoords({ lat: pos.coords.latitude, lon: pos.coords.longitude })
        setLocating(false)
      },
      () => setLocating(false),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 300000 },
    )
  }, [])

  /* ---------------------------------------------------------------- */
  /* Voice input                                                       */
  /* ---------------------------------------------------------------- */

  /**
   * Speech recognition.
   *
   * Uses the browser Web Speech API, which on Android Chrome is backed by
   * Google's own speech models at no cost and with no key — the right default
   * for a platform whose users are cost-sensitive. Cloud Speech-to-Text is
   * the production path where server-side transcription is needed (the IVR
   * channel, or languages the browser does not expose).
   */
  const toggleVoice = useCallback(() => {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SR) {
      alert('Voice input is not supported in this browser. Please type instead.')
      return
    }
    if (listening) {
      recognitionRef.current?.stop()
      setListening(false)
      return
    }
    const recognition = new SR()
    // Map our language codes to BCP-47 tags the recogniser expects.
    const TAG: Record<string, string> = {
      hi: 'hi-IN', pa: 'pa-Guru-IN', bn: 'bn-IN', mr: 'mr-IN', te: 'te-IN',
      ta: 'ta-IN', gu: 'gu-IN', kn: 'kn-IN', ml: 'ml-IN', or: 'or-IN',
      en: 'en-IN', zh: 'zh-CN', ru: 'ru-RU', pt: 'pt-BR',
    }
    recognition.lang = TAG[lang] || 'en-IN'
    recognition.interimResults = true
    recognition.continuous = false

    recognition.onresult = (e: any) => {
      const text = Array.from(e.results).map((r: any) => r[0].transcript).join('')
      setInput(text)
    }
    recognition.onend = () => setListening(false)
    recognition.onerror = () => setListening(false)

    recognitionRef.current = recognition
    recognition.start()
    setListening(true)
  }, [listening, lang])

  /* ---------------------------------------------------------------- */
  /* Voice output                                                      */
  /* ---------------------------------------------------------------- */

  const speak = useCallback((text: string) => {
    if (!('speechSynthesis' in window)) return
    window.speechSynthesis.cancel()
    const utterance = new SpeechSynthesisUtterance(text)
    const TAG: Record<string, string> = {
      hi: 'hi-IN', pa: 'pa-IN', bn: 'bn-IN', mr: 'mr-IN', te: 'te-IN',
      ta: 'ta-IN', gu: 'gu-IN', kn: 'kn-IN', en: 'en-IN',
    }
    utterance.lang = TAG[lang] || 'en-IN'
    // Slightly slower than default: advisory content carries numbers people
    // need to retain, and the default rate is tuned for notifications.
    utterance.rate = 0.92
    window.speechSynthesis.speak(utterance)
  }, [lang])

  /* ---------------------------------------------------------------- */
  /* Send                                                              */
  /* ---------------------------------------------------------------- */

  const send = useCallback(async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || busy) return

    setInput('')
    setBusy(true)
    setMessages((m) => [
      ...m,
      { role: 'user', text: trimmed, cards: [], evidence: [], tools: [] },
      { role: 'assistant', text: '', cards: [], evidence: [], tools: [] },
    ])

    const controller = new AbortController()
    abortRef.current = controller

    const update = (fn: (m: Msg) => Msg) =>
      setMessages((prev) => {
        const next = [...prev]
        next[next.length - 1] = fn(next[next.length - 1])
        return next
      })

    try {
      for await (const ev of streamChat({
        message: trimmed,
        farmer_id: session.farmerId,
        field_id: session.fieldId,
        language: lang,
        latitude: coords?.lat,
        longitude: coords?.lon,
      }, controller.signal)) {
        switch (ev.type) {
          case 'session':
            session.farmerId = ev.farmer_id
            if (ev.field_id) session.fieldId = ev.field_id
            break
          case 'text':
            update((m) => ({ ...m, text: m.text + ev.delta }))
            break
          case 'tool_start':
            update((m) => ({ ...m, tools: [...m.tools, { name: ev.name, done: false }] }))
            break
          case 'tool_result':
            update((m) => ({
              ...m,
              tools: m.tools.map((t) =>
                t.name === ev.name && !t.done ? { ...t, done: true, ok: ev.ok } : t),
            }))
            break
          case 'card':
            update((m) => ({ ...m, cards: [...m.cards, ev] }))
            break
          case 'done':
            update((m) => ({ ...m, evidence: ev.evidence || [] }))
            break
          case 'error':
            update((m) => ({ ...m, error: ev.message }))
            break
        }
      }
    } catch (e: any) {
      if (e?.name !== 'AbortError') {
        update((m) => ({ ...m, error: String(e?.message || e) }))
      }
    } finally {
      setBusy(false)
      abortRef.current = null
    }
  }, [busy, lang, coords])

  const stop = () => { abortRef.current?.abort(); setBusy(false) }

  /* ---------------------------------------------------------------- */
  /* Photo diagnosis                                                   */
  /* ---------------------------------------------------------------- */

  /**
   * Send a crop photo for diagnosis.
   *
   * Posted as multipart rather than base64 in JSON: phone photos run 2-5 MB
   * and base64 inflates them by a third, which is a real cost on a metered
   * rural connection.
   *
   * The preview is a local object URL, so the farmer sees their photo in the
   * conversation instantly while the upload is still in flight.
   */
  const sendPhoto = useCallback(async (file: File) => {
    if (busy) return
    const previewUrl = URL.createObjectURL(file)
    setBusy(true)
    setMessages((m) => [
      ...m,
      { role: 'user', text: input.trim() || 'Something is wrong with my crop',
        cards: [{ card: 'photo', imageUrl: previewUrl }], evidence: [], tools: [] },
      { role: 'assistant', text: '',
        cards: [], evidence: [],
        tools: [{ name: 'diagnose', done: false }] },
    ])
    const note = input.trim()
    setInput('')

    const form = new FormData()
    form.append('image', file)
    form.append('language', lang)
    form.append('note', note)
    if (coords) {
      form.append('latitude', String(coords.lat))
      form.append('longitude', String(coords.lon))
    }
    if (session.fieldId) form.append('field_id', session.fieldId)

    try {
      const r = await fetch('/api/diagnose', { method: 'POST', body: form })
      const d = await r.json()
      setMessages((prev) => {
        const next = [...prev]
        const last = next[next.length - 1]
        next[next.length - 1] = {
          ...last,
          tools: [{ name: 'diagnose', done: true, ok: !!d.ok }],
          text: d.ok ? (d.farmer_summary || '') : '',
          cards: d.ok ? [{ card: 'diagnosis', ...d, imageUrl: previewUrl }] : [],
          error: d.ok ? undefined : (d.abstain_reason || 'Diagnosis failed'),
          evidence: d.evidence ? [{ tool: 'diagnose_crop_photo', input: {},
                                    evidence: d.evidence }] : [],
        }
        return next
      })
    } catch (e: any) {
      setMessages((prev) => {
        const next = [...prev]
        next[next.length - 1] = { ...next[next.length - 1],
          error: String(e?.message || e) }
        return next
      })
    } finally {
      setBusy(false)
    }
  }, [busy, input, lang, coords])

  const empty = messages.length === 0

  /* ---------------------------------------------------------------- */
  /* Render                                                            */
  /* ---------------------------------------------------------------- */

  return (
    <div className="h-full flex flex-col" style={{ background: 'var(--bg)' }}>

      {/* Header: deliberately minimal. A language switch and a location
          button are the only chrome, because they are the only two things
          that change what an answer means. */}
      <header className="flex items-center justify-between px-4 py-3 border-b"
              style={{ borderColor: 'var(--border)' }}>
        <div className="flex items-center gap-2">
          <span className="text-xl" aria-hidden>🌾</span>
          <span className="font-semibold">{assistantName}</span>
          {health && !health.google_ai?.configured && (
            <span className="text-[11px] px-2 py-0.5 rounded-full"
                  style={{ background: '#fdf0ea', color: '#c2703d' }}>
              Gemini key not set
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={requestLocation}
                  className="text-[13px] px-3 py-1.5 rounded-full border"
                  style={{
                    borderColor: coords ? 'var(--accent)' : 'var(--border)',
                    color: coords ? 'var(--accent)' : 'var(--text-muted)',
                  }}>
            {locating ? 'Finding…' : coords ? '📍 Field set' : '📍 Set field'}
          </button>
          <button onClick={() => setShowLangPicker(!showLangPicker)}
                  className="text-[13px] px-3 py-1.5 rounded-full border"
                  style={{ borderColor: 'var(--border)', color: 'var(--text-muted)' }}>
            {current?.name || 'English'}
          </button>
        </div>
      </header>

      {showLangPicker && (
        <div className="px-4 py-3 border-b flex flex-wrap gap-2"
             style={{ borderColor: 'var(--border)', background: 'var(--bg-sunken)' }}>
          {languages.map((l) => (
            <button key={l.code}
                    onClick={() => { setLang(l.code); session.language = l.code; setShowLangPicker(false) }}
                    className="text-[14px] px-3 py-1.5 rounded-full border"
                    style={{
                      borderColor: l.code === lang ? 'var(--accent)' : 'var(--border)',
                      background: l.code === lang ? 'var(--accent-soft)' : 'transparent',
                      color: l.code === lang ? 'var(--accent)' : 'var(--text)',
                    }}>
              {l.name}
            </button>
          ))}
        </div>
      )}

      {/* Conversation */}
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-2xl mx-auto px-4 py-6">

          {empty && (
            <div className="flex flex-col items-center justify-center text-center pt-16 pb-8 animate-in">
              <div className="text-5xl mb-4" aria-hidden>🌾</div>
              <h1 className="text-2xl font-semibold mb-2">
                {lang === 'hi' ? 'नमस्ते, मैं साथी हूँ'
                 : lang === 'pa' ? 'ਸਤ ਸ੍ਰੀ ਅਕਾਲ, ਮੈਂ ਸਾਥੀ ਹਾਂ'
                 : `Hello, I'm ${assistantName}`}
              </h1>
              <p className="text-[15px] mb-8 max-w-md" style={{ color: 'var(--text-muted)' }}>
                {lang === 'hi' ? 'अपने खेत के बारे में कुछ भी पूछिए — बोलकर या लिखकर।'
                 : lang === 'pa' ? 'ਆਪਣੇ ਖੇਤ ਬਾਰੇ ਕੁਝ ਵੀ ਪੁੱਛੋ — ਬੋਲ ਕੇ ਜਾਂ ਲਿਖ ਕੇ।'
                 : 'Ask me anything about your field — speak or type.'}
              </p>
              <div className="flex flex-col gap-2 w-full max-w-md">
                {(current?.suggestions || []).map((s, i) => (
                  <button key={i} onClick={() => send(s)}
                          className="text-left px-4 py-3 rounded-xl border text-[15px] transition-colors"
                          style={{ borderColor: 'var(--border)', background: 'var(--bg-raised)' }}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) => (
            <div key={i} className="mb-5">
              {m.role === 'user' ? (
                <div className="flex justify-end">
                  <div className="rounded-2xl px-4 py-2.5 max-w-[85%] text-[16px]"
                       style={{ background: 'var(--accent-soft)', color: 'var(--text)' }}>
                    {m.cards.find((c: any) => c.card === 'photo') && (
                      <img
                        src={m.cards.find((c: any) => c.card === 'photo').imageUrl}
                        alt="Crop photo"
                        className="rounded-xl mb-2 max-h-48 object-cover" />
                    )}
                    {m.text}
                  </div>
                </div>
              ) : (
                <div className="animate-in">
                  {/* Progress strip: names the data source being consulted. */}
                  {m.tools.length > 0 && !m.text && (
                    <div className="space-y-1 mb-2">
                      {m.tools.map((t, j) => (
                        <div key={j} className="flex items-center gap-2 text-[14px]"
                             style={{ color: 'var(--text-muted)' }}>
                          <span>{t.done ? (t.ok ? '✓' : '⚠') : '◌'}</span>
                          <span>{TOOL_LABEL[t.name] || t.name}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {m.text && (
                    <div className="text-[17px] whitespace-pre-wrap leading-relaxed">
                      {m.text}
                    </div>
                  )}

                  {m.cards.filter((c: any) => c.card !== 'photo')
                    .map((c, j) => <RenderCard key={j} card={c} />)}

                  {m.error && (
                    <div className="rounded-xl p-3 text-[14px] mt-2"
                         style={{ background: '#fdf0ea', color: '#c2452d' }}>
                      {m.error}
                    </div>
                  )}

                  {m.text && !busy && (
                    <div className="flex items-center gap-3 mt-2">
                      <button onClick={() => speak(m.text)}
                              className="text-[13px] underline underline-offset-2"
                              style={{ color: 'var(--text-muted)', minHeight: 0 }}>
                        🔊 Listen
                      </button>
                      <EvidenceLedger entries={m.evidence} />
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      </main>

      {/* Composer */}
      <footer className="border-t px-4 py-3" style={{ borderColor: 'var(--border)' }}>
        <div className="max-w-2xl mx-auto">
          <div className="flex items-end gap-2 rounded-2xl border px-3 py-2"
               style={{ borderColor: 'var(--border)', background: 'var(--bg-raised)' }}>
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input) }
              }}
              rows={1}
              placeholder={
                lang === 'hi' ? 'अपने खेत के बारे में पूछिए…'
                : lang === 'pa' ? 'ਆਪਣੇ ਖੇਤ ਬਾਰੇ ਪੁੱਛੋ…'
                : 'Ask about your field…'
              }
              className="flex-1 resize-none bg-transparent outline-none py-2 text-[16px]"
              style={{ color: 'var(--text)', maxHeight: 140 }}
            />
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              capture="environment"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) sendPhoto(f)
                e.target.value = ''
              }}
            />
            <button onClick={() => fileRef.current?.click()}
                    aria-label="Photograph the crop"
                    disabled={busy}
                    className="rounded-full w-11 h-11 flex items-center justify-center shrink-0 disabled:opacity-30"
                    style={{ background: 'var(--bg-sunken)', color: 'var(--text-muted)' }}>
              📷
            </button>
            <button onClick={toggleVoice}
                    aria-label={listening ? 'Stop recording' : 'Speak'}
                    className={`rounded-full w-11 h-11 flex items-center justify-center shrink-0 ${listening ? 'recording' : ''}`}
                    style={{
                      background: listening ? 'var(--accent)' : 'var(--bg-sunken)',
                      color: listening ? '#fff' : 'var(--text-muted)',
                    }}>
              🎤
            </button>
            <button onClick={() => (busy ? stop() : send(input))}
                    aria-label={busy ? 'Stop' : 'Send'}
                    disabled={!busy && !input.trim()}
                    className="rounded-full w-11 h-11 flex items-center justify-center shrink-0 disabled:opacity-30"
                    style={{ background: 'var(--accent)', color: '#fff' }}>
              {busy ? '■' : '↑'}
            </button>
          </div>
          <div className="text-[11px] text-center mt-2" style={{ color: 'var(--text-muted)' }}>
            Advice is generated from soil, weather and satellite models. For
            anything costly or risky, confirm with your local KVK or extension officer.
          </div>
        </div>
      </footer>
    </div>
  )
}
