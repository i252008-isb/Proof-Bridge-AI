import { Link } from 'react-router-dom'
import { Printer, ShieldAlert } from 'lucide-react'
import { PageHead, StatusBadge, StatCard, useCase, NoCase, counts, fmtDate, Empty } from '../components/Bits.jsx'
import PaymentStatusCard from '../components/PaymentStatusCard.jsx'

export default function Report() {
  const c = useCase()
  if (!c) return <NoCase />
  if (!c.analyzedAt) return (
    <>
      <PageHead title="Customer Support Report" />
      <Empty text="Generate the support report to view the analysis findings." to={`/cases/${c.id}/analysis`} cta="Go to AI analysis" />
    </>
  )

  const k = counts(c)
  const pct = k.total ? Math.round((k.supported / k.total) * 100) : 0
  const obs = []
  if (k.supported) obs.push(`${k.supported} of ${k.total} promised specifications have supporting evidence.`)
  if (k.conflict) obs.push(`${k.conflict} promised specification(s) have evidence that conflicts with the listing promises.`)
  if (k.missing) obs.push(`${k.missing} promised specification(s) have no submitted evidence.`)
  if (k.verify) obs.push(`${k.verify} promised specification(s) only partly match and need human support check.`)

  return (
    <>
      <PageHead title="Customer Support Report" sub={`${c.title} · Order #${c.id} · generated ${fmtDate(c.analyzedAt)}`}>
        <button className="ghost" onClick={() => window.print()}><Printer size={16} /> Print or save PDF</button>
        <Link className="btn" to={`/cases/${c.id}/review`}>Support decision</Link>
      </PageHead>

      <div className="card" style={{ borderLeft: '4px solid var(--accent)', background: 'var(--card)', marginBottom: '20px' }}>
        <p style={{ margin: 0, fontWeight: 600, display: 'flex', alignItems: 'center', gap: '8px' }}>
          <ShieldAlert size={18} style={{ color: 'var(--accent)' }} />
          AI never moves money. It prepares a factual report for the human support agent. Refunds are processed by a human.
        </p>
      </div>

      <section className="stats">
        <StatCard label="Listing promises verified" value={`${pct}%`} tone={pct >= 70 ? 'ok' : 'warn'} />
        <StatCard label="Evidence files" value={c.evidence.length} />
        <StatCard label="Conflicts" value={k.conflict} tone="bad" />
        <StatCard label="Missing" value={k.missing} tone="miss" />
      </section>

      <section className="grid2">
        <div className="card">
          <h3>Summary</h3>
          <p>
            Buyer ({c.client}) ordered “{c.title}” from Seller ({c.freelancer})
            {(c.amount || c.payment?.amount) ? ` for ${c.amount || c.payment?.amount} ${c.currency || 'USD'}` : ''}.
          </p>
          <h3>Observations</h3>
          <ul className="bullets">{obs.map((o, i) => <li key={i}>{o}</li>)}</ul>
          <p className="muted">
            These findings are advisory and support the customer support agent. They are not an automated refund decision.
          </p>
        </div>
        <PaymentStatusCard project={c} />
      </section>

      <div className="card">
        <h3>Evidence references</h3>
        <table>
          <thead><tr><th>Listing Promise</th><th>Refund Evidence</th><th>Status</th></tr></thead>
          <tbody>
            {c.requirements.map((r) => (
              <tr key={r.id}>
                <td><b>{r.id}</b> {r.text}</td>
                <td>
                  {c.evidence.filter((e) => e.requirementId === r.id).map((e) => (
                    <div key={e.id}>{e.name}<small>{e.note}</small></div>
                  ))}
                  {!r.evidenceIds.length && <span className="muted">No evidence</span>}
                </td>
                <td><StatusBadge status={r.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>Timeline</h3>
        <ul className="timeline">
          {[...c.timeline].sort((a, b) => new Date(a.at) - new Date(b.at)).map((t, i) => (
            <li key={i}><span>{fmtDate(t.at)}</span>{t.text}</li>
          ))}
        </ul>
      </div>
    </>
  )
}
