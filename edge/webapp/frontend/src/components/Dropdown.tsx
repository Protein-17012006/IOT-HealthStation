import { useEffect, useRef, useState } from 'react'

interface Opt { value: string; label: string }

// A themed select with an animated open/close and hover-highlighted options.
// Keyboard accessible: Enter/Space toggles, arrows move, Escape closes.
export default function Dropdown({ value, options, onChange }: {
  value: string
  options: Opt[]
  onChange: (v: string) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const cur = options.find((o) => o.value === value)

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { setOpen(false); return }
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen((o) => !o); return }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      const i = options.findIndex((o) => o.value === value)
      const ni = e.key === 'ArrowDown'
        ? Math.min(options.length - 1, i + 1)
        : Math.max(0, i - 1)
      onChange(options[ni].value)
    }
  }

  return (
    <div className={'dd' + (open ? ' open' : '')} ref={ref}>
      <button type="button" className="dd-btn" onClick={() => setOpen((o) => !o)}
        onKeyDown={onKey} aria-haspopup="listbox" aria-expanded={open}>
        {cur?.label ?? '—'}<span className="dd-chev">▾</span>
      </button>
      <ul className="dd-menu" role="listbox">
        {options.map((o) => (
          <li key={o.value} role="option" aria-selected={o.value === value}
            className={'dd-opt' + (o.value === value ? ' sel' : '')}
            onClick={() => { onChange(o.value); setOpen(false) }}>
            {o.label}
          </li>
        ))}
      </ul>
    </div>
  )
}
