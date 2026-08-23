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

interface Summary {
  field: { id: string; name: string | null; latitude: number; longitude: number }
  season: { crop: string; sowing_date: string | null } | null
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

const PH_WORD: Record<string, string> = {
  strongly_acidic: 'very sour', slightly_acidic: 'slightly sour',
  neutral: 'balanced', alkaline: 'slightly salty',
  strongly_alkaline: 'very salty',
}

export function FieldPanel({
  fieldId, open, onClose, onAsk,
}: {
  fieldId: string | null
  open: boolean
  onClose: () => void
  onAsk: (q: string) => void
}) {
  const [data, setData] = useState<Summary | null>(null)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)

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
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
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
  }, [fieldId, open])

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

      <aside
        className={`fixed md:static right-0 top-0 h-full z-20 overflow-y-auto
                    border-l transition-transform duration-200
                    ${open ? 'translate-x-0' : 'translate-x-full md:hidden'}`}
        style={{
          width: 300, maxWidth: '85vw',
          background: 'var(--bg-raised)', borderColor: 'var(--border)',
        }}
      >
        <div className="p-4">
          <div className="flex items-center justify-between mb-3">
            <span className="font-semibold">Your field</span>
            <button onClick={onClose}
                    aria-label="Close field panel"
                    className="text-[20px] leading-none px-2"
                    style={{ color: 'var(--text-muted)', minHeight: 0 }}>
              ×
            </button>
          </div>

          {loading && (
            <div className="text-[14px]" style={{ color: 'var(--text-muted)' }}>
              Checking your field…
            </div>
          )}

          {failed && (
            <div className="text-[14px]" style={{ color: 'var(--text-muted)' }}>
              Could not load your field just now. Ask me directly instead.
            </div>
          )}

          {data && !loading && (
            <div className="space-y-4">
              {/* Location and crop */}
              <div>
                <div className="text-[15px] font-medium">
                  {data.field.name || 'My field'}
                </div>
                <div className="text-[13px]" style={{ color: 'var(--text-muted)' }}>
                  {data.field.latitude.toFixed(3)}, {data.field.longitude.toFixed(3)}
                </div>
                {data.season?.crop && (
                  <div className="text-[13px] mt-1" style={{ color: 'var(--text-muted)' }}>
                    Growing {data.season.crop.replace(/_/g, ' ')}
                    {data.irrigation
                      ? ` · day ${data.irrigation.days_after_sowing}`
                      : ''}
                  </div>
                )}
              </div>

              {/* Water: the reason most farmers open the app */}
              {irrigationLoading && !data.irrigation && (
                <div className="rounded-xl p-3 border text-[14px]"
                     style={{ borderColor: 'var(--border)', background: 'var(--bg-sunken)',
                              color: 'var(--text-muted)' }}>
                  Working out whether your field needs water…
                </div>
              )}
              {verdict && data.irrigation && (
                <button
                  onClick={() => onAsk('Does my field need water this week?')}
                  className="w-full text-left rounded-xl p-3 border"
                  style={{ borderColor: verdict.tone, background: 'var(--bg-sunken)' }}
                >
                  <div className="text-[15px] font-medium" style={{ color: verdict.tone }}>
                    {verdict.text}
                  </div>
                  <div className="text-[13px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
                    Soil holding {data.irrigation.soil_moisture_percent}% of its water
                    {data.irrigation.days_until_stress != null
                      ? ` · ${data.irrigation.days_until_stress} day${
                          data.irrigation.days_until_stress === 1 ? '' : 's'
                        } to stress`
                      : ''}
                  </div>
                </button>
              )}

              {/* Weather */}
              {data.weather && (
                <div>
                  <div className="text-[13px] font-medium mb-1.5">Weather</div>
                  {data.weather.today && (
                    <div className="text-[15px]">
                      {Math.round(data.weather.today.t_max_c)}° /{' '}
                      {Math.round(data.weather.today.t_min_c)}°
                    </div>
                  )}
                  <div className="text-[13px]" style={{ color: 'var(--text-muted)' }}>
                    {data.weather.rain_next_7_days_mm
                      ? `${data.weather.rain_next_7_days_mm} mm rain expected this week`
                      : 'No rain expected this week'}
                  </div>
                  {/* Seven-day rain bars: small, glanceable, no legend needed. */}
                  <div className="flex gap-1 items-end mt-2 h-10">
                    {data.weather.forecast.map((d: any, i: number) => {
                      const max = Math.max(
                        1, ...data.weather!.forecast.map((x: any) => x.rain_mm || 0))
                      return (
                        <div key={i} className="flex-1 flex flex-col justify-end"
                             title={`${d.date}: ${d.rain_mm ?? 0} mm`}>
                          <div className="rounded-t"
                               style={{
                                 height: `${Math.max(2, ((d.rain_mm || 0) / max) * 36)}px`,
                                 background: d.rain_mm > 0 ? 'var(--accent)' : 'var(--border)',
                               }} />
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Soil */}
              {data.soil && (
                <div>
                  <div className="text-[13px] font-medium mb-1.5">Soil</div>
                  <div className="text-[15px]">
                    {data.soil.texture.replace(/_/g, ' ')}
                  </div>
                  <div className="text-[13px]" style={{ color: 'var(--text-muted)' }}>
                    {data.soil.ph != null && (
                      <>pH {data.soil.ph}
                        {data.soil.ph_class
                          ? ` — ${PH_WORD[data.soil.ph_class] || data.soil.ph_class}`
                          : ''}<br /></>
                    )}
                    {data.soil.available_water_mm_per_m != null && (
                      <>Holds {data.soil.available_water_mm_per_m} mm of water per metre</>
                    )}
                  </div>
                  {data.soil.confidence === 'low' && (
                    <div className="text-[12px] mt-1" style={{ color: '#c2703d' }}>
                      Soil map uncertain here — a KVK soil test would be firmer.
                    </div>
                  )}
                </div>
              )}

              {/* Shortcuts phrased as questions, so tapping one teaches what
                  can be asked rather than hiding features behind buttons. */}
              <div>
                <div className="text-[13px] font-medium mb-1.5">Ask about</div>
                <div className="space-y-1">
                  {[
                    'How does my crop look from the satellite?',
                    'What is the rate at my mandi today?',
                    'How can I improve my soil?',
                  ].map((q) => (
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
