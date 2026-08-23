/**
 * Inline result cards.
 *
 * These are the platform's answer to "dashboards, maps and analytics" without
 * becoming a dashboard. A card appears inside the conversation, at the moment
 * a tool produced something worth seeing, and nowhere else. There is no home
 * screen of tiles to learn, no navigation, nothing to configure.
 *
 * Every card follows the same rule: **the headline is the decision, not the
 * data.** A farmer sees "No water needed this week" in large type; the
 * millimetres, the growth stage and the soil moisture sit underneath in
 * smaller type for whoever wants them. Reversing that -- leading with a
 * number and making the reader infer the decision -- is the single most
 * common failure of agricultural dashboards.
 */

import { useState } from 'react'

/* ------------------------------------------------------------------ */
/* Pictograms                                                          */
/* ------------------------------------------------------------------ */

/**
 * A small icon vocabulary for readers who cannot read.
 *
 * These are composed left-to-right into a sentence-like strip:
 *   [state] -> [duration] -> [action] -> [quantity]
 * e.g. dry-soil -> 3 days -> watering-can -> 40mm
 *
 * The grammar matters more than the drawings: a fixed slot order means a
 * farmer learns the pattern once and can read every subsequent advisory,
 * even a kind they have not seen before. Icons carry an aria-label so the
 * screen reader and the text-to-speech path stay in sync with the visual.
 */
export function Picto({ kind, label }: { kind: string; label: string }) {
  const common = {
    width: 34, height: 34, viewBox: '0 0 24 24', fill: 'none',
    stroke: 'currentColor', strokeWidth: 1.7,
    strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const,
    role: 'img' as const, 'aria-label': label,
  }
  switch (kind) {
    case 'sun':
      return <svg {...common}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4" /></svg>
    case 'rain':
      return <svg {...common}><path d="M17 16a4 4 0 0 0 0-8 5.5 5.5 0 0 0-10.7 1.5A3.5 3.5 0 0 0 6.5 16z" /><path d="M8 19l-1 2M12 19l-1 2M16 19l-1 2" /></svg>
    case 'water':
      return <svg {...common}><path d="M12 3s5.5 6 5.5 9.5a5.5 5.5 0 1 1-11 0C6.5 9 12 3 12 3z" /></svg>
    case 'no-water':
      return <svg {...common}><path d="M12 3s5.5 6 5.5 9.5a5.5 5.5 0 1 1-11 0C6.5 9 12 3 12 3z" /><path d="M4 4l16 16" /></svg>
    case 'dry-soil':
      return <svg {...common}><path d="M3 16h18M3 20h18" /><path d="M7 16V9M12 16V7M17 16v-5" /></svg>
    case 'seed':
      return <svg {...common}><path d="M12 21V11" /><path d="M12 11c0-4 3-7 7-7 0 4-3 7-7 7z" /><path d="M12 14c0-3-2.5-5-5.5-5 0 3 2.5 5 5.5 5z" /></svg>
    case 'calendar':
      return <svg {...common}><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4M16 3v4" /></svg>
    case 'warning':
      return <svg {...common}><path d="M12 4l9 16H3z" /><path d="M12 10v4M12 17.5v.5" /></svg>
    case 'leaf':
      return <svg {...common}><path d="M4 20C4 10 12 4 20 4c0 9-6 16-16 16z" /><path d="M4 20c4-6 8-9 12-11" /></svg>
    default:
      return null
  }
}

/** A pictogram strip: the icon sentence, with words beneath for readers. */
export function PictoStrip({ steps }: { steps: { kind: string; label: string }[] }) {
  return (
    <div className="flex items-center gap-1 flex-wrap py-1">
      {steps.map((s, i) => (
        <div key={i} className="flex items-center gap-1">
          <div className="flex flex-col items-center gap-0.5 min-w-[58px]">
            <span style={{ color: 'var(--accent)' }}><Picto kind={s.kind} label={s.label} /></span>
            <span className="text-[11px] text-center leading-tight"
                  style={{ color: 'var(--text-muted)' }}>{s.label}</span>
          </div>
          {i < steps.length - 1 && (
            <span aria-hidden className="text-lg opacity-30 mb-4">→</span>
          )}
        </div>
      ))}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Shell                                                               */
/* ------------------------------------------------------------------ */

function Card({ children, tone = 'neutral' }: {
  children: React.ReactNode; tone?: 'neutral' | 'good' | 'warn' | 'alert'
}) {
  const border =
    tone === 'good' ? 'var(--accent)'
    : tone === 'warn' ? '#c2703d'
    : tone === 'alert' ? '#c2452d'
    : 'var(--border)'
  return (
    <div className="animate-in rounded-2xl border overflow-hidden my-3"
         style={{ background: 'var(--bg-raised)', borderColor: border, borderLeftWidth: 4 }}>
      <div className="p-4">{children}</div>
    </div>
  )
}

function Headline({ children }: { children: React.ReactNode }) {
  return <div className="text-xl font-semibold leading-snug mb-1">{children}</div>
}

function Detail({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-1 text-[15px]">
      <span style={{ color: 'var(--text-muted)' }}>{label}</span>
      <span className="font-medium text-right">{value}</span>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Irrigation                                                          */
/* ------------------------------------------------------------------ */

const VERDICT_COPY: Record<string, { head: string; tone: 'good' | 'warn' | 'alert' }> = {
  irrigate_now:          { head: 'Water your field today', tone: 'alert' },
  irrigate_in_days:      { head: 'Water soon',             tone: 'warn' },
  wait_for_rain:         { head: 'Wait — rain is coming',  tone: 'good' },
  no_irrigation_needed:  { head: 'No water needed',        tone: 'good' },
  insufficient_data:     { head: 'Not enough information', tone: 'warn' },
}

export function IrrigationCard({ d }: { d: any }) {
  const copy = VERDICT_COPY[d.verdict] ?? VERDICT_COPY.insufficient_data
  // Millimetres mean nothing to most farmers. An inch of water and an hour of
  // pumping do. Both are shown; the familiar unit leads.
  const inches = d.gross_depth_mm ? (d.gross_depth_mm / 25.4).toFixed(1) : null

  const steps = d.verdict === 'wait_for_rain' || d.verdict === 'no_irrigation_needed'
    ? [{ kind: 'rain', label: 'Rain coming' }, { kind: 'no-water', label: 'No pump' }]
    : [
        { kind: 'dry-soil', label: 'Soil drying' },
        { kind: 'calendar', label: d.days_until_stress ? `${d.days_until_stress} days` : 'Now' },
        { kind: 'water', label: 'Irrigate' },
        { kind: 'sun', label: inches ? `${inches} inch` : `${d.gross_depth_mm} mm` },
      ]

  return (
    <Card tone={copy.tone}>
      <Headline>{copy.head}</Headline>
      <PictoStrip steps={steps} />
      <div className="mt-2 pt-2 border-t" style={{ borderColor: 'var(--border)' }}>
        {d.crop_name && <Detail label="Crop" value={`${d.crop_name} · ${String(d.growth_stage || '').replace('_', ' ')}`} />}
        <Detail label="Water in the soil now" value={`${d.soil_moisture_percent}%`} />
        {d.gross_depth_mm > 0 && (
          <Detail label="Water to apply"
                  value={<>{inches} inch <span style={{ color: 'var(--text-muted)' }}>({d.gross_depth_mm} mm)</span></>} />
        )}
        {d.forecast_effective_rain_mm > 0 && (
          <Detail label="Rain expected (7 days)" value={`${d.forecast_effective_rain_mm} mm`} />
        )}
      </div>
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/* Weather                                                             */
/* ------------------------------------------------------------------ */

export function WeatherCard({ d }: { d: any }) {
  const days: any[] = d.days || []
  const maxRain = Math.max(1, ...days.map((x) => x.rain_mm || 0))
  const fmt = (iso: string) =>
    new Date(iso).toLocaleDateString(undefined, { weekday: 'short' })

  return (
    <Card tone={d.rain_next_7_days_mm > 10 ? 'good' : 'neutral'}>
      <Headline>
        {d.rain_next_7_days_mm > 0
          ? `${d.rain_next_7_days_mm} mm rain expected this week`
          : 'No rain expected this week'}
      </Headline>
      <div className="flex gap-1 items-end mt-3 overflow-x-auto pb-1">
        {days.map((day, i) => (
          <div key={i} className="flex flex-col items-center gap-1 min-w-[42px]">
            <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
              {day.rain_mm > 0 ? `${Math.round(day.rain_mm)}` : ''}
            </span>
            <div className="w-6 rounded-t"
                 style={{
                   height: `${Math.max(3, ((day.rain_mm || 0) / maxRain) * 56)}px`,
                   background: day.rain_mm > 0 ? 'var(--accent)' : 'var(--border)',
                 }} />
            <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
              {fmt(day.date)}
            </span>
            <span className="text-[11px] font-medium">{Math.round(day.t_max_c)}°</span>
          </div>
        ))}
      </div>
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/* Soil                                                                */
/* ------------------------------------------------------------------ */

const PH_WORD: Record<string, string> = {
  strongly_acidic: 'very sour (acidic)',
  slightly_acidic: 'slightly sour',
  neutral: 'balanced',
  alkaline: 'slightly salty (alkaline)',
  strongly_alkaline: 'very salty (alkaline)',
}

export function SoilCard({ d }: { d: any }) {
  const t = d.texture || {}, c = d.chemistry || {}, w = d.water_holding || {}
  return (
    <Card tone={d.confidence === 'low' ? 'warn' : 'neutral'}>
      <Headline>Your soil is {String(t.usda_class || '').replace('_', ' ')}</Headline>
      {c.ph != null && (
        <div className="text-[15px] mb-2" style={{ color: 'var(--text-muted)' }}>
          pH {c.ph} — {PH_WORD[c.ph_class] || c.ph_class}
        </div>
      )}
      {/* Texture bar: sand / silt / clay proportions, read at a glance. */}
      <div className="flex h-3 rounded-full overflow-hidden my-3">
        <div style={{ width: `${t.sand_percent}%`, background: '#d0bc9c' }} title={`Sand ${t.sand_percent}%`} />
        <div style={{ width: `${t.silt_percent}%`, background: '#a89070' }} title={`Silt ${t.silt_percent}%`} />
        <div style={{ width: `${t.clay_percent}%`, background: '#7a6244' }} title={`Clay ${t.clay_percent}%`} />
      </div>
      <div className="flex justify-between text-[12px] mb-3" style={{ color: 'var(--text-muted)' }}>
        <span>Sand {t.sand_percent}%</span><span>Silt {t.silt_percent}%</span><span>Clay {t.clay_percent}%</span>
      </div>
      <Detail label="Water the soil can hold" value={`${w.available_water_mm_per_m} mm per metre`} />
      {c.organic_carbon_g_per_kg != null && (
        <Detail label="Organic carbon" value={`${c.organic_carbon_g_per_kg} g/kg`} />
      )}
      {d.confidence === 'low' && (
        <div className="mt-3 text-[13px] rounded-lg p-2"
             style={{ background: 'var(--bg-sunken)', color: 'var(--text-muted)' }}>
          The soil map is uncertain here. A soil test from your nearest KVK
          would give you a firmer answer.
        </div>
      )}
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/* Crop suitability                                                    */
/* ------------------------------------------------------------------ */

export function SuitabilityCard({ d }: { d: any }) {
  const list: any[] = d.assessments || []
  return (
    <Card>
      <Headline>Crops that suit your land</Headline>
      <div className="mt-2 space-y-2">
        {list.map((a, i) => (
          <div key={i} className="rounded-xl p-3" style={{ background: 'var(--bg-sunken)' }}>
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium">{a.name}</span>
              <span className="text-[13px] px-2 py-0.5 rounded-full"
                    style={{
                      background: a.rainfed_viable ? 'var(--accent-soft)' : 'transparent',
                      color: a.rainfed_viable ? 'var(--accent)' : 'var(--text-muted)',
                      border: a.rainfed_viable ? 'none' : '1px solid var(--border)',
                    }}>
                {a.rainfed_viable ? 'grows on rain alone' : 'needs irrigation'}
              </span>
            </div>
            {a.constraints?.[0] && (
              <div className="text-[13px] mt-1" style={{ color: 'var(--text-muted)' }}>
                {a.constraints[0]}
              </div>
            )}
          </div>
        ))}
      </div>
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/* Soil carbon                                                         */
/* ------------------------------------------------------------------ */

export function CarbonCard({ d }: { d: any }) {
  const scenarios = d.scenarios || {}
  const keys = Object.keys(scenarios)
  const values = keys.map((k) => scenarios[k].final_soc_t_per_ha)
  const lo = Math.min(...values), hi = Math.max(...values)
  const span = Math.max(0.001, hi - lo)

  return (
    <Card tone="good">
      <Headline>What different practices do to your soil</Headline>
      <div className="text-[14px] mb-3" style={{ color: 'var(--text-muted)' }}>
        Over {d.years_projected} years, starting from {d.initial_soc_t_per_ha} tonnes
        of carbon per hectare
      </div>
      <div className="space-y-2">
        {keys.map((k) => {
          const s = scenarios[k]
          const pct = ((s.final_soc_t_per_ha - lo) / span) * 100
          const best = k === d.best_scenario
          return (
            <div key={k}>
              <div className="flex justify-between text-[14px] mb-1">
                <span style={{ fontWeight: best ? 600 : 400 }}>{s.label}</span>
                <span style={{ color: s.change_t_per_ha >= 0 ? 'var(--accent)' : '#c2452d' }}>
                  {s.change_t_per_ha >= 0 ? '+' : ''}{s.change_t_per_ha} t C/ha
                </span>
              </div>
              <div className="h-2 rounded-full" style={{ background: 'var(--bg-sunken)' }}>
                <div className="h-2 rounded-full"
                     style={{ width: `${Math.max(4, pct)}%`,
                              background: best ? 'var(--accent)' : 'var(--border)' }} />
              </div>
            </div>
          )
        })}
      </div>
      {d.gain_over_burning_t_co2e_per_ha != null && (
        <div className="mt-3 text-[13px] rounded-lg p-2"
             style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}>
          Best practice holds {d.gain_over_burning_t_co2e_per_ha} tonnes more
          CO₂ per hectare than burning the residue.
        </div>
      )}
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/* Evidence ledger                                                     */
/* ------------------------------------------------------------------ */

/**
 * Provenance for every claim in the answer.
 *
 * Collapsed by default -- a farmer asking whether to irrigate does not want a
 * citation list. But it is always one tap away, and it names the actual
 * dataset, resolution, licence and method rather than saying "AI-powered".
 * The displacement note is here too: if the soil reading came from 2 km away
 * because the pin fell on a village, that is disclosed rather than hidden.
 */
export function EvidenceLedger({ entries }: { entries: any[] }) {
  const [open, setOpen] = useState(false)
  if (!entries?.length) return null

  return (
    <div className="mt-2">
      <button onClick={() => setOpen(!open)}
              className="text-[13px] underline underline-offset-2 px-0"
              style={{ color: 'var(--text-muted)', minHeight: 0 }}>
        {open ? 'Hide' : 'Where did this come from?'}
      </button>
      {open && (
        <div className="mt-2 rounded-xl p-3 text-[13px] space-y-3"
             style={{ background: 'var(--bg-sunken)', color: 'var(--text-muted)' }}>
          {entries.map((e, i) => {
            const ev = e.evidence || {}
            return (
              <div key={i}>
                <div className="font-medium" style={{ color: 'var(--text)' }}>
                  {e.tool.replace(/_/g, ' ')}
                </div>
                {ev.source && <div>Source: {ev.source} ({ev.licence})</div>}
                {ev.soil?.source && <div>Soil: {ev.soil.source} — {ev.soil.resolution_m} m grid</div>}
                {ev.weather?.source && <div>Weather: {ev.weather.source}, {ev.weather.days_returned} days</div>}
                {ev.method && <div>Method: {ev.method}</div>}
                {ev.displacement_note && (
                  <div style={{ color: '#c2703d' }}>{ev.displacement_note}</div>
                )}
                {ev.soil?.displacement_note && (
                  <div style={{ color: '#c2703d' }}>{ev.soil.displacement_note}</div>
                )}
                {ev.assumptions?.length > 0 && (
                  <details className="mt-1">
                    <summary className="cursor-pointer">Assumptions made</summary>
                    <ul className="list-disc ml-4 mt-1">
                      {ev.assumptions.map((a: string, j: number) => <li key={j}>{a}</li>)}
                    </ul>
                  </details>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

/** Dispatch a card payload to its renderer. */
export function RenderCard({ card }: { card: any }) {
  switch (card.card) {
    case 'irrigation':  return <IrrigationCard d={card} />
    case 'weather':     return <WeatherCard d={card} />
    case 'soil':        return <SoilCard d={card} />
    case 'suitability': return <SuitabilityCard d={card} />
    case 'carbon':      return <CarbonCard d={card} />
    default: return null
  }
}
