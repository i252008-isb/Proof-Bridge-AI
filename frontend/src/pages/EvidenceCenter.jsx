import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Image, FileText, Code2 } from 'lucide-react'
import { useStore } from '../store.jsx'
import { PageHead, StatusBadge, useCase, NoCase, fmtDate, fmtSize, Empty } from '../components/Bits.jsx'
import DropZone from '../components/DropZone.jsx'

const icon = { Screenshot: Image, Document: FileText, 'Source code': Code2 }

export default function EvidenceCenter() {
  const c = useCase()
  const { uploadEvidence } = useStore()
  const [busy, setBusy] = useState(false)
  const [filter, setFilter] = useState('All')
  const [error, setError] = useState('')

  if (!c) return <NoCase />

  const go = async (files) => {
    setBusy(true)
    setError('')
    try {
      await uploadEvidence(c.id, files)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const list = c.evidence.filter((e) => filter === 'All' || e.status === filter)

  return (
    <>
      <PageHead title="Refund-request evidence" sub={`${c.evidence.length} files submitted for ${c.title} (Order #${c.id})`}>
        <Link className="btn" to={`/cases/${c.id}/analysis`}>
          Generate support report
        </Link>
      </PageHead>
      <div className="card">
        <h3>Upload refund-request evidence</h3>
        <p className="muted" style={{ marginBottom: '14px' }}>
          Upload product photos (damages, defects), receipts, delivery confirmation, or seller chat messages.
        </p>
        <DropZone multiple label="Upload photos, receipts, or chat screenshots" onFiles={go} busy={busy} />
        {error && <p className="error">{error}</p>}
      </div>
      <div className="card">
        <div className="between">
          <h3>Submitted evidence</h3>
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            {['All', 'Supported', 'Needs verification', 'Missing/incomplete', 'Conflicting'].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </div>
        {list.length === 0 ? (
          <Empty text="No refund evidence matches this view. Upload files above." />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Evidence File</th>
                <th>Type</th>
                <th>Listing Promise</th>
                <th>AI Advisory Finding</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {list.map((e) => {
                const I = icon[e.type] || FileText
                return (
                  <tr key={e.id}>
                    <td className="fname">
                      <I size={18} />
                      <div>
                        <b>{e.name}</b>
                        <small>{fmtSize(e.size)} · {fmtDate(e.uploadedAt)}</small>
                      </div>
                    </td>
                    <td>{e.type}</td>
                    <td>{e.requirementId || 'Not linked'}</td>
                    <td className="note">{e.note}</td>
                    <td><StatusBadge status={e.status} /></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
