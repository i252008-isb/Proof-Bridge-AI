import { Navigate, Route, Routes } from 'react-router-dom'
import { useStore } from './store.jsx'
import Layout from './components/Layout.jsx'
import Login from './pages/Login.jsx'
import Dashboard from './pages/Dashboard.jsx'
import CreateCase from './pages/CreateCase.jsx'
import Agreement from './pages/Agreement.jsx'
import EvidenceCenter from './pages/EvidenceCenter.jsx'
import Analysis from './pages/Analysis.jsx'
import Report from './pages/Report.jsx'
import HumanReview from './pages/HumanReview.jsx'
import PaymentReturn from './pages/PaymentReturn.jsx'
import PaymentCancel from './pages/PaymentCancel.jsx'

export default function App() {
  const { user } = useStore()
  if (!user) return <Routes><Route path="*" element={<Login />} /></Routes>
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/cases/new" element={<CreateCase />} />
        <Route path="/cases/:id/agreement" element={<Agreement />} />
        <Route path="/cases/:id/evidence" element={<EvidenceCenter />} />
        <Route path="/cases/:id/analysis" element={<Analysis />} />
        <Route path="/cases/:id/report" element={<Report />} />
        <Route path="/cases/:id/review" element={<HumanReview />} />
        <Route path="/payment/return" element={<PaymentReturn />} />
        <Route path="/payment/cancel" element={<PaymentCancel />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
