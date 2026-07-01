import { useEffect, useRef } from 'react'

interface Props {
  sound: number | undefined
  soundHigh: number
}

// Signature element: a smooth, time-scrolled mirror waveform of the live KY-037
// ambient-sound level. Calm violet; turns alarm-red when the noise threshold is
// crossed. Real samples (one per server tick), scrolled with requestAnimationFrame.
export default function SoundWave({ sound, soundHigh }: Props) {
  const canRef = useRef<HTMLCanvasElement>(null)
  const samples = useRef<{ t: number; v: number }[]>([])
  const alertRef = useRef(false)

  useEffect(() => {
    if (sound == null) return
    samples.current.push({ t: performance.now(), v: Math.min(sound, 4095) / 4095 })
    alertRef.current = !isNaN(soundHigh) && sound >= soundHigh
    const cut = performance.now() - 20000
    while (samples.current.length && samples.current[0].t < cut) samples.current.shift()
  }, [sound, soundHigh])

  useEffect(() => {
    const can = canRef.current!
    const ctx = can.getContext('2d')!
    let raf = 0
    const draw = () => {
      const dpr = window.devicePixelRatio || 1
      const w = can.clientWidth, h = can.clientHeight
      if (can.width !== Math.round(w * dpr)) { can.width = w * dpr; can.height = h * dpr }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)
      const mid = h / 2
      ctx.strokeStyle = 'rgba(255,255,255,.05)'; ctx.lineWidth = 1
      ctx.beginPath(); ctx.moveTo(0, mid); ctx.lineTo(w, mid); ctx.stroke()
      const S = samples.current
      if (S.length > 1) {
        const now = performance.now(), pxMs = w / 20000
        const col = alertRef.current ? '#FF3B47' : '#A78BFA'
        const X = (s: { t: number; v: number }) => w - (now - s.t) * pxMs
        const A = (s: { t: number; v: number }) => s.v * (h * 0.42)
        ctx.beginPath()
        S.forEach((s, i) => { const x = X(s), y = mid - A(s); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y) })
        for (let i = S.length - 1; i >= 0; i--) { const s = S[i]; ctx.lineTo(X(s), mid + A(s)) }
        ctx.closePath()
        const g = ctx.createLinearGradient(0, 0, 0, h)
        g.addColorStop(0, col + '4d'); g.addColorStop(.5, col + '14'); g.addColorStop(1, col + '4d')
        ctx.fillStyle = g; ctx.fill()
        ctx.beginPath()
        S.forEach((s, i) => { const x = X(s), y = mid - A(s); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y) })
        ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.shadowColor = col; ctx.shadowBlur = 8
        ctx.stroke(); ctx.shadowBlur = 0
      }
      raf = requestAnimationFrame(draw)
    }
    raf = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(raf)
  }, [])

  return (
    <div className="card wave-card">
      <div className="cardhead"><h2>Ambient sound</h2><span className="eyebrow">KY-037 · live</span></div>
      <div className="wave-body"><canvas ref={canRef} /></div>
      <div className="wave-foot">
        <span className="muted">20-second trace</span>
        <span className="lvl">{sound == null ? '—' : Math.round(sound)} /4095</span>
      </div>
    </div>
  )
}
