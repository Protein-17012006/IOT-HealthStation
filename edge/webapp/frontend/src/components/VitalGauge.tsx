import { useEffect, useRef, useState } from 'react'

interface Props {
  label: string
  value: number | undefined
  unit: string
  color: string
  min: number
  max: number
  dec: number
  alert: boolean
}

const R = 52
const C = 2 * Math.PI * R

export default function VitalGauge({ label, value, unit, color, min, max, dec, alert }: Props) {
  const [disp, setDisp] = useState(0)
  const fromRef = useRef(0)
  const [hist, setHist] = useState<number[]>([])

  // count-up animation toward the new value
  useEffect(() => {
    if (value == null) return
    const from = fromRef.current
    const start = performance.now()
    let raf = 0
    const step = (t: number) => {
      const k = Math.min(1, (t - start) / 500)
      setDisp(from + (value - from) * (1 - Math.pow(1 - k, 3)))
      if (k < 1) raf = requestAnimationFrame(step)
      else setDisp(value)
    }
    raf = requestAnimationFrame(step)
    fromRef.current = value
    return () => cancelAnimationFrame(raf)
  }, [value])

  // sparkline history (last 40 samples)
  useEffect(() => {
    if (value != null) setHist((h) => [...h, value].slice(-40))
  }, [value])

  const v = value ?? min
  const frac = Math.max(0, Math.min(1, (v - min) / (max - min)))
  const c = alert ? 'var(--crit)' : color
  const pts = hist.map((val, i) => {
    const f = Math.max(0, Math.min(1, (val - min) / (max - min)))
    return `${(i / 39 * 100).toFixed(1)},${(27 - f * 25).toFixed(1)}`
  }).join(' ')

  return (
    <div className={'card vital' + (alert ? ' alert' : '')}>
      <span className="eyebrow">{label}</span>
      <div className="gauge">
        <svg viewBox="0 0 120 120" width="128" height="128">
          <circle className="ring-track" cx="60" cy="60" r={R} />
          <circle className="ring-val" cx="60" cy="60" r={R}
            style={{ stroke: c, color: c, strokeDasharray: C, strokeDashoffset: C * (1 - frac) }} />
        </svg>
        <div className="read">
          <span className="num">{value == null ? '--' : disp.toFixed(dec)}</span>
          <span className="unit">{unit}</span>
        </div>
      </div>
      <svg className="spark" viewBox="0 0 100 28" preserveAspectRatio="none">
        <polyline className="spark-line" style={{ stroke: c }} points={pts} />
      </svg>
    </div>
  )
}
