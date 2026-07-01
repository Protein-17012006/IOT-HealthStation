import { useState } from 'react'

async function cmd(c: any) {
  await fetch('/api/command', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(c),
  })
}

export default function ManualControl() {
  const [lcd, setLcd] = useState('')
  return (
    <div className="card">
      <div className="cardhead"><h2>Manual control</h2></div>
      <div className="pad">
        <div className="controls" style={{ marginTop: 0 }}>
          <button className="btn" onClick={() => cmd({ fan: 1 })}>Fan on</button>
          <button className="btn" onClick={() => cmd({ fan: 0 })}>Fan off</button>
          <button className="btn" onClick={() => cmd({ led: 'red' })}>LED red</button>
          <button className="btn" onClick={() => cmd({ led: 'green' })}>LED green</button>
        </div>
        <label>LCD message</label>
        <div className="controls" style={{ marginTop: 0 }}>
          <input type="text" placeholder="Up to 32 chars" style={{ flex: 1 }}
            value={lcd} onChange={(e) => setLcd(e.target.value)} />
          <button className="btn" onClick={() => cmd({ lcd })}>Send</button>
        </div>
        <p className="fieldnote">Commands are queued in the database and applied by the edge server (main.py) on its next loop.</p>
      </div>
    </div>
  )
}
