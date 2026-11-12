import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStore } from '../store.jsx'
import { PageHead } from '../components/Bits.jsx'

export default function CreateCase() {
  const { createCase } = useStore()
  const nav = useNavigate()
  const [f, setF] = useState({
    title: '',
    freelancerId: '',
    amount: '50.00',
    currency: 'USD',
    description: '',
  })
  const [error, setError] = useState('')
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    try {
      const id = await createCase(f)
      nav(`/cases/${id}/agreement`)
    } catch (err) {
      setError(err.message || 'Could not create order.')
    }
  }

  return (
    <>
      <PageHead
        title="Create order"
        sub="Create an order, then review listing details and complete payment."
      />
      <form className="card form" onSubmit={submit}>
        <label className="span2">
          Product title
          <input
            required
            value={f.title}
            onChange={set('title')}
            placeholder="e.g. Mechanical Gaming Keyboard RGB"
          />
        </label>
        <label>
          Seller account ID
          <input
            required
            type="number"
            min="1"
            value={f.freelancerId}
            onChange={set('freelancerId')}
            placeholder="Ask the seller for their account ID"
          />
        </label>
        <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '12px' }}>
          <label>
            Price
            <input
              required
              type="number"
              step="0.01"
              min="0.01"
              value={f.amount}
              onChange={set('amount')}
              placeholder="50.00"
            />
          </label>
          <label>
            Currency
            <select value={f.currency} onChange={set('currency')}>
              <option value="USD">USD</option>
              <option value="EUR">EUR</option>
              <option value="GBP">GBP</option>
            </select>
          </label>
        </div>
        <label className="span2">
          Listing description / promises
          <textarea
            rows="4"
            value={f.description}
            onChange={set('description')}
            placeholder="What did the seller promise for this product? (specifications, warranty, accessories included)"
          />
        </label>
        {error && <p className="error span2">{error}</p>}
        <div className="span2 row">
          <button className="btn">Create order and continue</button>
          <button type="button" className="ghost" onClick={() => nav('/')}>Cancel</button>
        </div>
      </form>
    </>
  )
}
