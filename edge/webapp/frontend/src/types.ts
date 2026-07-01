export interface Reading {
  id?: number
  ts?: string
  temp?: number
  humidity?: number
  sound?: number
  patient_uid?: string | null
}

export interface EventRow {
  ts: string
  type: string
  severity: string
  message: string
}

export type Settings = Record<string, string>

export interface Snapshot {
  reading: Reading | null
  patient: string | null
  events: EventRow[]
  settings: Settings
  last_fall_age: number | null
  ai_active?: boolean
}
