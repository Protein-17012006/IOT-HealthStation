import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { useLiveData } from './hooks/useLiveData'
import { unlockAudio, alarmBeep } from './audio'
import TopBar from './components/TopBar'
import CameraPanel from './components/CameraPanel'
import SoundWave from './components/SoundWave'
import VitalGauge from './components/VitalGauge'
import TrendChart from './components/TrendChart'
import EventLog from './components/EventLog'
import SettingsPanel from './components/SettingsPanel'
import ManualControl from './components/ManualControl'
import { ErrorBoundary } from './components/ErrorBoundary'

// Heavy WebGL bundle (three.js) — code-split so the dashboard paints first.
const VitalsCore = lazy(() => import('./components/VitalsCore'))

export default function App() {
  const { data, live } = useLiveData()
  const [muted, setMuted] = useState(false)
  const [cameraUrl, setCameraUrl] = useState('')
  const fallActive = useRef(false)
  const lastAlarm = useRef(0)
  const seededCam = useRef(false)
  const live3d = useRef<{ soundFrac: number; status: 'ok' | 'warn' | 'crit'; fall: boolean }>(
    { soundFrac: 0, status: 'ok', fall: false })
  const reduced = useMemo(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches, [])

  // unlock Web Audio on the first user gesture (browsers block autoplay)
  useEffect(() => {
    const f = () => unlockAudio()
    window.addEventListener('click', f, { once: true })
    return () => window.removeEventListener('click', f)
  }, [])

  const r: any = data?.reading || {}
  const s: any = data?.settings || {}

  // seed the camera URL once from saved settings
  useEffect(() => {
    if (!seededCam.current && s && Object.keys(s).length) {
      setCameraUrl((s.camera_url || '').trim())
      seededCam.current = true
    }
  }, [s])

  const tempHigh = parseFloat(s.temp_high || '999')
  const soundHigh = parseFloat(s.sound_high || '9999')
  const fall = data?.last_fall_age != null && data.last_fall_age <= 30
  const fever = r.temp != null && r.temp >= tempHigh
  const loud = r.sound != null && r.sound >= soundHigh
  const status = fall
    ? { txt: 'CRITICAL', col: 'var(--crit)' }
    : (fever || loud ? { txt: 'ATTENTION', col: 'var(--warn)' } : { txt: 'STABLE', col: 'var(--ok)' })

  // feed the live snapshot to the 3D core via a ref (no React re-render per tick)
  live3d.current.soundFrac = r.sound != null ? Math.min(r.sound, 4095) / 4095 : 0
  live3d.current.status = fall ? 'crit' : (fever || loud ? 'warn' : 'ok')
  live3d.current.fall = fall

  // fall alarm: beep on onset and every 3s while the fall stays active
  useEffect(() => {
    if (fall) {
      const now = Date.now()
      if (!fallActive.current || now - lastAlarm.current > 3000) {
        alarmBeep(muted)
        lastAlarm.current = now
      }
      fallActive.current = true
    } else {
      fallActive.current = false
    }
  }, [fall, data, muted])

  return (
    <>
      {fall && (
        <div className="crit-overlay">
          <div className="banner">⚠️ FALL DETECTED — caregiver attention needed</div>
        </div>
      )}
      <TopBar live={live} status={status}
        muted={muted} onToggleMute={() => setMuted((m) => !m)} />
      <div className="wrap">
        <section className="core-hero">
          <ErrorBoundary fallback={<div className="core-fallback" />}>
            <Suspense fallback={<div className="core-fallback" />}>
              <VitalsCore liveRef={live3d} reduced={reduced} />
            </Suspense>
          </ErrorBoundary>
          <div className="core-overlay">
            <span className="status-pill" style={{ color: status.col }}>● {status.txt}</span>
          </div>
        </section>
        <section className="hero">
          <CameraPanel cameraUrl={cameraUrl} fall={fall} aiActive={!!data?.ai_active} />
          <SoundWave sound={r.sound} soundHigh={soundHigh} />
        </section>

        <section className="vitals">
          <VitalGauge label="Temperature" value={r.temp} unit="°C" color="var(--temp)" min={30} max={42} dec={1} alert={fever} />
          <VitalGauge label="Humidity" value={r.humidity} unit="%" color="var(--humid)" min={0} max={100} dec={0} alert={false} />
          <VitalGauge label="Sound level" value={r.sound} unit="/4095" color="var(--sound)" min={0} max={4095} dec={0} alert={loud} />
        </section>

        <section className="row">
          <TrendChart />
          <EventLog events={data?.events || []} />
        </section>

        <section className="row">
          <SettingsPanel settings={s} onSaved={(b) => setCameraUrl((b.camera_url || '').trim())} />
          <ManualControl />
        </section>
      </div>
    </>
  )
}
