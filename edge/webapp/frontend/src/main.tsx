import ReactDOM from 'react-dom/client'
import App from './App'
import './styles.css'

// No StrictMode on purpose: it double-invokes effects in dev, which would open
// two SSE connections and two audio contexts. We want one of each.
ReactDOM.createRoot(document.getElementById('root')!).render(<App />)
