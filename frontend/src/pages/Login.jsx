import { useState } from 'react'
import { ShieldCheck } from 'lucide-react'
import { useStore } from '../store.jsx'
import ThemeToggle from '../components/ThemeToggle.jsx'

export default function Login() {
  const { login } = useStore()
  const [mode, setMode] = useState('login')
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('client')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await login(email, password, mode === 'signup' ? name : undefined, role)
    } catch (err) {
      setError(err.message || 'Could not sign in.')
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <ThemeToggle floating />
      <div className="login-art">
        <ShieldCheck size={44} />
        <h1>Evidence you can check, decisions people make.</h1>
        <p>ProofBridge AI compares product refund evidence against listing promises and gives customer support agents a clear, referenced advisory report.</p>
      </div>
      <form className="login-card" onSubmit={submit}>
        <h2>{mode === 'login' ? 'Log in' : 'Create your account'}</h2>
        {mode === 'signup' && (
          <label>Full name<input required value={name} onChange={(e) => setName(e.target.value)} /></label>
        )}
        {mode === 'signup' && (
          <label>Account type
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="client">Buyer (places orders & requests refunds)</option>
              <option value="freelancer">Seller (lists products)</option>
            </select>
          </label>
        )}
        <label>Email<input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" /></label>
        <label>Password<input required type="password" minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        {error && <p className="error">{error}</p>}
        <button className="btn" disabled={busy}>{busy ? 'Please wait...' : mode === 'login' ? 'Log in' : 'Sign up'}</button>
        <p className="switch">
          {mode === 'login' ? 'New to ProofBridge?' : 'Already registered?'}{' '}
          <a onClick={() => setMode(mode === 'login' ? 'signup' : 'login')}>{mode === 'login' ? 'Create an account' : 'Log in'}</a>
        </p>
        <small className="hint">Create a Buyer or Seller account. Passwords must be at least 8 characters.</small>
      </form>
    </div>
  )
}
