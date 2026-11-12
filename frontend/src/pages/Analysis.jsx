import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Sparkles } from 'lucide-react'
import { useStore } from '../store.jsx'
import { PageHead, StatCard, StatusBadge, useCase, NoCase, counts, Empty, fmtDate } from '../components/Bits.jsx'

export default function Analysis() {
  const c = useCase()
  const { runAnalysis, setProjectStatus, user } = useStore()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  if (!c) return <NoCase />

  const k = counts(c)

  const run = async () => {
    setBusy(true)
    setError('')
    try {
      await runAnalysis(c.id)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const submitReview = async () => {
    setBusy(true)
    setError('')
    try {
      await setProjectStatus(c.id, 'under_review')
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const gaps = c.requirements.filter((r) => r.status === 'Missing/incomplete' || r.status === 'Conflicting')

  return (
    <>
      <PageHead
        title="AI Support Analysis"
        sub={c.analyzedAt ? `Last generated ${fmtDate(c.analyzedAt)}` : 'Ready to generate support analysis'}
      >
        <button className="btn" onClick={run} disabled={busy || !c.requirements.length}>
          <Sparkles size={16} /> {busy ? 'Analyzing...' : 'Generate support report'}
        </button>
        {c.analyzedAt && user?.role === 'client' && c.status === 'in_progress' && (
          <button className="ghost" onClick={submitReview} disabled={busy}>
            Submit for support review
          </button>
        )}
      </PageHead>
      {error && <p className="error">{error}</p>}
      {c.requirements.length === 0 ? (
        <Empty
          text="Add listing promises or upload a listing document first so there are specifications to check."
          to={`/cases/${c.id}/agreement`}
          cta="Go to order details"
        />
      ) : (
        <>
          <section className="stats">
            <StatCard label="Supported" value={k.supported} tone="ok" />
            <StatCard label="Needs verification" value={k.verify} tone="warn" />
            <StatCard label="Missing or incomplete" value={k.missing} tone="miss" />
            <StatCard label="Conflicting" value={k.conflict} tone="bad" />
          </section>
          <div className="card">
            <h3>Listing promises vs. Evidence matching</h3>
            <table>
              <thead>
                <tr>
                  <th>Listing Promise</th>
                  <th>Refund Evidence</th>
                  <th>Match</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {c.requirements.map((r) => (
                  <tr key={r.id}>
                    <td><b>{r.id}</b> {r.text}</td>
                    <td>
                      {r.evidenceIds.length
                        ? r.evidenceIds
                            .map((id) => c.evidence.find((e) => e.id === id)?.name)
                            .filter(Boolean)
                            .join(', ')
                        : <span className="muted">None submitted</span>}
                    </td>
                    <td>
                      <div className="meter"><i style={{ width: `${Math.round(r.score * 100)}%` }} /></div>
                      <small>{Math.round(r.score * 100)}%</small>
                    </td>
                    <td><StatusBadge status={r.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="card">
            <h3>Gaps and policy conflicts</h3>
            {gaps.length === 0 ? (
              <p className="muted">No gaps or conflicts found between listing promises and evidence.</p>
            ) : (
              <ul className="gaps">
                {gaps.map((r) => {
                  const ev = c.evidence.filter((e) => e.requirementId === r.id)
                  return (
                    <li key={r.id}>
                      <StatusBadge status={r.status} />
                      <span>
                        <b>{r.id}</b> {r.text}
                        <small>
                          {ev.length
                            ? ev.map((e) => e.note).join(' ')
                            : 'No evidence was submitted for this promised specification.'}
                        </small>
                      </span>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
          <div className="row">
            <Link className="btn" to={`/cases/${c.id}/report`}>
              View customer support report
            </Link>
          </div>
        </>
      )}
    </>
  )
}
