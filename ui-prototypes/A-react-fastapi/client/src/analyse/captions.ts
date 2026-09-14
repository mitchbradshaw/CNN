/* One-line plain-language captions (spec §3: load-bearing). Before a run a row shows a
   parameter summary; after a run it shows the payload's own summary. */
import type { AdapterCard, Step } from '../api'

const fmtNum = (v: unknown) => typeof v === 'number' ? (Number.isInteger(v) ? String(v) : String(+v.toFixed(3))) : String(v)

export function paramCaption(step: Step, adapter: AdapterCard | undefined): string {
  const p = step.params ?? {}
  const name = `${step.stage}.${step.algorithm}`
  switch (name) {
    case 'preprocessing.detrend':
      return p.mode === 'linear' ? 'linear trend subtracted' : `${fmtNum(p.window_s ?? 600)} s ${p.mode === 'rolling_z' ? 'rolling z-score' : 'rolling mean'} subtracted`
    case 'detection.matrix_profile':
      return `m = ${fmtNum(p.window_min ?? 10)} min · z-normalised · ${String(p.backend ?? 'auto')}`
    case 'detection.threshold':
      return `spans where score > ${fmtNum(p.threshold ?? 0)}`
    case 'detection.sax_dsax':
      return `${segCaption(p)} → dSAX letters · alphabet ${fmtNum(p.alphabet_size ?? 3)} · cutlines ${String(p.threshold_mode ?? 'learned')}`
    case 'detection.sax_csax':
      return `${segCaption(p)} → cSAX letters`
    case 'detection.sax_psax':
      return `${segCaption(p)} → pSAX letters · alphabet ${fmtNum(p.alphabet_size ?? 8)}`
    case 'preprocessing.window_matrix':
      return `${fmtNum(p.window_min ?? 10)} min windows · step ${fmtNum(p.step_frac ?? 1)} × · ${['catch22', 'fast_entropy', 'slow_entropy', 'cnn', 'rf'].filter(k => (p[k] ?? (k === 'catch22' || k === 'fast_entropy' || k === 'slow_entropy'))).join(' + ') || 'no feature groups'}`
    case 'catalogue.cluster':
      return `${String(p.linkage ?? 'ward')} linkage · cut into k = ${fmtNum(p.k ?? 3)}`
    case 'catalogue.classifier':
      return `${fmtNum(p.n_estimators ?? 300)} trees · ${Math.round(Number(p.holdout_frac ?? 0.25) * 100)} % held out · classes = clusters`
    case 'preprocessing.bandpass':
      return `${fmtNum(p.low_hz ?? 0.01)}–${fmtNum(p.high_hz ?? 0.1)} Hz · order ${fmtNum(p.order ?? 4)}`
    case 'preprocessing.highpass':
    case 'preprocessing.lowpass':
      return `cutoff ${fmtNum(p.cutoff_hz ?? 0.01)} Hz · order ${fmtNum(p.order ?? 4)}`
    case 'preprocessing.surrogate':
      return `${String(p.method ?? 'phase_randomize').replace('_', ' ')} · seed ${fmtNum(p.seed ?? 0)}`
    case 'detection.rupture':
      return `${String(p.cost_model ?? 'l2')} cost · penalty ${fmtNum(p.penalty ?? 50)}`
    case 'detection.freq_stft':
      return `${fmtNum(p.window_size ?? 300)}-sample window · hop ${fmtNum(p.hop_size ?? 150)} · ${fmtNum(p.n_log_bins ?? 64)} log bins`
    default: {
      const entries = Object.entries(p).slice(0, 3).map(([k, v]) => `${k} ${fmtNum(v)}${unitOf(k)}`)
      return entries.length ? entries.join(' · ') : (adapter?.description?.split('.')[0] ?? 'defaults')
    }
  }
}

function segCaption(p: Record<string, unknown>): string {
  const mode = String(p.segment_mode ?? 'seconds_per_symbol')
  if (mode === 'samples_per_symbol') return `${fmtNum(p.samples_per_symbol ?? 20)} samples per symbol`
  if (mode === 'target_symbol_count') return `${fmtNum(p.target_symbol_count ?? 30)} symbols`
  if (mode === 'dim_ratio') return `dim ratio ${fmtNum(p.dim_ratio ?? 0.05)}`
  return `${fmtNum(p.seconds_per_symbol ?? 20)} s per symbol`
}

export function unitOf(paramName: string): string {
  if (/_s$/.test(paramName)) return ' s'
  if (/_hz$/.test(paramName)) return ' Hz'
  if (/_min$/.test(paramName)) return ' min'
  if (/_frac$/.test(paramName) || /fraction$/.test(paramName)) return ''
  return ''
}
