import { Link } from 'react-router-dom'
import { AlertCircle, ArrowLeft } from 'lucide-react'
import { PageHead } from '../components/Bits.jsx'

export default function PaymentCancel() {
  const projectId = sessionStorage.getItem('pb_paying_project_id')
  const targetLink = projectId ? `/cases/${projectId}/agreement` : '/'

  return (
    <>
      <PageHead title="Payment Cancelled" sub="PayPal checkout was cancelled" />
      <div style={{ maxWidth: '640px', margin: '0 auto' }}>
        <div className="card">
          <h3 style={{ color: 'var(--warn)' }}>
            <AlertCircle size={22} /> Checkout Cancelled
          </h3>
          <p className="muted" style={{ margin: '14px 0 24px' }}>
            You cancelled the PayPal payment process. No charges have been made to your account.
            You can return to the order and try again whenever you are ready.
          </p>
          <div className="row">
            <Link className="btn" to={targetLink}>
              <ArrowLeft size={16} /> Return to Order
            </Link>
          </div>
        </div>
      </div>
    </>
  )
}
