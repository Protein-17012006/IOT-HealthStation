import { useEffect, useState } from 'react'

interface Props {
  cameraUrl: string
  fall: boolean
  aiActive: boolean
}

// Shows the patient camera. When the GPU detector is pushing annotated frames
// (aiActive), it prefers /api/ai_camera -- the live feed WITH the YOLOv8 skeleton,
// boxes and FALL banner drawn on it. Otherwise it falls back to /api/camera, the
// raw iPhone MJPEG proxied by Flask (credentials injected server-side, so they
// never reach the browser). A toggle forces the raw feed for the demo.
//
// The <img> element is kept mounted and its src is only reassigned when the chosen
// source actually changes (an MJPEG stream restarts on every src write, so we must
// not rewrite it every render). `nonce` lets the toggle / retry re-issue the
// current source to recover from a transient error.
export default function CameraPanel({ cameraUrl, fall, aiActive }: Props) {
  const [showAI, setShowAI] = useState(true)
  const [failed, setFailed] = useState(false)
  const [nonce, setNonce] = useState(0)
  const [src, setSrc] = useState('')

  const mode = (showAI && aiActive) ? 'ai' : (cameraUrl ? 'raw' : 'none')

  // Recompute src only when the source genuinely changes (mode / url / retry),
  // never on every live-data tick.
  useEffect(() => {
    setFailed(false)
    if (mode === 'ai') setSrc(`/api/ai_camera?t=${Date.now()}_${nonce}`)
    else if (mode === 'raw') setSrc(`/api/camera?t=${Date.now()}_${nonce}`)
    else setSrc('')
  }, [mode, cameraUrl, nonce])

  const retry = () => setNonce((n) => n + 1)
  const toggle = () => { setShowAI((v) => !v); setNonce((n) => n + 1) }
  const onError = () => {
    // an AI feed that drops while still "active" -> re-pick (retries AI, or shows
    // raw once ai_active turns false); a raw failure shows the recoverable error
    if (mode === 'ai') retry()
    else setFailed(true)
  }

  const showImg = mode !== 'none' && !failed

  return (
    <div className="card">
      <div className="cardhead">
        <h2>Live patient feed</h2>
        <button
          className={'feed-toggle' + (showAI ? ' on' : '')}
          onClick={toggle}
          title={aiActive ? 'Toggle the AI detection overlay'
                          : 'AI detector offline — start run_fall_detector.sh'}
        >
          {showAI ? (aiActive ? 'AI overlay' : 'AI overlay (offline)') : 'Raw feed'}
        </button>
      </div>
      <div className="pad" style={{ padding: 12 }}>
        <div className={'cam-wrap' + (fall ? ' crit' : '')}>
          {src && (
            <img src={src} alt="Live patient camera"
                 style={{ display: showImg ? 'block' : 'none' }}
                 onError={onError} />
          )}
          {!showImg && (
            <div className="cam-ph">
              <div className="ico">📷</div>
              <div className="ph-msg">
                {failed
                  ? 'Camera unreachable — check the URL and that the phone app is streaming.'
                  : 'No camera connected. Add the stream URL under Rule thresholds → Camera URL below.'}
              </div>
              {failed && <button className="feed-toggle" onClick={retry}>Retry</button>}
            </div>
          )}
          <div className={'cam-badge' + (fall ? ' crit' : '')}>
            <span className="bdot" />
            {fall ? 'AI: FALL DETECTED' : (mode === 'ai' ? 'AI: monitoring' : 'AI: monitoring (raw)')}
          </div>
          <div className="cam-live">LIVE</div>
        </div>
      </div>
    </div>
  )
}
