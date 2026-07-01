interface Props {
  patient: string
  ts?: string
}

export default function PatientCard({ patient, ts }: Props) {
  return (
    <div className="card vital patientcard">
      <span className="eyebrow">Current patient</span>
      <div className="who">{patient || '—'}</div>
      <div className="meta">{ts ? 'updated ' + ts.split(' ')[1] : 'awaiting data…'}</div>
      <div className="meta muted" style={{ marginTop: 'auto' }}>RFID check-in</div>
    </div>
  )
}
