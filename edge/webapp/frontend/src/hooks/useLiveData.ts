import { useEffect, useState } from 'react'
import type { Snapshot } from '../types'

// Connects to the Flask SSE stream (/api/stream) and exposes the latest
// snapshot reactively. Falls back to polling /api/latest if SSE is unavailable
// or errors. `live` reflects the connection state for the topbar indicator.
export function useLiveData() {
  const [data, setData] = useState<Snapshot | null>(null)
  const [live, setLive] = useState(false)

  useEffect(() => {
    let es: EventSource | null = null
    let poll: number | undefined

    const apply = (d: Snapshot) => { setData(d); setLive(true) }

    const startPolling = () => {
      if (poll) return
      const tick = async () => {
        try {
          const r = await fetch('/api/latest')
          apply(await r.json())
        } catch {
          setLive(false)
        }
      }
      tick()
      poll = window.setInterval(tick, 2000)
    }

    if ('EventSource' in window) {
      es = new EventSource('/api/stream')
      es.onmessage = (e) => {
        try { apply(JSON.parse(e.data)) } catch { /* ignore partial frames */ }
      }
      es.onerror = () => {
        es?.close()
        setLive(false)
        startPolling()
      }
    } else {
      startPolling()
    }

    return () => {
      es?.close()
      if (poll) clearInterval(poll)
    }
  }, [])

  return { data, live }
}
