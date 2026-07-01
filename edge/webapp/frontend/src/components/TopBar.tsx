interface Props {
  patient: string
  live: boolean
  status: { txt: string; col: string }
  muted: boolean
  onToggleMute: () => void
}

export default function TopBar({ patient, live, status, muted, onToggleMute }: Props) {
  return (
    <header className="topbar">
      <div className="brand"><span className="glyph">✚</span> Health Station</div>
      <div className="sep" />
      <div className="patient-id">
        <span className="eyebrow">Patient</span>
        <span className="who">{patient || '—'}</span>
      </div>
      <div className="spacer" />
      <div className={'conn' + (live ? ' live' : '')}>
        <span className="dot" />{live ? 'live' : 'reconnecting…'}
      </div>
      <button className="iconbtn" title="Mute / unmute fall alarm" onClick={onToggleMute}>
        {muted ? '🔕' : '🔔'}
      </button>
      <span className="status-pill" style={{ color: status.col }}>● {status.txt}</span>
    </header>
  )
}
