import { useEffect, useState, useRef } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { CheckCircle2, AlertCircle, ArrowLeft, Loader2 } from 'lucide-react'
import { api } from '../api.js'
import { useStore } from '../store.jsx'
import { PageHead } from '../components/Bits.jsx'

export default function PaymentReturn() {
  const [params] = useSearchParams()
  const token = params.get('token')
  const payerId = params.get('PayerID')
  const { cases, refreshCase } = useStore()

  const [loading, setLoading] = useState(true)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [projectId, setProjectId] = useState(() => {
    return (
      (token && sessionStorage.getItem(`pb_order_${token}`)) ||
      sessionStorage.getItem('pb_paying_project_id') ||
      ''
    )
  })

  const captureRan = useRef(false)

  useEffect(() => {
    let activePid = projectId
    if (!activePid && token && cases.length > 0) {
      const match = cases.find(
        (c) => c.paypal_order_id === token || c.payment?.order_id === token
      )
      if (match) {
        activePid = String(match.id)
        setProjectId(activePid)
      }
    }

    if (!token) {
      setError('Missing PayPal token in the return URL.')
      setLoading(false)
      return
    }

    if (!activePid) {
      setError('Could not locate the order associated with this PayPal payment.')
      setLoading(false)
      return
    }

    if (captureRan.current) return
    captureRan.current = true

    async function executeCapture() {
      setLoading(true)
      setError('')
      try {
        const data = await api.capturePayment(activePid, token)
        setResult(data)
        if (refreshCase) {
          await refreshCase(activePid)
        }
      } catch (err) {
        setError(err.message || 'Failed to capture PayPal payment.')
      } finally {
        setLoading(false)
      }
    }

    executeCapture()
  }, [token, projectId, cases, refreshCase])

  const targetProjectLink = projectId ? `/cases/${projectId}/agreement` : '/'

  return (
    <>
      <PageHead title="Payment Confirmation" sub="PayPal order checkout completion" />
      <div style={{ maxWidth: '640px', margin: '0 auto' }}>
        {loading && (
          <div className="card" style={{ textAlign: 'center', padding: '48px 24px' }}>
            <h3>Processing Payment</h3>
            <p className="muted">Capturing PayPal authorization and verifying transaction...</p>
          </div>
        )}

        {!loading && result && (
          <div className="card">
            <h3 style={{ color: 'var(--ok)' }}>
              <CheckCircle2 size={22} /> Payment Captured Successfully!
            </h3>
            <p className="muted">
              Your payment has been received and verified. The order is now paid.
            </p>
            <dl className="kv" style={{ margin: '20px 0' }}>
              <dt>Payment Status</dt>
              <dd><span className="badge ok">{result.status || 'PAID'}</span></dd>
              <dt>Amount Paid</dt>
              <dd><b>{result.amount} {result.currency}</b></dd>
              <dt>Order ID</dt>
              <dd style={{ fontFamily: 'monospace' }}>{result.order_id || token}</dd>
              {result.capture_id && (
                <>
                  <dt>Capture ID</dt>
                  <dd style={{ fontFamily: 'monospace' }}>{result.capture_id}</dd>
                </>
              )}
            </dl>
            <div className="row" style={{ marginTop: '24px' }}>
              <Link className="btn" to={targetProjectLink}>
                <ArrowLeft size={16} /> Return to Order
              </Link>
            </div>
          </div>
        )}

        {!loading && error && (
          <div className="card">
            <h3 style={{ color: 'var(--bad)' }}>
              <AlertCircle size={22} /> Payment Processing Error
            </h3>
            <p className="error" style={{ margin: '14px 0' }}>{error}</p>
            <p className="muted">
              If your payment was already approved on PayPal, you can check the order status or try again.
            </p>
            <div className="row" style={{ marginTop: '24px' }}>
              <Link className="btn" to={targetProjectLink}>
                <ArrowLeft size={16} /> Return to Order
              </Link>
            </div>
          </div>
        )}
      </div>
    </>
  )
}
