import { NavLink, Outlet, useMatch, Link } from 'react-router-dom'
import { LayoutDashboard, FilePlus2, FileText, FolderOpen, ScanSearch, ClipboardList, UserCheck, LogOut, ShieldCheck } from 'lucide-react'
import { useStore } from '../store.jsx'
import ThemeToggle from './ThemeToggle.jsx'

const ROLE_LABELS = {
  client: 'Buyer',
  freelancer: 'Seller',
  reviewer: 'Support Agent',
}

export default function Layout() {
  const { user, logout, cases } = useStore()
  const m = useMatch('/cases/:id/*')
  const id = m?.params.id
  const current = cases.find((c) => String(c.id) === id)
  const steps = [
    ['agreement', 'Order Details', FileText],
    ['evidence', 'Refund Evidence', FolderOpen],
    ['analysis', 'Generate Report', ScanSearch],
    ['report', 'Support Report', ClipboardList],
    ['review', 'Support Decision', UserCheck],
  ]

  const displayRole = ROLE_LABELS[user?.role] || user?.role || 'User'

  return (
    <div className="shell">
      <header className="topbar">
        <Link to="/" className="brand"><ShieldCheck size={22} /> ProofBridge <span>AI</span></Link>
        <nav className="topnav">
          <NavLink to="/" end><LayoutDashboard size={16} /> Orders</NavLink>
          {user?.role === 'client' && <NavLink to="/cases/new"><FilePlus2 size={16} /> New Order</NavLink>}
        </nav>
        <div className="top-actions">
          <ThemeToggle />
          <div className="who">
            <div className="avatar">{(user?.name || 'U')[0].toUpperCase()}</div>
            <div>
              <b>{user?.name}</b>
              <small>{displayRole} · ID {user?.id}</small>
            </div>
          </div>
          <button className="ghost" onClick={logout}><LogOut size={16} /> Log out</button>
        </div>
      </header>
      <main className="main">
        <div className="notice">
          ProofBridge AI supports refund investigation only. It never moves money, and all refund decisions are made by human support.
        </div>
        {current && (
          <div className="stepbar">
            <div className="nav-group">Order #{current.id}<small>{current.title}</small></div>
            <nav>
              {steps.map(([p, label, Icon]) => (
                <NavLink key={p} to={`/cases/${id}/${p}`}><Icon size={16} /> {label}</NavLink>
              ))}
            </nav>
          </div>
        )}
        <Outlet />
      </main>
    </div>
  )
}
