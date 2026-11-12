import { createContext, useContext, useEffect, useState } from 'react'
import { api } from './api.js'

export const STATUSES = ['Supported', 'Needs verification', 'Missing/incomplete', 'Conflicting']
const Ctx = createContext(null)
export const useStore = () => useContext(Ctx)

const now = () => new Date().toISOString()

const seed = [
  {
    id: 'PB-1001',
    title: 'E-commerce Website Redesign',
    client: 'Acme Trading Co.',
    freelancer: 'Sara Khan',
    budget: 1200,
    currency: 'USD',
    deadline: '2026-11-20',
    description: 'Full redesign and build of the Acme online store.',
    status: 'In review',
    agreement: { name: 'acme-contract.pdf', size: 184000 },
    requirements: [
      { id: 'R1', text: 'Responsive homepage with hero section and product grid', status: 'Supported', score: 0.93, evidenceIds: ['E1'] },
      { id: 'R2', text: 'User registration and login with email verification', status: 'Needs verification', score: 0.64, evidenceIds: ['E2'] },
      { id: 'R3', text: 'Shopping cart and checkout flow', status: 'Conflicting', score: 0.48, evidenceIds: ['E3'] },
      { id: 'R4', text: 'Admin dashboard to manage products and orders', status: 'Missing/incomplete', score: 0.12, evidenceIds: [] },
      { id: 'R5', text: 'PayPal payment integration', status: 'Supported', score: 0.88, evidenceIds: ['E4'] },
    ],
    evidence: [
      { id: 'E1', name: 'homepage-screenshot.png', type: 'Screenshot', size: 412000, uploadedAt: '2026-11-08T10:12:00Z', status: 'Supported', score: 0.93, requirementId: 'R1', note: 'OCR found "Shop now" hero text and a 3-column product grid.' },
      { id: 'E2', name: 'signup-flow.png', type: 'Screenshot', size: 288000, uploadedAt: '2026-11-08T10:15:00Z', status: 'Needs verification', score: 0.64, requirementId: 'R2', note: 'Signup form shown, but no email verification step is visible.' },
      { id: 'E3', name: 'checkout-notes.docx', type: 'Document', size: 51000, uploadedAt: '2026-11-09T09:02:00Z', status: 'Conflicting', score: 0.48, requirementId: 'R3', note: 'Notes say guest checkout only; the agreement requires a saved cart for logged-in users.' },
      { id: 'E4', name: 'paypal-sandbox-payment.png', type: 'Screenshot', size: 310000, uploadedAt: '2026-11-09T11:40:00Z', status: 'Supported', score: 0.88, requirementId: 'R5', note: 'Sandbox payment confirmation matches the PayPal requirement.' },
    ],
    paypal: { transactionId: '8XJ12345AB678901C', amount: 600, currency: 'USD', status: 'COMPLETED', date: '2026-11-05', payer: 'buyer@acme-sandbox.test', note: 'Milestone 1 deposit (sandbox)' },
    comments: [
      { id: 'C1', author: 'Client', role: 'Client', text: 'We could not find the admin dashboard in the demo.', at: '2026-11-09T14:00:00Z', attachment: null },
    ],
    decision: null,
    analyzedAt: '2026-11-09T12:00:00Z',
    timeline: [
      { at: '2026-11-05T08:00:00Z', text: 'Case created' },
      { at: '2026-11-05T08:30:00Z', text: 'Agreement uploaded: acme-contract.pdf' },
      { at: '2026-11-05T08:31:00Z', text: 'AI extracted 5 requirements' },
      { at: '2026-11-08T10:12:00Z', text: 'Evidence uploaded: homepage-screenshot.png' },
      { at: '2026-11-09T12:00:00Z', text: 'AI analysis completed' },
    ],
  },
]

// Deterministic fake classification used only when the backend/AI is not connected.
function fakeClassify(name) {
  let h = 0
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0
  const status = ['Supported', 'Supported', 'Needs verification', 'Conflicting'][h % 4]
  const score = { Supported: 0.82, 'Needs verification': 0.6, Conflicting: 0.45 }[status] + (h % 10) / 100
  return { status, score: Math.min(score, 0.97) }
}
const fileType = (n) => (/\.(png|jpe?g|webp)$/i.test(n) ? 'Screenshot' : /\.(js|jsx|py|ts|zip|java|html|css)$/i.test(n) ? 'Source code' : 'Document')

export function StoreProvider({ children }) {
  const [user, setUser] = useState(() => JSON.parse(localStorage.getItem('pb_user') || 'null'))
  const [cases, setCases] = useState(() => JSON.parse(localStorage.getItem('pb_cases') || 'null') || [])

  useEffect(() => { localStorage.setItem('pb_cases', JSON.stringify(cases)) }, [cases])
  useEffect(() => {
    if (localStorage.getItem('pb_token')) api.listCases().then(setCases).catch((e) => console.warn('Could not load projects:', e.message))
  }, [])

  const update = (id, fn) => setCases((cs) => cs.map((c) => (c.id === id ? fn(c) : c)))
  const addEvent = (c, text) => ({ ...c, timeline: [...c.timeline, { at: now(), text }] })

  const login = async (email, password, name, role) => {
    if (name) await api.register(name, email, password, role)
    const u = await api.login(email, password)
    localStorage.setItem('pb_user', JSON.stringify(u))
    setUser(u)
    setCases(await api.listCases())
  }
  const logout = () => { api.logout().catch(() => {}); localStorage.removeItem('pb_token'); localStorage.removeItem('pb_user'); localStorage.removeItem('pb_cases'); setUser(null); setCases([]) }

  const createCase = async (data) => {
    const remote = await api.createCase(data)
    const id = remote.id
    const c = {
      ...remote, id, ...data, freelancerId: remote.freelancer_id, clientId: remote.client_id, budget: Number(data.amount) || Number(data.budget) || 0,
      amount: remote.amount || (data.amount ? String(data.amount) : null),
      currency: remote.currency || data.currency || 'USD',
      payment: { payment_state: 'UNPAID', amount: remote.amount || (data.amount ? String(data.amount) : null), currency: remote.currency || data.currency || 'USD' },
      status: remote.status,
      agreement: null, requirements: [], evidence: [], paypal: null, comments: [], decision: null, analyzedAt: null,
      timeline: [{ at: now(), text: 'Order created' }],
    }
    setCases((cs) => [c, ...cs])
    return id
  }

  const refreshCase = async (id) => {
    const fresh = await api.getCase(id)
    update(id, (c) => ({ ...c, ...fresh }))
    return fresh
  }

  const uploadAgreement = async (id, file) => {
    await api.uploadAgreement(id, file)
    const fresh = await api.getCase(id)
    update(id, (c) => ({ ...c, ...fresh, agreement: { name: file.name, size: file.size }, timeline: [...c.timeline, { at: now(), text: `Agreement uploaded: ${file.name}` }] }))
  }

  const addRequirement = async (id, text) => { await api.addRequirement(id, text); const fresh = await api.getCase(id); update(id, (c) => ({ ...c, ...fresh })) }

  const uploadEvidence = async (id, files) => {
    for (const file of files) {
      const uploaded = await api.uploadEvidence(id, file)
      update(id, (c) => {
        const ev = {
          id: String(uploaded.id), name: uploaded.filename, type: uploaded.mime_type || fileType(file.name), size: file.size,
          uploadedAt: now(), status: 'Needs verification', score: 0, requirementId: null, note: 'Not analyzed yet. Run AI analysis.',
        }
        return addEvent({ ...c, evidence: [...c.evidence, ev] }, `Evidence uploaded: ${file.name}`)
      })
    }
  }

  const runAnalysis = async (id) => {
    await api.runAnalysis(id)
    await api.createReport(id)
    const fresh = await api.getCase(id)
    update(id, (c) => ({ ...c, ...fresh }))
  }

  const addComment = () => {}

  const setDecision = async (id, decision, rationale) => {
    const mapped = { 'Work accepted as delivered': 'verified', 'Request more evidence': 'needs_more_evidence', 'Partially accepted, needs rework': 'partially_verified', 'Escalate to mediation': 'rejected' }[decision] || decision
    await api.decide(id, mapped, rationale)
    setCases(await api.listCases())
  }

  const setProjectStatus = async (id, status) => { await api.setStatus(id, status); const fresh = await api.getCase(id); update(id, (c) => ({ ...c, ...fresh })) }

  const linkPaypal = (id, p) => update(id, (c) => addEvent({ ...c, paypal: p }, 'PayPal transaction linked'))

  const resetDemo = () => { setCases([]); localStorage.removeItem('pb_cases') }

  return (
    <Ctx.Provider value={{ user, login, logout, cases, createCase, refreshCase, uploadAgreement, addRequirement, uploadEvidence, runAnalysis, addComment, setDecision, setProjectStatus, linkPaypal, resetDemo }}>
      {children}
    </Ctx.Provider>
  )
}
