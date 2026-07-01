import { useEffect, useState } from 'react'
import {
  Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, Filler, Tooltip,
} from 'chart.js'
import { Line } from 'react-chartjs-2'
import Dropdown from './Dropdown'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Filler, Tooltip)

const COL: Record<string, string> = { temp: '#FFB000', humidity: '#22D3EE', sound: '#A78BFA' }

export default function TrendChart() {
  const [metric, setMetric] = useState('temp')
  const [labels, setLabels] = useState<string[]>([])
  const [vals, setVals] = useState<number[]>([])
  const [stats, setStats] = useState<any>({})

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const h = await (await fetch('/api/history?metric=' + metric + '&n=60')).json()
        const s = await (await fetch('/api/stats?metric=' + metric + '&minutes=60')).json()
        if (!alive) return
        setLabels(h.map((p: any) => p.ts)); setVals(h.map((p: any) => p.value)); setStats(s)
      } catch { /* ignore */ }
    }
    load()
    const id = setInterval(load, 5000)
    return () => { alive = false; clearInterval(id) }
  }, [metric])

  const col = COL[metric] || COL.temp
  const data = {
    labels,
    datasets: [{ data: vals, borderColor: col, backgroundColor: col + '20', fill: true, tension: .35, pointRadius: 0, borderWidth: 2 }],
  }
  const opts: any = {
    responsive: true, maintainAspectRatio: false, animation: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { ticks: { color: '#5b6b82', maxTicksLimit: 6 }, grid: { color: 'rgba(255,255,255,.04)' } },
      y: { ticks: { color: '#5b6b82' }, grid: { color: 'rgba(255,255,255,.04)' } },
    },
  }

  return (
    <div className="card">
      <div className="cardhead"><h2>Trend</h2>
        <Dropdown value={metric} onChange={setMetric} options={[
          { value: 'temp', label: 'Temperature' },
          { value: 'humidity', label: 'Humidity' },
          { value: 'sound', label: 'Sound' },
        ]} />
      </div>
      <div className="pad">
        <div style={{ height: 170 }}><Line data={data} options={opts} /></div>
        <div className="statline">
          <span>Mean <b>{stats.mean ?? '--'}</b></span>
          <span>Min <b>{stats.min ?? '--'}</b></span>
          <span>Max <b>{stats.max ?? '--'}</b></span>
          <span>Samples <b>{stats.count ?? '--'}</b></span>
        </div>
      </div>
    </div>
  )
}
