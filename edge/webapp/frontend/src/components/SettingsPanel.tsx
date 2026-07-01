import { useEffect, useRef, useState } from 'react'
import type { Settings } from '../types'

interface Props {
  settings: Settings
  onSaved: (s: Settings) => void
}

// Seeds the form once from the server, then stays user-controlled so the live
// stream can't overwrite what you're typing before you press Save.
export default function SettingsPanel({ settings, onSaved }: Props) {
  const seeded = useRef(false)
  const [form, setForm] = useState({
    temp_high: '', sound_high: '', camera_url: '',
    fan_auto: false, rules_enabled: false, fall_detection: false,
  })
  const [msg, setMsg] = useState('')

  useEffect(() => {
    if (!seeded.current && Object.keys(settings).length) {
      setForm({
        temp_high: settings.temp_high ?? '',
        sound_high: settings.sound_high ?? '',
        camera_url: settings.camera_url ?? '',
        fan_auto: settings.fan_auto === '1',
        rules_enabled: settings.rules_enabled === '1',
        fall_detection: settings.fall_detection === '1',
      })
      seeded.current = true
    }
  }, [settings])

  const set = (k: string, v: any) => setForm((f) => ({ ...f, [k]: v }))

  const save = async () => {
    const body: Settings = {
      temp_high: form.temp_high,
      sound_high: form.sound_high,
      camera_url: form.camera_url.trim(),
      fan_auto: form.fan_auto ? '1' : '0',
      rules_enabled: form.rules_enabled ? '1' : '0',
      fall_detection: form.fall_detection ? '1' : '0',
    }
    await fetch('/api/settings', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    })
    setMsg('✓ saved'); setTimeout(() => setMsg(''), 1500)
    onSaved(body)
  }

  return (
    <div className="card">
      <div className="cardhead"><h2>Rule thresholds</h2><span className="eyebrow">Edge analytics</span></div>
      <div className="pad">
        <label>Fever temperature ≥ (°C)</label>
        <input type="number" step="0.1" value={form.temp_high} onChange={(e) => set('temp_high', e.target.value)} />
        <label>Loud sound ≥ (raw 0–4095)</label>
        <input type="number" value={form.sound_high} onChange={(e) => set('sound_high', e.target.value)} />
        <label>Camera URL <span className="muted">(proxied — never shown to viewers)</span></label>
        <input type="text" placeholder="http://user:pass@192.168.x.x:8081/video"
          value={form.camera_url} onChange={(e) => set('camera_url', e.target.value)} />
        <div className="checks">
          <label><input type="checkbox" checked={form.fan_auto} onChange={(e) => set('fan_auto', e.target.checked)} /> Auto fan on fever</label>
          <label><input type="checkbox" checked={form.rules_enabled} onChange={(e) => set('rules_enabled', e.target.checked)} /> Rules enabled</label>
          <label><input type="checkbox" checked={form.fall_detection} onChange={(e) => set('fall_detection', e.target.checked)} /> Fall detection (AI)</label>
        </div>
        <div className="controls">
          <button className="btn primary" onClick={save}>Save settings</button>
          <span className="savemsg">{msg}</span>
        </div>
      </div>
    </div>
  )
}
