import type { EventRow } from '../types'

export default function EventLog({ events }: { events: EventRow[] }) {
  return (
    <div className="card">
      <div className="cardhead"><h2>Event log</h2></div>
      <div className="pad">
        <table className="log"><tbody>
          {events.length === 0 && (
            <tr><td className="muted" style={{ padding: '14px 6px' }}>No events yet.</td></tr>
          )}
          {events.map((e, i) => (
            <tr key={i} className={'sev-' + e.severity}>
              <td className="t">{(e.ts || '').split(' ')[1] || e.ts}</td>
              <td className="ty"><span className="dot" />{e.type}</td>
              <td>{e.message}</td>
            </tr>
          ))}
        </tbody></table>
      </div>
    </div>
  )
}
