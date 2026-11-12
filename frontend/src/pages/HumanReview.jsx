import { useState } from 'react'
import { useStore } from '../store.jsx'
import { PageHead, StatusBadge, useCase, NoCase, counts } from '../components/Bits.jsx'

const DECISIONS = ['needs_more_evidence', 'rejected', 'partially_verified', 'verified']
const LABELS = {
  needs_more_evidence: 'Needs more evidence from buyer',
  rejected: 'Full refund recommended',
  partially_verified: 'Partial refund recommended',
  verified: 'Refund not supported (Listing promises fulfilled)',
}

export default function HumanReview() {
  const c = useCase()
  const { setDecision, user } = useStore()
  const [decision, setValue] = useState('needs_more_evidence')
  const [notes, setNotes] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  if (!c) return <NoCase />

  const k = counts(c)

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await setDecision(c.id, decision, notes)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHead
        title="Customer Support Decision"
        sub="AI findings are advisory. The customer support agent reviews the report and records the case decision."
      />
      <section className="grid2">
        <div className="card">
          <h3>Advisory findings to review</h3>
          <ul className="gaps">
            {c.requirements.map((r) => (
              <li key={r.id}>
                <StatusBadge status={r.status} />
                <span><b>{r.id}</b> {r.text}</span>
              </li>
            ))}
          </ul>
          <p className="muted">
            {k.supported} supported, {k.verify} to verify, {k.missing} missing, {k.conflict} conflicting.
          </p>
          <div className="hint" style={{ marginTop: '16px' }}>
            AI never moves money. Refund execution is performed by a human operator using the offline refund script.
          </div>
        </div>
        <div className="card">
          <h3>Support Decision</h3>
          {user?.role !== 'reviewer' ? (
            <p className="muted">
              Only a provisioned support agent (reviewer) account can record a support decision.
            </p>
          ) : c.status !== 'under_review' ? (
            <p className="muted">
              This order must be submitted for support review first. The buyer can do that from the AI Analysis page.
            </p>
          ) : (
            <form className="form" onSubmit={submit}>
              <label className="span2">
                Support Recommendation / Decision
                <select value={decision} onChange={(e) => setValue(e.target.value)}>
                  {DECISIONS.map((d) => (
                    <option value={d} key={d}>{LABELS[d]}</option>
                  ))}
                </select>
              </label>
              <label className="span2">
                Support agent notes & rationale (10–5000 characters)
                <textarea
                  required
                  minLength={10}
                  maxLength={5000}
                  rows={5}
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Explain why the refund was recommended, partially recommended, or denied based on the listing promises and evidence."
                />
              </label>
              {error && <p className="error span2">{error}</p>}
              <div className="span2">
                <button className="btn" disabled={busy}>
                  {busy ? 'Recording…' : 'Record support decision'}
                </button>
              </div>
            </form>
          )}
        </div>
      </section>
    </>
  )
}
