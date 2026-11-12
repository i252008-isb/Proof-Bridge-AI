import { Link, useNavigate } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { useStore } from '../store.jsx'
import { PageHead, StatCard, counts, fmtDate } from '../components/Bits.jsx'

export default function Dashboard() {
  const { cases, user } = useStore()
  const nav = useNavigate()
  const all = cases.flatMap((c) => c.requirements)
  const activity = cases
    .flatMap((c) => c.timeline.map((t) => ({ ...t, case: c.id })))
    .sort((a, b) => new Date(b.at) - new Date(a.at))
    .slice(0, 8)

  return (
    <>
      <PageHead title="Orders Dashboard" sub="Orders and refund cases assigned to your account.">
        {user?.role === 'client' && (
          <button className="btn" onClick={() => nav('/cases/new')}>
            <Plus size={16} /> New Order
          </button>
        )}
      </PageHead>
      <section className="stats">
        <StatCard label="Total orders" value={cases.length} />
        <StatCard label="Promises verified" value={all.filter((r) => r.status === 'Supported').length} tone="ok" />
        <StatCard label="Need verification" value={all.filter((r) => r.status === 'Needs verification').length} tone="warn" />
        <StatCard label="Missing or conflicting" value={all.filter((r) => r.status === 'Missing/incomplete' || r.status === 'Conflicting').length} tone="bad" />
      </section>
      <section className="grid2">
        <div className="card">
          <h3>Orders</h3>
          {cases.length === 0 ? (
            <p className="muted">No orders are assigned to this account yet.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Order</th>
                  <th>Parties</th>
                  <th>Payment</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {cases.map((c) => {
                  const payState = c.payment?.payment_state || (c.status === 'paid' ? 'PAID' : 'UNPAID')
                  const payBadgeClass = payState === 'PAID' ? 'ok' : 'warn'
                  return (
                    <tr
                      key={c.id}
                      className="click"
                      onClick={() => nav(`/cases/${c.id}/${c.agreement ? 'analysis' : 'agreement'}`)}
                    >
                      <td>
                        <b>{c.title}</b>
                        <small>Order #{c.id}</small>
                      </td>
                      <td>
                        <span>Buyer: #{c.clientId || c.client}</span>
                        <small>Seller: #{c.freelancerId || c.freelancer}</small>
                      </td>
                      <td>
                        <span className={`badge ${payBadgeClass}`}>{payState}</span>
                        {(c.amount || c.payment?.amount) && (
                          <small>{c.amount || c.payment?.amount} {c.currency || 'USD'}</small>
                        )}
                      </td>
                      <td><span className="badge neutral">{c.status}</span></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
        <div className="card">
          <h3>Recent activity</h3>
          <ul className="activity">
            {activity.map((a, i) => (
              <li key={i}>
                <Link to={`/cases/${a.case}/report`}>Order #{a.case}</Link> {a.text}
                <small>{fmtDate(a.at)}</small>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </>
  )
}
