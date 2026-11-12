import { useState } from 'react'
import { Link } from 'react-router-dom'
import { FileText, CheckCircle2 } from 'lucide-react'
import { useStore } from '../store.jsx'
import { PageHead, useCase, NoCase, fmtSize } from '../components/Bits.jsx'
import DropZone from '../components/DropZone.jsx'
import PaymentStatusCard from '../components/PaymentStatusCard.jsx'

export default function Agreement() {
  const c = useCase()
  const { uploadAgreement, addRequirement, setProjectStatus, user } = useStore()
  const [busy, setBusy] = useState(false)
  const [requirement, setRequirement] = useState('')
  const [error, setError] = useState('')

  const startWork = async () => {
    setError('')
    try {
      await setProjectStatus(c.id, 'in_progress')
    } catch (e) {
      setError(e.message)
    }
  }

  if (!c) return <NoCase />

  const go = async ([file]) => {
    setBusy(true)
    setError('')
    try {
      await uploadAgreement(c.id, file)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const add = async (e) => {
    e.preventDefault()
    setError('')
    try {
      await addRequirement(c.id, requirement)
      setRequirement('')
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <>
      <PageHead title="Order and listing details" sub={`${c.title} (#${c.id})`}>
        {c.requirements.length > 0 && (
          <Link className="btn" to={`/cases/${c.id}/evidence`}>
            Continue to refund evidence
          </Link>
        )}
        {user?.role === 'client' && c.status === 'created' && (
          <button className="ghost" onClick={startWork}>
            Mark order in progress
          </button>
        )}
      </PageHead>

      <div style={{ marginBottom: '20px' }}>
        <PaymentStatusCard project={c} />
      </div>

      <section className="grid2">
        <div className="card">
          <h3>Listing document or receipt</h3>
          <DropZone
            label={c.agreement ? 'Replace listing document' : 'Upload product listing or receipt'}
            onFiles={go}
            busy={busy}
            accept=".pdf,.docx,.png,.jpg,.jpeg,.webp"
          />
          {c.agreement && (
            <div className="file">
              <FileText size={18} />
              <div>
                <b>{c.agreement.name}</b>
                <small>{fmtSize(c.agreement.size)}</small>
              </div>
            </div>
          )}
          {busy && <p className="hint">Uploading listing document...</p>}
          {error && <p className="error">{error}</p>}
        </div>
        <div className="card">
          <h3>What the listing promised</h3>
          <p className="muted">
            The backend stores the listing details. Add promises or specifications below for AI verification.
          </p>
          <form className="compose" onSubmit={add}>
            <textarea
              required
              minLength="10"
              maxLength="2000"
              rows="3"
              value={requirement}
              onChange={(e) => setRequirement(e.target.value)}
              placeholder="e.g. Brand new in sealed box, 1-year warranty included, includes charger."
            />
            <button className="btn" disabled={!c.agreement}>
              Add promised specification
            </button>
          </form>
          {c.requirements.length > 0 && (
            <ol className="reqs">
              {c.requirements.map((r) => (
                <li key={r.id}>
                  <CheckCircle2 size={16} />
                  <span><b>{r.id}</b> {r.text}</span>
                </li>
              ))}
            </ol>
          )}
          {c.requirements.length > 0 && (
            <Link className="btn" to={`/cases/${c.id}/evidence`}>
              Continue to refund evidence
            </Link>
          )}
        </div>
      </section>
    </>
  )
}
