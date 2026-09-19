/**
 * Interface translation.
 *
 * Every visible label goes through t(). English strings are the keys; the
 * first time a string is seen in a non-English language it is queued, sent
 * to the server in one batch, translated once and cached (server-side on
 * disk, client-side in localStorage). Until a translation arrives the English
 * text shows, so the page never waits on it.
 */

import { useSyncExternalStore } from 'react'

type Table = Record<string, string>

const tables: Record<string, Table> = {}
const pending: Record<string, Set<string>> = {}
const listeners = new Set<() => void>()
let version = 0
let flushTimer: ReturnType<typeof setTimeout> | null = null

function storageKey(lang: string) { return `agrin.ui.${lang}` }

function table(lang: string): Table {
  if (!tables[lang]) {
    try { tables[lang] = JSON.parse(localStorage.getItem(storageKey(lang)) || '{}') }
    catch { tables[lang] = {} }
  }
  return tables[lang]
}

function notify() { version++; listeners.forEach((l) => l()) }

let flushing = false

async function flush() {
  flushTimer = null
  // One batch at a time. Strings are discovered while earlier ones are still
  // being translated, and starting a new request for each wave sent three
  // overlapping translation calls at once -- tripling the quota spent and
  // racing each other on the server's cache, so two of the three were lost.
  if (flushing) { flushTimer = setTimeout(flush, 300); return }
  flushing = true
  try {
  for (const lang of Object.keys(pending)) {
    // Drop anything the shipped file supplied while these were queued.
    const strings = [...pending[lang]].filter((x) => !table(lang)[x])
    delete pending[lang]
    if (!strings.length) continue
    try {
      const r = await fetch('/api/ui-strings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ language: lang, strings }),
      })
      const d = await r.json()
      Object.assign(table(lang), d.translations || {})
      try { localStorage.setItem(storageKey(lang), JSON.stringify(table(lang))) } catch { /* full */ }
      notify()
    } catch { /* stay in English */ }
  }
  } finally {
    flushing = false
  }
}

const bundled = new Set<string>()

/**
 * Load the pre-built translation file shipped with the app.
 *
 * Every fixed interface string is translated ahead of time
 * (scripts/build_ui_translations.py), so choosing a language is instant and
 * spends no quota. Only text arriving from live data falls through to the
 * on-demand path below.
 */
async function loadBundled(lang: string) {
  if (lang === 'en' || bundled.has(lang)) return
  bundled.add(lang)
  try {
    const r = await fetch(`/i18n/${lang}.json`)
    if (!r.ok) return
    const shipped: Table = await r.json()
    // Shipped entries fill gaps but never overwrite a newer on-demand result.
    tables[lang] = { ...shipped, ...table(lang) }
    notify()
  } catch { /* fall back to on-demand */ }
}

export function translate(lang: string, english: string, vars?: Record<string, string | number>): string {
  let out = english
  if (lang && lang !== 'en') {
    const known = table(lang)[english]
    if (known) out = known
    else if (bundled.has(lang)) {
      // Only strings the shipped file does not cover go to the server.
      (pending[lang] ||= new Set()).add(english)
      if (!flushTimer) flushTimer = setTimeout(flush, 1500)
    } else {
      loadBundled(lang)
    }
  }
  if (vars) for (const [k, v] of Object.entries(vars)) out = out.split(`{${k}}`).join(String(v))
  return out
}

// Start in the saved language so the first paint is already translated.
let current = (() => { try { return localStorage.getItem('agrin.language') || 'en' } catch { return 'en' } })()

/** Called by App whenever the farmer picks a language. */
export function setUiLanguage(lang: string) {
  loadBundled(lang)
  if (lang !== current) { current = lang; notify() }
}

const LOCALE: Record<string, string> = {
  hi: 'hi-IN', pa: 'pa-IN', bn: 'bn-IN', mr: 'mr-IN', te: 'te-IN', ta: 'ta-IN',
  gu: 'gu-IN', kn: 'kn-IN', ml: 'ml-IN', or: 'or-IN', as: 'as-IN', en: 'en-IN',
  zh: 'zh-CN', ru: 'ru-RU', pt: 'pt-BR', es: 'es-ES', fr: 'fr-FR', ar: 'ar',
  fa: 'fa-IR', am: 'am-ET', sw: 'sw-KE', af: 'af-ZA', zu: 'zu-ZA', xh: 'xh-ZA',
}

/** Locale for dates and weekday names, e.g. ਬੁੱਧ instead of Wed. */
export function uiLocale() { return LOCALE[current] || 'en-IN' }

export function useT() {
  useSyncExternalStore(
    (cb) => { listeners.add(cb); return () => listeners.delete(cb) },
    () => version,
  )
  return (english: string, vars?: Record<string, string | number>) => translate(current, english, vars)
}

loadBundled(current)
