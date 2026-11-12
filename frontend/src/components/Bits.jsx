import { Link, useParams, Navigate } from 'react-router-dom'
import { useStore } from '../store.jsx'

const cls = { Supported: 'ok', 'Needs verification': 'warn', 'Missing/incomplete': 'miss', Conflicting: 'bad' }
export const StatusBadge = ({ status }) => <span className={`badge ${cls[status] || 'neutral'}`}>{status}</span>

export const StatCard = ({ label, value, tone = '' }) => (
  <div className={`stat ${tone}`}><span>{label}</span><b>{value}</b></div>
)

export const PageHead = ({ title, sub, children }) => (
  <header className="pagehead"><div><h1>{title}</h1>{sub && <p>{sub}</p>}</div><div className="actions">{children}</div></header>
)

export const fmtDate = (d) => new Date(d).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
export const fmtSize = (b) => (b > 1e6 ? (b / 1e6).toFixed(1) + ' MB' : Math.max(1, Math.round(b / 1e3)) + ' KB')

export function useCase() {
  const { id } = useParams()
  const { cases } = useStore()
  return cases.find((c) => String(c.id) === id)
}
export const NoCase = () => <Navigate to="/" replace />

export const Empty = ({ text, to, cta }) => (
  <div className="empty"><p>{text}</p>{to && <Link className="btn" to={to}>{cta}</Link>}</div>
)

export function counts(c) {
  const r = c.requirements
  return {
    total: r.length,
    supported: r.filter((x) => x.status === 'Supported').length,
    verify: r.filter((x) => x.status === 'Needs verification').length,
    missing: r.filter((x) => x.status === 'Missing/incomplete').length,
    conflict: r.filter((x) => x.status === 'Conflicting').length,
  }
}
