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
import { useT, uiLocale } from '../lib/i18n'

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
  const t = useT()
  const copy = VERDICT_COPY[d.verdict] ?? VERDICT_COPY.insufficient_data
  // Millimetres mean nothing to most farmers. An inch of water and an hour of
  // pumping do. Both are shown; the familiar unit leads.
  const inches = d.gross_depth_mm ? (d.gross_depth_mm / 25.4).toFixed(1) : null

  const needsWater = d.verdict === 'irrigate_now' || d.verdict === 'irrigate_in_days'

  const steps = d.verdict === 'wait_for_rain' || d.verdict === 'no_irrigation_needed'
    ? [{ kind: 'rain', label: t('Rain coming') }, { kind: 'no-water', label: t('No pump') }]
    : [
        { kind: 'dry-soil', label: t('Soil drying') },
        { kind: 'calendar', label: !d.days_until_stress || d.days_until_stress <= 0 ? t('Now')
            : d.days_until_stress === 1 ? t('1 day') : t('{n} days', { n: d.days_until_stress }) },
        { kind: 'water', label: t('Irrigate') },
        { kind: 'sun', label: inches ? t('{n} inch', { n: inches }) : `${d.gross_depth_mm} mm` },
      ]

  return (
    <Card tone={copy.tone}>
      <Headline>{t(copy.head)}</Headline>
      <PictoStrip steps={steps} />
      <div className="mt-2 pt-2 border-t" style={{ borderColor: 'var(--border)' }}>
        {d.crop_name && <Detail label={t('Crop')} value={`${t(d.crop_name)} · ${t(String(d.growth_stage || '').replace('_', ' '))}`} />}
        <Detail label={t('Water in the soil now')} value={`${d.soil_moisture_percent}%`} />
        {/* Only when the answer is actually to water.
            
            The depth is computed either way -- it is what a full irrigation
            would need, not a recommendation -- and printing it regardless put
            "Water to apply: 0.5 inch" directly beneath "No water needed" and
            "No pump". A farmer skimming the card could irrigate a field that
            did not need it, which is the one outcome this card exists to
            prevent. */}
        {needsWater && d.gross_depth_mm > 0 && (
          <Detail label={t('Water to apply')}
                  value={<>{t('{n} inch', { n: inches ?? '' })} <span style={{ color: 'var(--text-muted)' }}>({d.gross_depth_mm} mm)</span></>} />
        )}
        {d.forecast_effective_rain_mm > 0 && (
          <Detail label={t('Rain expected (7 days)')} value={`${d.forecast_effective_rain_mm} mm`} />
        )}
      </div>
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/* Weather                                                             */
/* ------------------------------------------------------------------ */

export function WeatherCard({ d }: { d: any }) {
  const t = useT()
  const days: any[] = d.days || []
  const maxRain = Math.max(1, ...days.map((x) => x.rain_mm || 0))
  const fmt = (iso: string) =>
    new Date(iso).toLocaleDateString(uiLocale(), { weekday: 'short' })

  return (
    <Card tone={d.rain_next_7_days_mm > 10 ? 'good' : 'neutral'}>
      <Headline>
        {d.rain_next_7_days_mm > 0
          ? t('{n} mm rain expected this week', { n: d.rain_next_7_days_mm })
          : t('No rain expected this week')}
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
  const t = useT()
  const tex = d.texture || {}, c = d.chemistry || {}, w = d.water_holding || {}
  return (
    <Card tone={d.confidence === 'low' ? 'warn' : 'neutral'}>
      <Headline>{t('Your soil is {x}', { x: t(String(tex.usda_class || '').replace('_', ' ')) })}</Headline>
      {c.ph != null && (
        <div className="text-[15px] mb-2" style={{ color: 'var(--text-muted)' }}>
          pH {c.ph} — {t(PH_WORD[c.ph_class] || c.ph_class)}
        </div>
      )}
      {/* Texture bar: sand / silt / clay proportions, read at a glance. */}
      <div className="flex h-3 rounded-full overflow-hidden my-3">
        <div style={{ width: `${tex.sand_percent}%`, background: '#d0bc9c' }} title={`Sand ${tex.sand_percent}%`} />
        <div style={{ width: `${tex.silt_percent}%`, background: '#a89070' }} title={`Silt ${tex.silt_percent}%`} />
        <div style={{ width: `${tex.clay_percent}%`, background: '#7a6244' }} title={`Clay ${tex.clay_percent}%`} />
      </div>
      <div className="flex justify-between text-[12px] mb-3" style={{ color: 'var(--text-muted)' }}>
        <span>{t('Sand')} {tex.sand_percent}%</span><span>{t('Silt')} {tex.silt_percent}%</span><span>{t('Clay')} {tex.clay_percent}%</span>
      </div>
      <Detail label={t('Water the soil can hold')} value={t('{n} mm per metre', { n: w.available_water_mm_per_m })} />
      {c.organic_carbon_g_per_kg != null && (
        <Detail label={t('Organic carbon')} value={`${c.organic_carbon_g_per_kg} g/kg`} />
      )}
      {d.confidence === 'low' && (
        <div className="mt-3 text-[13px] rounded-lg p-2"
             style={{ background: 'var(--bg-sunken)', color: 'var(--text-muted)' }}>
          {t('The soil map is uncertain here. A soil test from your nearest KVK would give you a firmer answer.')}
        </div>
      )}
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/* Crop suitability                                                    */
/* ------------------------------------------------------------------ */

export function SuitabilityCard({ d }: { d: any }) {
  const t = useT()
  const list: any[] = d.assessments || []
  return (
    <Card>
      <Headline>{t('Crops that suit your land')}</Headline>
      <div className="mt-2 space-y-2">
        {list.map((a, i) => (
          <div key={i} className="rounded-xl p-3" style={{ background: 'var(--bg-sunken)' }}>
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium">{t(a.name)}</span>
              <span className="text-[13px] px-2 py-0.5 rounded-full"
                    style={{
                      background: a.rainfed_viable ? 'var(--accent-soft)' : 'transparent',
                      color: a.rainfed_viable ? 'var(--accent)' : 'var(--text-muted)',
                      border: a.rainfed_viable ? 'none' : '1px solid var(--border)',
                    }}>
                {a.rainfed_viable ? t('grows on rain alone') : t('needs irrigation')}
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
  const t = useT()
  const scenarios = d.scenarios || {}
  const keys = Object.keys(scenarios)
  const values = keys.map((k) => scenarios[k].final_soc_t_per_ha)
  const lo = Math.min(...values), hi = Math.max(...values)
  const span = Math.max(0.001, hi - lo)

  return (
    <Card tone="good">
      <Headline>{t('What different practices do to your soil')}</Headline>
      <div className="text-[14px] mb-3" style={{ color: 'var(--text-muted)' }}>
        {t('Over {y} years, starting from {c} tonnes of carbon per hectare', { y: d.years_projected, c: d.initial_soc_t_per_ha })}
      </div>
      <div className="space-y-2">
        {keys.map((k) => {
          const s = scenarios[k]
          const pct = ((s.final_soc_t_per_ha - lo) / span) * 100
          const best = k === d.best_scenario
          return (
            <div key={k}>
              <div className="flex justify-between text-[14px] mb-1">
                <span style={{ fontWeight: best ? 600 : 400 }}>{t(s.label)}</span>
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
          {t('Best practice holds {n} tonnes more CO₂ per hectare than burning the residue.', { n: d.gain_over_burning_t_co2e_per_ha })}
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
  const t = useT()
  const [open, setOpen] = useState(false)
  if (!entries?.length) return null

  return (
    <div className="mt-2">
      <button onClick={() => setOpen(!open)}
              className="text-[13px] underline underline-offset-2 px-0"
              style={{ color: 'var(--text-muted)', minHeight: 0 }}>
        {open ? t('Hide') : t('Where did this come from?')}
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
                    <summary className="cursor-pointer">{t('Assumptions made')}</summary>
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


/* ------------------------------------------------------------------ */
/* Disease diagnosis                                                   */
/* ------------------------------------------------------------------ */

const CONF_TONE: Record<string, string> = {
  high: 'var(--accent)', moderate: '#c2703d', low: 'var(--text-muted)',
}

type Tone = 'neutral' | 'good' | 'warn' | 'alert'

const URGENCY_COPY: Record<string, { text: string; tone: Tone }> = {
  today:     { text: 'Act today',         tone: 'alert'   },
  this_week: { text: 'Act this week',     tone: 'warn'    },
  monitor:   { text: 'Watch it',          tone: 'neutral' },
  no_action: { text: 'Nothing to do yet', tone: 'good'    },
}

export function DiagnosisCard({ d, imageUrl }: { d: any; imageUrl?: string }) {
  const t = useT()
  // An unusable photo is not a failure to hide -- it is the most useful
  // thing we can say, because it tells the farmer exactly how to get an
  // answer on the next try.
  if (!d.image_usable) {
    return (
      <Card tone="warn">
        <Headline>{t("I can't read this photo")}</Headline>
        <div className="text-[16px] mt-1">{d.image_problem}</div>
        {imageUrl && (
          <img src={imageUrl} alt="" className="mt-3 rounded-xl max-h-40 object-cover" />
        )}
      </Card>
    )
  }

  const urgency = URGENCY_COPY[d.urgency] ?? URGENCY_COPY.monitor
  const top = (d.candidates || [])[0]

  return (
    <Card tone={urgency.tone}>
      <div className="flex gap-3">
        {imageUrl && (
          <img src={imageUrl} alt=""
               className="w-20 h-20 rounded-xl object-cover shrink-0" />
        )}
        <div className="min-w-0">
          <Headline>{top?.name || t('Unclear')}</Headline>
          <div className="text-[14px]" style={{ color: 'var(--text-muted)' }}>
            {t(urgency.text)}
            {d.affected_part ? ` · ${t(d.affected_part)}` : ''}
          </div>
        </div>
      </div>

      {/* Ranked possibilities. Showing the alternatives is the point: a
          single confident answer would misrepresent how much a photograph
          can actually settle. */}
      <div className="mt-3 space-y-2">
        {(d.candidates || []).map((c: any, i: number) => (
          <div key={i} className="rounded-xl p-3" style={{ background: 'var(--bg-sunken)' }}>
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium text-[15px]">{c.name}</span>
              <span className="text-[12px] px-2 py-0.5 rounded-full shrink-0"
                    style={{ color: CONF_TONE[c.confidence] || 'var(--text-muted)',
                             border: `1px solid ${CONF_TONE[c.confidence] || 'var(--border)'}` }}>
                {t(c.confidence)}
              </span>
            </div>
            {c.why && (
              <div className="text-[13px] mt-1" style={{ color: 'var(--text-muted)' }}>
                {c.why}
              </div>
            )}
            {/* The check the farmer can run themselves. This is what turns an
                unfalsifiable claim into something confirmable in the field. */}
            {c.farmer_check && (
              <div className="text-[14px] mt-2 rounded-lg p-2"
                   style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}>
                {t('Check for yourself:')} {c.farmer_check}
              </div>
            )}
            {c.weather_consistent === false && (
              <div className="text-[12px] mt-1" style={{ color: '#c2703d' }}>
                {t('Recent weather was not favourable for this — less likely.')}
              </div>
            )}
          </div>
        ))}
      </div>

      {d.immediate_actions?.length > 0 && (
        <div className="mt-3">
          <div className="font-medium text-[15px] mb-1">{t('Do this now')}</div>
          <ul className="space-y-1">
            {d.immediate_actions.map((a: string, i: number) => (
              <li key={i} className="text-[15px] flex gap-2">
                <span style={{ color: 'var(--accent)' }}>·</span>{a}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Chemical guidance names a class and never a dose. Doses depend on
          formulation and equipment, are printed on the label, and are set by
          the state agriculture department. */}
      {d.active_ingredient_class && (
        <div className="mt-3 text-[14px] rounded-lg p-3"
             style={{ background: 'var(--bg-sunken)' }}>
          <span className="font-medium">{t('If you spray:')} </span>
          {d.active_ingredient_class}. {t('Follow the dose on the label — we do not advise quantities. Confirm with your KVK or extension officer.')}
        </div>
      )}

      {d.refer_to_expert && (
        <div className="mt-3 text-[14px] rounded-lg p-3"
             style={{ background: '#fdf0ea', color: '#c2452d' }}>
          {t('This needs a real look. Please show it to your nearest KVK or agriculture extension officer.')}
        </div>
      )}

      {/* The weather-driven prior. This is the part that separates the
          diagnosis from a generic image lookup, so it is shown, not hidden. */}
      {d.infection_pressure?.length > 0 && (
        <details className="mt-3">
          <summary className="text-[13px] cursor-pointer"
                   style={{ color: 'var(--text-muted)' }}>
            {t('Disease pressure at your field over the last 3 weeks')}
          </summary>
          <div className="mt-2 space-y-1">
            {d.infection_pressure.map((p: any, i: number) => (
              <div key={i} className="flex justify-between text-[13px]">
                <span>{p.name}</span>
                <span style={{
                  color: ['severe', 'high'].includes(p.risk_level)
                    ? '#c2452d' : 'var(--text-muted)',
                }}>
                  {t(p.risk_level)} · {t('{a} of {b} days', { a: p.favourable_days, b: p.days_assessed })}
                </span>
              </div>
            ))}
          </div>
        </details>
      )}
    </Card>
  )
}


/* ------------------------------------------------------------------ */
/* Mandi prices                                                        */
/* ------------------------------------------------------------------ */

export function MandiCard({ d }: { d: any }) {
  const t = useT()
  const median = d.median_rs_per_quintal
  const best = d.best_market
  const local = d.local_market
  const national = d.scope === 'national'

  return (
    <Card tone={national ? 'warn' : 'neutral'}>
      {/* Rupees per quintal, always stated. A farmer hearing a per-kg figure
          when it is per-quintal is out by a hundredfold. */}
      <Headline>
        {t('₹{n} per quintal', { n: median?.toLocaleString('en-IN') ?? '' })}
      </Headline>
      <div className="text-[14px]" style={{ color: 'var(--text-muted)' }}>
        {t(d.crop_name)} · {t('{n} markets reporting', { n: d.markets_reporting })}
        {d.as_of ? ` · ${d.as_of}` : ''}
      </div>

      {national && (
        <div className="mt-2 text-[14px] rounded-lg p-2"
             style={{ background: 'var(--bg-sunken)', color: 'var(--text-muted)' }}>
          {t('No mandi in your state traded this crop today — it is likely out of season locally. These are rates from elsewhere in India, a guide to what to expect rather than what you would be paid today.')}
        </div>
      )}

      <div className="mt-3 space-y-1">
        {local && (
          <Detail label={`${t('Your district')} (${local.market})`}
                  value={`₹${local.modal_rs_per_quintal.toLocaleString('en-IN')}`} />
        )}
        {best && (
          <Detail label={`${t('Best rate')} (${best.market}, ${best.district})`}
                  value={`₹${best.modal_rs_per_quintal.toLocaleString('en-IN')}`} />
        )}
      </div>

      {/* The gap matters more than the level. Shown per tonne because that is
          how a load is costed -- a per-quintal gap looks trivial until scaled. */}
      {d.premium_per_tonne_rs > 0 && (
        <div className="mt-3 text-[14px] rounded-lg p-3"
             style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}>
          {t('{m} is paying about ₹{n} more per tonne than your local mandi. Worth it only if transport costs less than that.', { m: best.market, n: d.premium_per_tonne_rs.toLocaleString('en-IN') })}
        </div>
      )}

      {d.top_markets?.length > 1 && (
        <details className="mt-3">
          <summary className="text-[13px] cursor-pointer"
                   style={{ color: 'var(--text-muted)' }}>
            {t('All reporting markets')}
          </summary>
          <div className="mt-2 space-y-1">
            {d.top_markets.map((m: any, i: number) => (
              <div key={i} className="flex justify-between text-[13px] gap-3">
                <span className="truncate">
                  {m.market}
                  <span style={{ color: 'var(--text-muted)' }}> · {m.district}</span>
                </span>
                <span className="shrink-0">
                  ₹{m.modal_rs_per_quintal.toLocaleString('en-IN')}
                </span>
              </div>
            ))}
          </div>
        </details>
      )}
    </Card>
  )
}


/* ------------------------------------------------------------------ */
/* Government schemes                                                  */
/* ------------------------------------------------------------------ */

/**
 * Scheme cards are navigation, never entitlement.
 *
 * The card never says "you qualify". It gives the farmer questions they can
 * answer themselves, the things that most commonly disqualify people, and a
 * phone number and website that outrank anything we said. That ordering is
 * deliberate: the helpline is the most valuable thing on the card, because
 * it is the only part that is authoritative.
 */
export function SchemesCard({ d }: { d: any }) {
  const t = useT()
  const schemes: any[] = d.schemes || []
  if (!schemes.length) return null

  return (
    <Card tone="neutral">
      <Headline>{t('Schemes worth checking')}</Headline>
      <div className="text-[13px] mb-3" style={{ color: 'var(--text-muted)' }}>
        {t('Whether you qualify is decided by your agriculture department, not by me. Use the questions below to see if it is worth the trip.')}
      </div>

      <div className="space-y-3">
        {schemes.map((s, i) => (
          <div key={i} className="rounded-xl p-3" style={{ background: 'var(--bg-sunken)' }}>
            <div className="font-medium text-[16px]">{s.short_name}</div>
            <div className="text-[14px] mt-0.5">{t(s.what_it_does)}</div>

            {s.check_yourself?.length > 0 && (
              <div className="mt-2">
                <div className="text-[13px] font-medium mb-1">{t('Check yourself')}</div>
                <ul className="space-y-0.5">
                  {s.check_yourself.map((q: string, j: number) => (
                    <li key={j} className="text-[14px] flex gap-2">
                      <span style={{ color: 'var(--accent)' }}>·</span>{t(q)}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <details className="mt-2">
              <summary className="text-[13px] cursor-pointer"
                       style={{ color: 'var(--text-muted)' }}>
                {t('What usually stops people, and what to carry')}
              </summary>
              <div className="mt-2 text-[13px] space-y-2"
                   style={{ color: 'var(--text-muted)' }}>
                {s.commonly_disqualifies?.length > 0 && (
                  <div>
                    <span className="font-medium">{t('Commonly disqualifies:')} </span>
                    {s.commonly_disqualifies.map((x: string) => t(x)).join('; ')}
                  </div>
                )}
                {s.documents?.length > 0 && (
                  <div>
                    <span className="font-medium">{t('Documents:')} </span>
                    {s.documents.map((x: string) => t(x)).join(', ')}
                  </div>
                )}
                {s.key_facts?.length > 0 && (
                  <ul className="list-disc ml-4">
                    {s.key_facts.map((f: string, j: number) => <li key={j}>{t(f)}</li>)}
                  </ul>
                )}
              </div>
            </details>

            {/* The authoritative route out. Rendered as a tel: link because
                on a phone this should be one tap, not a number to copy. */}
            <div className="mt-2 flex flex-wrap gap-3 items-center text-[14px]">
              {/^[\d\s\-/]+$/.test(s.helpline) ? (
                <a href={`tel:${s.helpline.split('/')[0].trim()}`}
                   className="underline underline-offset-2"
                   style={{ color: 'var(--accent)' }}>
                  📞 {s.helpline}
                </a>
              ) : (
                <span style={{ color: 'var(--text-muted)' }}>📞 {s.helpline}</span>
              )}
              <a href={s.official_website} target="_blank" rel="noreferrer"
                 className="underline underline-offset-2"
                 style={{ color: 'var(--accent)' }}>
                {t('Official website')}
              </a>
            </div>

            {s.may_be_out_of_date && (
              <div className="mt-2 text-[12px]" style={{ color: '#c2703d' }}>
                {t('This information was last checked on {d} and scheme rules change every year. Confirm before acting.', { d: s.information_last_checked })}
              </div>
            )}
          </div>
        ))}
      </div>
    </Card>
  )
}

/** Dispatch a card payload to its renderer. */
export function CropValueCard({ d }: { d: any }) {
  const t = useT()
  const m = d.money || {}
  const rupees = (n: number) =>
    // Indian grouping: 1,20,000 rather than 120,000. A farmer reading
    // "120,000" has to stop and count digits.
    new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(n)

  return (
    <Card tone="neutral">
      <Headline>
        {d.crop_name
          ? t('What your {crop} is worth today', { crop: t(d.crop_name) })
          : t('What your crop is worth today')}
      </Headline>

      <div className="text-[15px] mt-1">
        {t('Likely harvest')}{' '}
        <span className="font-medium">
          {t('{low} to {high} quintals', {
            low: m.quintals?.[0] ?? '', high: m.quintals?.[1] ?? '',
          })}
        </span>
      </div>
      {d.lost_to_water_stress_percent > 0 && (
        <div className="text-[13px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
          {t('Your usual {n} per acre, less {pct}% the crop gave up to water stress', {
            n: d.attainable_in_a_good_year ?? '', pct: d.lost_to_water_stress_percent,
          })}
        </div>
      )}

      <div className="mt-2 pt-2 border-t" style={{ borderColor: 'var(--border)' }}>
        {m.revenue ? (
          <Detail
            label={t('At today’s rate')}
            value={`₹${rupees(m.revenue[0])} – ₹${rupees(m.revenue[1])}`}
          />
        ) : (
          <div className="text-[13px]" style={{ color: 'var(--text-muted)' }}>
            {t('No mandi rate reported for this crop today, so no rupee figure.')}
          </div>
        )}
        {m.price_today && (
          <Detail label={t('Rate used')}
                  value={t('₹{n} a quintal at {market}', {
                    n: m.price_today, market: m.price_market || '',
                  })} />
        )}
        {m.msp && (
          <Detail
            label={t('Support price floor')}
            value={
              <>
                {`₹${rupees(m.msp)}`}{' '}
                <span style={{ color: 'var(--text-muted)' }}>
                  {m.above_msp === true ? t('— today’s rate is above it')
                    : m.above_msp === false ? t('— today’s rate is below it')
                    : ''}
                </span>
              </>
            } />
        )}
        {m.margin && (
          <Detail label={m.margin[0] < 0 ? t('Loss after your costs')
                                         : t('Left after your costs')}
                  value={`₹${rupees(m.margin[0])} – ₹${rupees(m.margin[1])}`} />
        )}
      </div>

      {m.better_market && (
        <div className="mt-2 text-[14px] rounded-xl p-2"
             style={{ background: 'var(--bg-sunken)' }}>
          {t('{market} is paying ₹{price} — about ₹{extra} more for this much crop', {
            market: m.better_market.market, price: m.better_market.price,
            extra: rupees(m.better_market.extra_rupees),
          })}
        </div>
      )}

      {/* Said on the card, not only in the evidence ledger. The number most
          likely to be misread is the rupee one, and the misreading that
          costs a farmer money is treating it as what they will get at
          harvest. */}
      <div className="mt-2 text-[12px]" style={{ color: 'var(--text-muted)' }}>
        {t('This is what today’s rate would pay for this much crop. Nobody can say what the rate will be at harvest.')}
      </div>
    </Card>
  )
}

// Where an answer came from.
//
// Deliberately quiet: a small list under the reply rather than a panel
// competing with it. The passages themselves are not repeated here — the
// assistant has already said what they say, in the farmer's own language,
// and printing the English underneath would be noise for the person who
// needed the translation most.
//
// What this adds is the one thing spoken advice cannot carry: something to
// check. A farmer who is unsure, or an extension officer they show the phone
// to, can open the page and read the original. That is also the honest
// signal that this particular answer was read from somewhere rather than
// recalled.
export function SourcesCard({ d }: { d: any }) {
  const t = useT()
  const sources: any[] = d.sources || []
  if (!sources.length) return null

  return (
    <Card tone="neutral">
      <Headline>{t('Where this came from')}</Headline>
      <div className="text-[13px] mb-2" style={{ color: 'var(--text-muted)' }}>
        {t('Published advice from')} {d.source_name || t('Vikaspedia, Government of India')}
      </div>
      <div className="space-y-2">
        {sources.map((s, i) => (
          <a key={i} href={s.url} target="_blank" rel="noopener noreferrer"
             className="block rounded-xl p-3"
             style={{ background: 'var(--bg-sunken)' }}>
            <div className="text-[14px] font-medium">{s.title}</div>
            {s.section && s.section !== s.title && (
              <div className="text-[13px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
                {String(s.section).split(' > ').slice(1).join(' › ')}
              </div>
            )}
            {s.updated && (
              <div className="text-[12px] mt-1" style={{ color: 'var(--text-muted)' }}>
                {t('Page updated')} {s.updated}
              </div>
            )}
          </a>
        ))}
      </div>
    </Card>
  )
}

export function RenderCard({ card }: { card: any }) {
  switch (card.card) {
    case 'irrigation':  return <IrrigationCard d={card} />
    case 'weather':     return <WeatherCard d={card} />
    case 'soil':        return <SoilCard d={card} />
    case 'suitability': return <SuitabilityCard d={card} />
    case 'carbon':      return <CarbonCard d={card} />
    case 'diagnosis':   return <DiagnosisCard d={card} imageUrl={card.imageUrl} />
    case 'mandi':       return <MandiCard d={card} />
    case 'schemes':     return <SchemesCard d={card} />
    case 'crop_value':  return <CropValueCard d={card} />
    case 'sources':     return <SourcesCard d={card} />
    default: return null
  }
}
