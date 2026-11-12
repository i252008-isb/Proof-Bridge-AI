import { useState } from 'react'
import { Wallet, CheckCircle2, AlertCircle } from 'lucide-react'
import { api } from '../api.js'
import { useStore } from '../store.jsx'

export default function PaymentStatusCard({ project }) {
  const { user } = useStore()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  if (!project) return null

  const payment = project.payment || {}
  const state = payment.payment_state || 'UNPAID'
  const amount = payment.amount || project.amount || '0.00'
  const currency = payment.currency || project.currency || 'USD'
  const orderId = payment.order_id || project.paypal_order_id
  const captureId = payment.capture_id

  const isPaid = state === 'PAID'
  const isBuyer = user?.role === 'client'

  const handlePay = async () => {
    setLoading(true)
    setError('')
    try {
      sessionStorage.setItem('pb_paying_project_id', String(project.id))
      const res = await api.createPayment(project.id)
      if (res.order_id) {
        sessionStorage.setItem(`pb_order_${res.order_id}`, String(project.id))
      }
      if (res.approval_link) {
        window.location.href = res.approval_link
      } else {
        throw new Error('No PayPal approval link received from server.')
      }
    } catch (err) {
      setError(err.message || 'Payment initiation failed.')
      setLoading(false)
    }
  }

  const badgeTone = isPaid ? 'ok' : state === 'FAILED' ? 'bad' : 'warn'

  return (
    <div className="card">
      <h3><Wallet size={16} /> Payment Status</h3>
      <dl className="kv">
        <dt>Status</dt>
        <dd><span className={`badge ${badgeTone}`}>{state}</span></dd>
        <dt>Amount</dt>
        <dd><b>{amount} {currency}</b></dd>
        {orderId && (
          <>
            <dt>Order ID</dt>
            <dd style={{ fontFamily: 'monospace', fontSize: '13px' }}>{orderId}</dd>
          </>
        )}
        {captureId && (
          <>
            <dt>Capture ID</dt>
            <dd style={{ fontFamily: 'monospace', fontSize: '13px' }}>{captureId}</dd>
          </>
        )}
      </dl>

      {error && <p className="error" style={{ marginTop: '12px' }}>{error}</p>}

      {!isPaid && isBuyer && (
        <div style={{ marginTop: '16px' }}>
          <button className="btn" onClick={handlePay} disabled={loading}>
            {loading ? 'Connecting to PayPal...' : 'Pay with PayPal'}
          </button>
          <small style={{ marginTop: '8px' }}>
            Redirects to PayPal Sandbox to approve the order payment.
          </small>
        </div>
      )}

      {isPaid && (
        <p className="hint" style={{ marginTop: '14px', color: 'var(--ok)', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <CheckCircle2 size={16} /> Payment captured and verified via PayPal Sandbox.
        </p>
      )}
    </div>
  )
}
