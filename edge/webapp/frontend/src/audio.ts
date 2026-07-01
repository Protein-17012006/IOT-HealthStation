// Web Audio fall alarm. Browsers block audio until a user gesture, so call
// unlockAudio() on the first click; alarmBeep() then plays a 3-tone medical beep.
let ctx: AudioContext | null = null

export function unlockAudio() {
  if (!ctx) {
    const AC = window.AudioContext || (window as any).webkitAudioContext
    ctx = new AC()
  }
  if (ctx.state === 'suspended') ctx.resume()
}

export function alarmBeep(muted: boolean) {
  if (!ctx || muted) return
  const t0 = ctx.currentTime
  for (let i = 0; i < 3; i++) {
    const o = ctx.createOscillator()
    const g = ctx.createGain()
    const t = t0 + i * 0.26
    o.type = 'square'
    o.frequency.value = i % 2 ? 988 : 1319
    g.gain.setValueAtTime(0.0001, t)
    g.gain.exponentialRampToValueAtTime(0.22, t + 0.02)
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.2)
    o.connect(g).connect(ctx.destination)
    o.start(t)
    o.stop(t + 0.22)
  }
}
