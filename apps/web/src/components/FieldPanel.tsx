/**
 * The field panel: what a returning farmer sees the moment they open the app.
 *
 * The chat interface is deliberately empty for a first-time user — that is
 * the whole point of a conversation-first design. But for someone who checks
 * in most mornings, an empty box asks them to remember what to ask. This
 * panel answers the three questions they open the app for, before they type:
 * does my field need water, what is the weather doing, what is my soil.
 *
 * It only appears once a field is saved. New users still get the blank page.
 */

import { useEffect, useState } from 'react'
import { useT, uiLocale } from '../lib/i18n'

interface CropEntry {
  crop: string
  name?: string
  sowing_date?: string | null
  days_after_sowing?: number
  growth_stage?: string
  days_to_harvest?: number
}

interface Summary {
  field: {
    id: string; name: string | null; latitude: number; longitude: number
    area_hectares?: number | null; area_acres?: number | null
  }
  season: { crop: string; sowing_date: string | null } | null
  crops_growing?: CropEntry[]
  last_irrigation?: {
    date: string; days_ago: number | null
    hours_pumped?: number | null; method?: string | null
  } | null
  farmer_said?: { about: string; said: string; on: string }[]
  missing?: string[]
  photos_on_record?: number
  irrigation_by_crop?: any[]
  soil: {
    texture: string; ph: number | null; ph_class: string | null
    organic_carbon_g_per_kg: number | null
    available_water_mm_per_m: number | null
    confidence: string | null
  } | null
  weather: {
    rain_last_14_days_mm: number | null
    rain_next_7_days_mm: number | null
    today: any
    forecast: any[]
  } | null
  irrigation?: {
    verdict: string
    soil_moisture_percent: number
    days_until_stress: number | null
    gross_depth_mm: number
    growth_stage: string
    days_after_sowing: number
  }
}

const VERDICT: Record<string, { text: string; tone: string }> = {
  irrigate_now:         { text: 'Water today',        tone: '#c2452d' },
  irrigate_in_days:     { text: 'Water soon',         tone: '#c2703d' },
  wait_for_rain:        { text: 'Rain coming — wait', tone: 'var(--accent)' },
  no_irrigation_needed: { text: 'No water needed',    tone: 'var(--accent)' },
  insufficient_data:    { text: 'Not enough data',    tone: 'var(--text-muted)' },
}

// What tapping a gap should actually say. Phrased as the farmer speaking,
// because that is what lands in the conversation.
const MISSING_PROMPT: Record<string, string> = {
  'when it was sown': 'I want to tell you when I sowed my crop',
  'what is planted': 'I want to tell you what I have planted',
  'field size': 'I want to tell you how big my field is',
  'when it was last watered': 'I want to tell you when I last watered',
}

const PH_WORD: Record<string, string> = {
  strongly_acidic: 'very sour', slightly_acidic: 'slightly sour',
  neutral: 'balanced', alkaline: 'slightly salty',
  strongly_alkaline: 'very salty',
}

export function FieldPanel({
  fieldId, open, onClose, onAsk, refreshKey = 0, view = 'split', onView,
}: {
  fieldId: string | null
  open: boolean
  // Bumped when a reply finishes, so facts saved during that turn appear
  // without the farmer reloading the page.
  refreshKey?: number
  onClose: () => void
  onAsk: (q: string) => void
  view?: 'chat' | 'split' | 'field'
  onView?: (v: 'chat' | 'split' | 'field') => void
}) {
  const t = useT()
  const [data, setData] = useState<Summary | null>(null)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)
  // Set when the service worker served this from cache because the network
  // was unavailable. Showing yesterday's soil moisture as though it were
  // today's is precisely the kind of quiet wrongness this project exists to
  // avoid, so staleness is surfaced rather than hidden.
  const [stale, setStale] = useState(false)

  const [irrigationLoading, setIrrigationLoading] = useState(false)

  useEffect(() => {
    if (!fieldId || !open) return
    setLoading(true)
    setFailed(false)

    // Two requests, not one. Soil and weather are cached and return in well
    // under a second; the irrigation water balance takes ten or more. Waiting
    // for both made the panel show "Checking your field…" long enough to look
    // broken, so the fast half paints first and irrigation fills in after.
    fetch(`/api/field/${fieldId}/summary`)
      .then((r) => {
        if (!r.ok) return Promise.reject(r.status)
        setStale(r.headers.get('X-Agrin-Stale') === 'true')
        return r.json()
      })
      .then((d) => {
        setData(d)
        if (d.season?.crop && d.season?.sowing_date) {
          setIrrigationLoading(true)
          fetch(`/api/field/${fieldId}/summary?include_irrigation=true`)
            .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
            .then((full) => setData(full))
            .catch(() => {})
            .finally(() => setIrrigationLoading(false))
        }
      })
      .catch(() => setFailed(true))
      .finally(() => setLoading(false))
  }, [fieldId, open, refreshKey])

  if (!fieldId) return null

  const verdict = data?.irrigation ? VERDICT[data.irrigation.verdict] : null

  return (
    <>
      {/* Scrim: on a phone the panel covers the chat, so tapping away closes it. */}
      {open && (
        <div className="fixed inset-0 z-10 md:hidden"
             style={{ background: 'rgba(0,0,0,0.4)' }}
             onClick={onClose} />
      )}

      {/* On a phone this stays a drawer sliding over the conversation --
          half a phone is not a panel. On a wide screen it takes a real share
          of the width, which is what lets the farm be laid out as tiles
          instead of a list running off the bottom. */}
      <aside
        className={`fixed md:static right-0 top-0 h-full z-20 overflow-y-auto
                    border-l transition-transform duration-200
                    ${open ? 'translate-x-0' : 'translate-x-full md:hidden'}
                    w-[340px] max-w-[88vw]
                    ${view === 'field' ? 'md:w-full md:max-w-none'
                                       : 'md:w-1/2 md:max-w-none'}`}
        style={{
          // Width lives in classes, not here. An inline width beats any
          // class, so setting it here silently pinned the panel to 340px
          // and the half-width split never took effect.
          background: 'var(--bg-raised)', borderColor: 'var(--border)',
        }}
      >
        <div className="p-4">
          <div className="flex items-center justify-between mb-3">
            <span className="font-semibold">{t('Your field')}</span>
            <div className="flex items-center gap-1">
              {/* Widen the farm to fill the screen, or hand the width back
                  to the conversation. Hidden on a phone, where there is only
                  ever one of the two on screen. */}
              <button
                onClick={() => onView?.(view === 'field' ? 'split' : 'field')}
                aria-label={view === 'field' ? t('Show the conversation too')
                                             : t('Expand the field')}
                title={view === 'field' ? t('Show the conversation too')
                                        : t('Expand the field')}
                className="hidden md:block text-[15px] leading-none px-2"
                style={{ color: 'var(--text-muted)', minHeight: 0 }}>
                {view === 'field' ? '⇥' : '⇤'}
              </button>
            <button onClick={onClose}
                    aria-label={t('Close field panel')}
                    className="text-[20px] leading-none px-2"
                    style={{ color: 'var(--text-muted)', minHeight: 0 }}>
              ×
            </button>
            </div>
          </div>

          {loading && (
            <div className="text-[14px]" style={{ color: 'var(--text-muted)' }}>
              {t('Checking your field…')}
            </div>
          )}

          {failed && (
            <div className="text-[14px]" style={{ color: 'var(--text-muted)' }}>
              {t('Could not load your field just now. Ask me directly instead.')}
            </div>
          )}

          {stale && (
            <div className="mb-3 text-[13px] rounded-lg p-2"
                 style={{ background: 'var(--bg-sunken)', color: '#c2703d' }}>
              {t('You are offline. This is what your field looked like the last time there was a signal, not right now.')}
            </div>
          )}

          {/* Tiles rather than a column.
              
              Multi-column rather than a grid because the sections are
              genuinely different heights -- a weather strip is short, the
              crop list grows with the number of crops -- and a grid would
              leave ragged gaps beside the short ones. break-inside-avoid
              keeps a section whole rather than splitting it across columns,
              which is the failure this technique is known for. */}
          {/* What needs attention comes first.
              
              The farm used to open with its own name and coordinates, and a
              farmer had to read down past soil and weather to reach the one
              line telling them to do something. Where there is a verdict it
              leads; where the verdict cannot be computed, the reason it
              cannot is what leads instead -- and that is tappable. */}
          {data && !loading && (
            <div className={`space-y-3 ${
              view === 'field'
                ? 'md:columns-2 xl:columns-3 md:space-y-0 md:gap-3'
                : 'lg:columns-2 lg:space-y-0 lg:gap-3'
            } [&>*]:break-inside-avoid lg:[&>*]:mb-3
              [&>*]:rounded-2xl [&>*]:border [&>*]:p-3
              [&>*]:border-[var(--border)] [&>*]:bg-[var(--bg-sunken)]`}>
              {/* Water: the reason most farmers open the app */}
              {irrigationLoading && !data.irrigation && (
                <div className="rounded-xl p-3 border text-[14px]"
                     style={{ borderColor: 'var(--border)', background: 'var(--bg-sunken)',
                              color: 'var(--text-muted)' }}>
                  {t('Working out whether your field needs water…')}
                </div>
              )}
              {/* No verdict is not nothing to say. The water balance needs a
                  sowing date, and without one the farmer saw soil, weather
                  and no advice, with no hint that one missing fact was the
                  reason. */}
              {!data.irrigation && !irrigationLoading
                && (data.crops_growing?.length ?? 0) > 0
                && data.missing?.includes('when it was sown') && (
                <button
                  onClick={() => onAsk(t('I want to tell you when I sowed my crop'))}
                  className="w-full text-left rounded-xl p-3 border"
                  style={{ borderColor: '#c2703d', background: 'var(--bg-sunken)' }}>
                  <div className="text-[15px] font-medium" style={{ color: '#c2703d' }}>
                    {t('Tell me when you sowed')}
                  </div>
                  <div className="text-[13px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
                    {t('Then I can work out whether this field needs water.')}
                  </div>
                </button>
              )}
              {verdict && data.irrigation && (
                <button
                  onClick={() => onAsk(t('Does my field need water this week?'))}
                  className="w-full text-left rounded-xl p-3 border"
                  style={{ borderColor: verdict.tone, background: 'var(--bg-sunken)' }}
                >
                  <div className="text-[15px] font-medium" style={{ color: verdict.tone }}>
                    {t(verdict.text)}
                  </div>
                  <div className="text-[13px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
                    {t('Soil holding {n}% of its water', { n: data.irrigation.soil_moisture_percent })}
                    {data.irrigation.days_until_stress != null
                      ? ` · ${data.irrigation.days_until_stress === 1
                          ? t('1 day until the crop is stressed')
                          : t('{n} days until the crop is stressed', { n: data.irrigation.days_until_stress })}`
                      : ''}
                  </div>
                </button>
              )}

              {/* The farm itself */}
              <div>
                <div className="text-[15px] font-medium">
                  {data.field.name || t('My field')}
                </div>
                <div className="text-[13px]" style={{ color: 'var(--text-muted)' }}>
                  {/* No coordinates. Nobody describes their land as
                      31.321, 74.842, and the two numbers were the most
                      prominent thing under the field's name. */}
                  {data.field.area_acres
                    ? t('{n} acres', { n: data.field.area_acres })
                    : t('Area not added')}
                </div>
              </div>

              {/* Every crop in the ground, each with its own stage. A holding
                  carrying maize and paddy has two different answers, and
                  showing one of them would be worse than showing neither. */}
              {(data.crops_growing?.length ?? 0) > 0 && (
                <div>
                  <div className="text-[13px] font-medium mb-1.5">{t('Growing now')}</div>
                  <div className="space-y-1.5">
                    {data.crops_growing!.map((c, i) => (
                      <div key={i} className="rounded-lg px-2 py-1.5"
                           style={{ background: 'var(--bg-sunken)' }}>
                        <div className="text-[14px] font-medium">
                          {t(c.name || c.crop.replace(/_/g, ' '))}
                        </div>
                        <div className="text-[12px]" style={{ color: 'var(--text-muted)' }}>
                          {c.days_after_sowing != null
                            ? t('day {n}', { n: c.days_after_sowing })
                            : t('sowing date unknown')}
                          {c.growth_stage ? ` · ${t(c.growth_stage)}` : ''}
                          {c.days_to_harvest != null
                            ? ` · ${t('about {n} days to harvest', { n: c.days_to_harvest })}`
                            : ''}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* When they last watered, in their own units. */}
              {data.last_irrigation && (
                <div>
                  <div className="text-[13px] font-medium mb-1">{t('Last watered')}</div>
                  <div className="text-[15px]">
                    {data.last_irrigation.days_ago === 0 ? t('Today')
                      : data.last_irrigation.days_ago === 1 ? t('Yesterday')
                      : t('{n} days ago', { n: data.last_irrigation.days_ago ?? '' })}
                  </div>
                  <div className="text-[13px]" style={{ color: 'var(--text-muted)' }}>
                    {data.last_irrigation.date}
                    {data.last_irrigation.hours_pumped
                      ? ` · ${t('{n} hours of pumping', { n: data.last_irrigation.hours_pumped })}`
                      : ''}
                  </div>
                </div>
              )}

              {/* Weather */}
              {data.weather && (
                <div>
                  <div className="text-[13px] font-medium mb-1.5">{t('Weather')}</div>
                  {data.weather.today && (
                    <div className="text-[15px]">
                      {Math.round(data.weather.today.t_max_c)}° /{' '}
                      {Math.round(data.weather.today.t_min_c)}°
                    </div>
                  )}
                  <div className="text-[13px]" style={{ color: 'var(--text-muted)' }}>
                    {data.weather.rain_next_7_days_mm
                      ? t('{n} mm rain expected this week', { n: data.weather.rain_next_7_days_mm })
                      : t('No rain expected this week')}
                  </div>
                  {/* Seven bars told you rain was coming and not which day,
                      which is the only part a farmer plans around. Day and
                      amount now sit under each bar; the hover title was no
                      use on a phone, where there is no hover. */}
                  <div className="flex gap-1 items-end mt-2">
                    {data.weather.forecast.map((d: any, i: number) => {
                      const max = Math.max(
                        1, ...data.weather!.forecast.map((x: any) => x.rain_mm || 0))
                      const mm = d.rain_mm || 0
                      const day = new Date(d.date).toLocaleDateString(
                        uiLocale(), { weekday: 'short' })
                      return (
                        <div key={i} className="flex-1 flex flex-col items-center gap-1">
                          <div className="w-full flex flex-col justify-end h-10">
                            <div className="rounded-t"
                                 style={{
                                   height: `${Math.max(2, (mm / max) * 36)}px`,
                                   background: mm > 0 ? 'var(--accent)' : 'var(--border)',
                                 }} />
                          </div>
                          <div className="text-[10px] leading-none"
                               style={{ color: 'var(--text-muted)' }}>{day}</div>
                          <div className="text-[10px] leading-none"
                               style={{ color: mm > 0 ? 'var(--accent)' : 'transparent' }}>
                            {mm > 0 ? mm : '0'}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Soil */}
              {data.soil && (
                <div>
                  <div className="text-[13px] font-medium mb-1.5">{t('Soil')}</div>
                  <div className="text-[15px]">
                    {t(data.soil.texture.replace(/_/g, ' '))}
                  </div>
                  <div className="text-[13px]" style={{ color: 'var(--text-muted)' }}>
                    {data.soil.ph != null && (
                      <>pH {data.soil.ph}
                        {data.soil.ph_class
                          ? ` — ${t(PH_WORD[data.soil.ph_class] || data.soil.ph_class)}`
                          : ''}<br /></>
                    )}
                    {data.soil.available_water_mm_per_m != null && (
                      <>{t('Holds {n} mm of water per metre', { n: data.soil.available_water_mm_per_m })}</>
                    )}
                  </div>
                  {data.soil.confidence === 'low' && (
                    <div className="text-[12px] mt-1" style={{ color: '#c2703d' }}>
                      {t('Soil map uncertain here — a KVK soil test would be firmer.')}
                    </div>
                  )}
                </div>
              )}

              {/* What the farmer told us, labelled as theirs. Where their
                  account of the soil disagrees with the raster, both are
                  shown -- they have dug that field and the raster has not. */}
              {(data.farmer_said?.length ?? 0) > 0 && (
                <div>
                  <div className="text-[13px] font-medium mb-1.5">{t('Field details')}</div>
                  <div className="space-y-1">
                    {data.farmer_said!.map((n, i) => (
                      <div key={i} className="text-[13px]"
                           style={{ color: 'var(--text-muted)' }}>
                        “{n.said}”
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* What is still unknown, phrased as an invitation rather than
                  a form. Tapping one asks the question conversationally. */}
              {(data.missing?.length ?? 0) > 0 && (
                <div>
                  <div className="text-[13px] font-medium mb-1.5">
                    {t('Help Saathi advise better')}
                  </div>
                  {/* Tappable, not a label.
                      
                      These were dead text, and one of them -- the sowing
                      date -- is what the water balance needs before it can
                      say anything about irrigating at all. A farmer looking
                      at "when it was sown" in orange had no way to act on it
                      and no idea it was the reason no advice appeared.
                      Tapping now asks the question in the conversation,
                      where it can be answered by voice. */}
                  <div className="space-y-1">
                    {data.missing!.map((m, i) => (
                      <button key={i}
                              onClick={() => onAsk(MISSING_PROMPT[m]
                                ? t(MISSING_PROMPT[m]) : t('Let me add {what}', { what: t(m) }))}
                              className="w-full text-left text-[13px] rounded-lg px-2 py-2"
                              style={{ background: 'var(--bg-raised)', color: '#c2703d' }}>
                        + {t(m)}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Shortcuts phrased as questions, so tapping one teaches what
                  can be asked rather than hiding features behind buttons.
 
                  Which questions appear depends on what the field knows,
                  because a shortcut that cannot be answered is worse than no
                  shortcut: it spends a farmer's tap to be told no. The panel
                  was offering the mandi rate to a field with nothing planted,
                  while the panel directly above it said "what is planted" was
                  missing -- and get_mandi_prices abstains outright without a
                  crop. So a field with no crop is asked what to sow instead,
                  which is answerable from soil and climate alone and is the
                  question that actually moves that farmer forward.
 
                  The satellite question survives without a sowing date on
                  purpose: get_crop_health still returns the NDVI history and
                  only withholds the on-track verdict, so it stays useful. */}
              <div>
                <div className="text-[13px] font-medium mb-1.5">{t('Ask about')}</div>
                <div className="space-y-1">
                  {(() => {
                    // Each literal sits inside t() rather than being mapped
                    // through it afterwards. The translation extractor reads
                    // the source for t('...') calls, so a string reached any
                    // other way is never collected and ships in English --
                    // which is what had happened to all three of these.
                    const hasCrop = (data.crops_growing?.length ?? 0) > 0
                    const questions = hasCrop
                      ? [t('How does my crop look from the satellite?'),
                         t('What is the rate at my mandi today?')]
                      : [t('What should I sow this season?')]
                    if (data.soil) questions.push(t('How can I improve my soil?'))
                    return questions
                  })().map((q) => (
                    <button key={q} onClick={() => onAsk(q)}
                            className="w-full text-left text-[13px] rounded-lg px-2 py-2"
                            style={{ background: 'var(--bg-sunken)' }}>
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      </aside>
    </>
  )
}
