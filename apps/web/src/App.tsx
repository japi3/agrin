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
import { FieldPanel } from './components/FieldPanel'
import { useT, setUiLanguage } from './lib/i18n'
import { streamChat, fetchLanguages, fetchHealth, saveField, session,
         type LanguageInfo, type EvidenceEntry } from './lib/api'

interface Msg {
  role: 'user' | 'assistant'
  text: string
  cards: any[]
  evidence: EvidenceEntry[]
  tools: { name: string; done: boolean; ok?: boolean }[]
  error?: string
  errorKind?: string
}

/* Human-readable labels for the "working on it" strip. Naming the actual
   data source rather than showing a generic spinner makes the wait feel
   purposeful and quietly teaches what the system is doing. */
/**
 * BCP-47 tags for speech recognition and synthesis.
 *
 * Kept in one place because input and output previously carried separate,
 * subtly different tables -- recognition used pa-Guru-IN while synthesis used
 * pa-IN, so a farmer could be understood in Punjabi and answered in English.
 */
const SPEECH_TAG: Record<string, string> = {
  hi: 'hi-IN', pa: 'pa-IN', bn: 'bn-IN', mr: 'mr-IN', te: 'te-IN',
  ta: 'ta-IN', gu: 'gu-IN', kn: 'kn-IN', ml: 'ml-IN', or: 'or-IN',
  as: 'as-IN', en: 'en-IN', zh: 'zh-CN', ru: 'ru-RU', pt: 'pt-BR',
  es: 'es-ES', fr: 'fr-FR', ar: 'ar-SA', fa: 'fa-IR', am: 'am-ET',
  sw: 'sw-KE', af: 'af-ZA', zu: 'zu-ZA', xh: 'xh-ZA',
}

// Indic scripts share enough phonology that a Hindi voice is a far better
// fallback than an English one when the exact language has no voice installed.
const INDIC = new Set(['hi', 'pa', 'bn', 'mr', 'te', 'ta', 'gu', 'kn', 'ml',
                       'or', 'as'])

/**
 * Error wording by kind, so it can be shown in the farmer's language.
 *
 * The server's messages carry changing details (seconds to wait), which makes
 * each one a unique string that cannot be translated ahead of time. The kind
 * is stable, so the interface picks fixed, pre-translated wording from it.
 */
const ERROR_TEXT: Record<string, string> = {
  rate_limited: 'Too many questions have come in at once. Please try again in a minute.',
  busy: 'The service is very busy right now. Please try again in a moment — your field details are saved.',
  timeout: 'The AI service is not responding right now. Please try again in a moment — your field details are saved.',
  network: 'The connection dropped. Please try again — your field details are saved.',
  upstream: 'Something went wrong reaching the AI service. Please try again.',
  not_configured: 'This installation is not set up correctly. Whoever runs this service needs to check it.',
}

const TOOL_LABEL: Record<string, string> = {
  get_soil_profile: 'Reading the soil survey for your field',
  get_weather: 'Checking the weather model',
  get_irrigation_advice: 'Running the water balance',
  assess_crop_suitability: 'Matching crops to your land',
  compare_regenerative_practices: 'Projecting your soil carbon',
  diagnose: 'Looking at your photo and checking disease pressure',
  get_crop_health: 'Reading the satellite view of your field',
  get_mandi_prices: 'Checking today\'s mandi rates',
  find_government_schemes: 'Looking up government schemes',
  find_place: 'Finding your village',
}

export default function App() {
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [languages, setLanguages] = useState<LanguageInfo[]>([])
  const [lang, setLang] = useState(session.language || 'en')
  useEffect(() => { setUiLanguage(lang) }, [lang])
  const tr = useT()
  const [coords, setCoords] = useState<{ lat: number; lon: number } | null>(null)
  const [locating, setLocating] = useState(false)
  const [listening, setListening] = useState(false)
  const [speaking, setSpeaking] = useState(false)
  // True between pressing Listen and the first sound actually coming out.
  // Server speech takes several seconds; without a label of its own the
  // button reads "Stop" in silence, which is what "it got stuck" was.
  const [speechLoading, setSpeechLoading] = useState(false)
  const [transcribing, setTranscribing] = useState(false)
  const [voiceHint, setVoiceHint] = useState('')
  const [online, setOnline] = useState(() => navigator.onLine)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const [health, setHealth] = useState<any>(null)
  const [showLangPicker, setShowLangPicker] = useState(false)
  // Open by default when a field is already saved. A returning farmer should
  // see how their field is doing without asking; a first-time user still
  // gets the blank conversation-first screen.
  const [panelOpen, setPanelOpen] = useState(() => Boolean(session.fieldId))
  const [fieldId, setFieldId] = useState<string | null>(session.fieldId)
  const [panelRefresh, setPanelRefresh] = useState(0)

  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const current = languages.find((l) => l.code === lang)
  const assistantName = current?.assistant_name || 'Saathi'

  useEffect(() => { fetchLanguages().then(setLanguages).catch(() => {}) }, [])

  // Connection state is shown rather than inferred from a failed request.
  // A farmer who knows the phone has no signal reads a failure as "wait",
  // not as "this tool is broken".
  useEffect(() => {
    const up = () => setOnline(true)
    const down = () => setOnline(false)
    window.addEventListener('online', up)
    window.addEventListener('offline', down)
    return () => {
      window.removeEventListener('online', up)
      window.removeEventListener('offline', down)
    }
  }, [])
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
      async (pos) => {
        const lat = pos.coords.latitude
        const lon = pos.coords.longitude
        setCoords({ lat, lon })
        setLocating(false)
        // Save it server-side so the field panel and season memory have
        // something durable to hang off, not just this browser tab.
        try {
          let farmer = session.farmerId
          if (!farmer) {
            const r = await fetch(`/api/farmer?language=${lang}`, { method: 'POST' })
            farmer = (await r.json()).farmer_id
            session.farmerId = farmer
          }
          const id = await saveField(farmer!, lat, lon)
          session.fieldId = id
          setFieldId(id)
          setPanelOpen(true)
        } catch {
          // Non-fatal: the conversation still works from coordinates alone.
        }
      },
      () => setLocating(false),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 300000 },
    )
  }, [lang])

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
  /**
   * Record the farmer speaking and transcribe it.
   *
   * Recorded audio is sent to the server, which transcribes through Gemini.
   * The browser's own recogniser is used only where it genuinely supports
   * the language, for the same reason as speech output: on most devices it
   * does not support Indian languages and fails in ways that look like
   * success.
   *
   * The server refuses silent recordings deterministically before the model
   * sees them, because a model given silence will invent a sentence rather
   * than report an empty room -- and that sentence would then be answered as
   * though the farmer had asked it.
   */
  const stopRecording = useCallback(() => {
    recorderRef.current?.stop()
    setListening(false)
  }, [])

  const toggleVoice = useCallback(async () => {
    if (listening) {
      stopRecording()
      return
    }
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      alert(tr('Voice input is not supported in this browser. Please type instead.'))
      return
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = new MediaRecorder(stream)
      chunksRef.current = []
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }
      recorder.onstop = async () => {
        // Release the microphone promptly; a lingering recording indicator
        // is alarming and, on a shared phone, reasonably so.
        stream.getTracks().forEach((t) => t.stop())

        const blob = new Blob(chunksRef.current, { type: recorder.mimeType })
        if (blob.size < 2000) {
          return   // Too short to contain anything; do not spend a request.
        }
        setTranscribing(true)
        try {
          const form = new FormData()
          form.append('audio', blob, 'recording.webm')
          form.append('language', lang)
          const r = await fetch('/api/transcribe', { method: 'POST', body: form })
          const d = await r.json()
          if (d.ok && d.text) {
            setInput(d.text)
          } else if (d.abstain_reason) {
            // Shown in the composer rather than as an alert, so it reads as
            // guidance rather than an error.
            setVoiceHint(d.abstain_reason)
            setTimeout(() => setVoiceHint(''), 5000)
          }
        } catch {
          setVoiceHint('Could not send the recording. Please try typing.')
          setTimeout(() => setVoiceHint(''), 5000)
        } finally {
          setTranscribing(false)
        }
      }
      recorderRef.current = recorder
      recorder.start()
      setListening(true)
    } catch {
      alert(tr('I could not use the microphone. Please allow access, or type instead.'))
    }
  }, [listening, lang, stopRecording])

  /* ---------------------------------------------------------------- */
  /* Voice output                                                      */
  /* ---------------------------------------------------------------- */

  /**
   * Speak a reply aloud in the farmer's language.
   *
   * Setting `utterance.lang` alone is not enough, which is the bug this
   * fixes: browsers fall back to the default system voice when no voice is
   * explicitly assigned, so Punjabi text was being read by an English voice
   * — audible as gibberish, and worse than silence for someone relying on
   * audio because they cannot read.
   *
   * So a matching voice is selected from the installed set, preferring an
   * exact locale match, then the bare language, then a Hindi voice as a last
   * resort for Indic scripts (its phoneme set renders Devanagari-family text
   * far better than an English voice does).
   */
  const pickVoice = useCallback((tag: string): SpeechSynthesisVoice | null => {
    const voices = window.speechSynthesis.getVoices()
    if (!voices.length) return null
    const base = tag.split('-')[0]
    return (
      voices.find((v) => v.lang.toLowerCase() === tag.toLowerCase()) ||
      voices.find((v) => v.lang.toLowerCase().replace('_', '-') === tag.toLowerCase()) ||
      voices.find((v) => v.lang.toLowerCase().startsWith(base)) ||
      (INDIC.has(base) ? voices.find((v) => v.lang.toLowerCase().startsWith('hi')) : null) ||
      null
    )
  }, [])

  // Chrome and Safari build the voice list asynchronously: the very first
  // getVoices() returns an empty array and only then starts loading. Because
  // the list was first asked for at the moment Listen was pressed, it was
  // always empty then, and every first press fell through to server speech --
  // a ten second wait even on a phone that already had a perfectly good local
  // voice installed. Asking on mount means the answer is ready by the time
  // anyone presses anything.
  useEffect(() => {
    if (!('speechSynthesis' in window)) return
    const warm = () => window.speechSynthesis.getVoices()
    warm()
    window.speechSynthesis.addEventListener('voiceschanged', warm)
    return () => window.speechSynthesis.removeEventListener('voiceschanged', warm)
  }, [])

  const audioRef = useRef<HTMLAudioElement | null>(null)
  const speechRunRef = useRef<{ cancelled: boolean; controller: AbortController } | null>(null)

  const stopSpeaking = useCallback(() => {
    const run = speechRunRef.current
    if (run) { run.cancelled = true; run.controller.abort() }
    speechRunRef.current = null
    audioRef.current?.pause()
    audioRef.current = null
    window.speechSynthesis?.cancel()
    setSpeaking(false)
    setSpeechLoading(false)
  }, [])

  /**
   * Read a reply aloud.
   *
   * Server speech first, browser speech as fallback.
   *
   * The browser path is cheaper and needs no round trip, which matters on a
   * metered rural connection. But most devices ship no voice at all for most
   * Indian languages, and the browser silently substitutes an English voice
   * rather than failing -- so Punjabi came out as an English speaker reading
   * Gurmukhi phonetically. That is worse than silence for someone relying on
   * audio precisely because they cannot read.
   *
   * So: if the browser has a genuine voice for this language, use it. If it
   * does not, ask the server, which synthesises through Gemini.
   */
  const speak = useCallback(async (text: string) => {
    const tag = SPEECH_TAG[lang] || 'en-IN'

    // Stop anything already playing, from either path.
    stopSpeaking()

    const localVoice = pickVoice(tag)
    const baseLang = tag.split('-')[0]
    const localVoiceIsRight =
      localVoice && localVoice.lang.toLowerCase().startsWith(baseLang)

    if (localVoiceIsRight && 'speechSynthesis' in window) {
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.lang = tag
      utterance.voice = localVoice
      // Slower than default: advisory content carries numbers people need to
      // retain, and the default rate is tuned for notifications.
      utterance.rate = 0.92
      // A local voice starts instantly, so it needs no preparing state — but
      // it must still flip the button to Stop, or pressing it again restarts
      // the reply instead of ending it.
      utterance.onend = () => setSpeaking(false)
      utterance.onerror = () => setSpeaking(false)
      setSpeaking(true)
      window.speechSynthesis.speak(utterance)
      return
    }

    // Server speech, one sentence at a time.
    //
    // Synthesising a whole reply as one clip took 27 seconds before any sound
    // came out, and produced a 1.9 MB file. With no way to stop it the button
    // simply looked stuck. Sentence by sentence, the first words play within
    // a few seconds, the next sentence is fetched while the current one
    // plays, and Stop works at any point.
    const sentences = (text.match(/[^.!?।\n]+[.!?।]*/g) || [text])
      .map((x) => x.trim()).filter(Boolean)
    // Two requests, not one per sentence: a short opening so sound starts
    // quickly, then everything else. The free speech quota allows only a
    // handful of requests a minute, and a request per sentence ran out of it
    // partway through a single reply.
    const chunks: string[] = sentences.length > 1
      ? [sentences[0], sentences.slice(1).join(' ')]
      : sentences

    const run = { cancelled: false, controller: new AbortController() }
    speechRunRef.current = run
    setSpeaking(true)
    setSpeechLoading(true)

    const fetchChunk = async (chunk: string): Promise<string> => {
      const timeout = setTimeout(() => run.controller.abort(), 45000)
      try {
        const r = await fetch('/api/speak', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: chunk, language: lang }),
          signal: run.controller.signal,
        })
        if (!r.ok) throw new Error(String(r.status))
        return URL.createObjectURL(await r.blob())
      } finally {
        clearTimeout(timeout)
      }
    }

    try {
      let pending: Promise<string> | null = fetchChunk(chunks[0])
      for (let i = 0; i < chunks.length; i++) {
        if (run.cancelled) break
        const url: string = await pending!
        // Start fetching the next sentence while this one plays.
        pending = i + 1 < chunks.length ? fetchChunk(chunks[i + 1]) : null
        pending?.catch(() => undefined)
        if (run.cancelled) break
        const audio = new Audio(url)
        audioRef.current = audio
        await new Promise<void>((resolve, reject) => {
          audio.onended = () => resolve()
          audio.onerror = () => reject(new Error('playback'))
          audio.play()
            .then(() => { if (!run.cancelled) setSpeechLoading(false) })
            .catch(reject)
        })
        URL.revokeObjectURL(url)
      }
    } catch {
      if (!run.cancelled) {
        // Deliberately no fallback to a wrong-language browser voice: an
        // English voice sounding out Gurmukhi is gibberish, and worse than
        // an honest message for someone who cannot read the screen.
        setVoiceHint(tr('Could not read this aloud right now. Please try again in a moment.'))
        setTimeout(() => setVoiceHint(''), 5000)
      }
    } finally {
      if (speechRunRef.current === run) {
        speechRunRef.current = null
        setSpeaking(false)
        setSpeechLoading(false)
      }
    }
  }, [lang, pickVoice, stopSpeaking])

  /* ---------------------------------------------------------------- */
  /* Send                                                              */
  /* ---------------------------------------------------------------- */

  const send = useCallback(async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed || busy) return

    // Fail before sending rather than after a timeout. Every answer needs
    // soil, weather, satellite or a model, so there is nothing honest to
    // return offline -- but saying so immediately, and keeping what they
    // typed, is very different from a spinner that dies silently.
    if (!navigator.onLine) {
      setMessages((m) => [
        ...m,
        { role: 'user', text: trimmed, cards: [], evidence: [], tools: [] },
        { role: 'assistant', text: '', cards: [], evidence: [], tools: [],
          error: tr('Your phone has no signal right now. I need to check the weather and your soil to answer this. Your question is saved — send it again once you have a connection.') },
      ])
      setInput(trimmed)
      return
    }

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
        // Without this the server opens a fresh conversation on every turn
        // and the model sees no history at all -- the assistant re-asks for
        // the village it was told one message ago.
        conversation_id: session.conversationId,
        farmer_id: session.farmerId,
        field_id: session.fieldId,
        language: lang,
        latitude: coords?.lat,
        longitude: coords?.lon,
      }, controller.signal)) {
        switch (ev.type) {
          case 'session':
            session.farmerId = ev.farmer_id
            session.conversationId = ev.conversation_id
            if (ev.field_id) {
              session.fieldId = ev.field_id
              setFieldId(ev.field_id)
            }
            break
          case 'field':
            // The farmer named their village and it became their field.
            session.fieldId = ev.field_id
            setFieldId(ev.field_id)
            setCoords({ lat: ev.latitude, lon: ev.longitude })
            setPanelOpen(true)
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
            setPanelRefresh((n) => n + 1)
            break
          case 'error':
            update((m) => ({ ...m, error: ev.message, errorKind: ev.kind }))
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
          {!online && (
            <span className="text-[11px] px-2 py-0.5 rounded-full"
                  style={{ background: 'var(--bg-sunken)', color: '#c2703d' }}>
              {tr('No signal')}
            </span>
          )}
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
            {locating ? tr('Finding…') : coords ? `📍 ${tr('Field set')}` : `📍 ${tr('Set field')}`}
          </button>
          {fieldId && (
            <button onClick={() => setPanelOpen(!panelOpen)}
                    aria-label={tr('Show field details')}
                    className="text-[13px] px-3 py-1.5 rounded-full border"
                    style={{ borderColor: 'var(--border)', color: 'var(--text-muted)' }}>
              {tr('My field')}
            </button>
          )}
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

      {/* Conversation + field panel */}
      <div className="flex-1 flex min-h-0">
      <main className="flex-1 overflow-y-auto">
        <div className="max-w-2xl mx-auto px-4 py-6">

          {empty && (
            <div className="flex flex-col items-center justify-center text-center pt-16 pb-8 animate-in">
              <div className="text-5xl mb-4" aria-hidden>🌾</div>
              <h1 className="text-2xl font-semibold mb-2">
                {lang === 'hi' ? 'नमस्ते, मैं साथी हूँ'
                 : lang === 'pa' ? 'ਸਤ ਸ੍ਰੀ ਅਕਾਲ, ਮੈਂ ਸਾਥੀ ਹਾਂ'
                 : tr("Hello, I'm {name}", { name: assistantName })}
              </h1>
              <p className="text-[15px] mb-8 max-w-md" style={{ color: 'var(--text-muted)' }}>
                {lang === 'hi' ? 'अपने खेत के बारे में कुछ भी पूछिए — बोलकर या लिखकर।'
                 : lang === 'pa' ? 'ਆਪਣੇ ਖੇਤ ਬਾਰੇ ਕੁਝ ਵੀ ਪੁੱਛੋ — ਬੋਲ ਕੇ ਜਾਂ ਲਿਖ ਕੇ।'
                 : tr('Ask me anything about your field — speak or type.')}
              </p>
              <div className="flex flex-col gap-2 w-full max-w-md">
                {(current?.suggestions || []).map((s, i) => (
                  // tr() on a hand-written localised suggestion finds no entry
                  // and returns it unchanged; on the English fallback set it
                  // finds the shipped translation. So the six languages with
                  // hand-written questions keep them, and the rest stop
                  // showing English.
                  <button key={i} onClick={() => send(tr(s))}
                          className="text-left px-4 py-3 rounded-xl border text-[15px] transition-colors"
                          style={{ borderColor: 'var(--border)', background: 'var(--bg-raised)' }}>
                    {tr(s)}
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
                  {/* Before any server event arrives there is nothing to
                      report, and on a rate-limited or slow model that gap ran
                      to ten seconds of blank screen. An immediate indicator
                      is not decoration: it is the difference between "this is
                      working" and "this is broken", and the farmer decides
                      which within about two seconds. */}
                  {busy && i === messages.length - 1
                    && m.tools.length === 0 && !m.text && !m.error && (
                    <div className="flex items-center gap-2 text-[14px]"
                         style={{ color: 'var(--text-muted)' }}>
                      <span className="inline-block w-2 h-2 rounded-full animate-pulse"
                            style={{ background: 'var(--accent)' }} />
                      <span>{tr('Thinking about your field…')}</span>
                    </div>
                  )}

                  {/* Progress strip: names the data source being consulted. */}
                  {m.tools.length > 0 && !m.text && (
                    <div className="space-y-1 mb-2">
                      {m.tools.map((t, j) => (
                        <div key={j} className="flex items-center gap-2 text-[14px]"
                             style={{ color: 'var(--text-muted)' }}>
                          <span>{t.done ? (t.ok ? '✓' : '⚠') : '◌'}</span>
                          <span>{tr(TOOL_LABEL[t.name] || t.name)}</span>
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
                      {tr(ERROR_TEXT[m.errorKind || ''] ?? m.error)}
                    </div>
                  )}

                  {m.text && !busy && (
                    <div className="flex items-center gap-3 mt-2">
                      <button onClick={() => (speaking ? stopSpeaking() : speak(m.text))}
                              className="text-[13px] underline underline-offset-2"
                              style={{ color: 'var(--text-muted)', minHeight: 0 }}>
                        {speechLoading
                          ? `◌ ${tr('Getting the audio ready…')}`
                          : speaking ? `■ ${tr('Stop')}` : `🔊 ${tr('Listen')}`}
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

      <FieldPanel
        fieldId={fieldId}
        open={panelOpen}
        onClose={() => setPanelOpen(false)}
        onAsk={(q) => { setPanelOpen(false); send(q) }}
        refreshKey={panelRefresh}
      />
      </div>

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
                : tr('Ask about your field…')
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
                    aria-label={tr('Photograph the crop')}
                    disabled={busy}
                    className="rounded-full w-11 h-11 flex items-center justify-center shrink-0 disabled:opacity-30"
                    style={{ background: 'var(--bg-sunken)', color: 'var(--text-muted)' }}>
              📷
            </button>
            <button onClick={toggleVoice}
                    aria-label={listening ? 'Stop recording' : 'Speak'}
                    disabled={transcribing}
                    className={`rounded-full w-11 h-11 flex items-center justify-center shrink-0 disabled:opacity-50 ${listening ? 'recording' : ''}`}
                    style={{
                      background: listening ? 'var(--accent)' : 'var(--bg-sunken)',
                      color: listening ? '#fff' : 'var(--text-muted)',
                    }}>
              {transcribing ? '…' : '🎤'}
            </button>
            <button onClick={() => (busy ? stop() : send(input))}
                    aria-label={busy ? 'Stop' : 'Send'}
                    disabled={!busy && !input.trim()}
                    className="rounded-full w-11 h-11 flex items-center justify-center shrink-0 disabled:opacity-30"
                    style={{ background: 'var(--accent)', color: '#fff' }}>
              {busy ? '■' : '↑'}
            </button>
          </div>
          {(voiceHint || listening || transcribing) && (
            <div className="text-[13px] text-center mt-2"
                 style={{ color: voiceHint ? '#c2703d' : 'var(--accent)' }}>
              {voiceHint || (listening ? tr('Listening… tap the microphone again when done')
                                       : tr('Understanding what you said…'))}
            </div>
          )}
          <div className="text-[11px] text-center mt-2" style={{ color: 'var(--text-muted)' }}>
            {tr('Advice is generated from soil, weather and satellite models. For anything costly or risky, confirm with your local KVK or extension officer.')}
          </div>
        </div>
      </footer>
    </div>
  )
}
