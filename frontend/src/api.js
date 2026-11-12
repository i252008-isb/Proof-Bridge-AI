const BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')
export const USING_BACKEND = true

async function call(path, options = {}) {
  const token = localStorage.getItem('pb_token')
  const headers = { ...(options.body instanceof FormData ? {} : options.body ? { 'Content-Type': 'application/json' } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(options.headers || {}) }
  const res = await fetch(`${BASE}${path}`, { ...options, headers })
  const type = res.headers.get('content-type') || ''
  const body = type.includes('application/json') ? await res.json() : null
  if (!res.ok) throw new Error(body?.error?.message || body?.detail || `Request failed (${res.status})`)
  return body
}

const json = (method, data) => ({ method, body: JSON.stringify(data) })
const statusLabel = (s) => ({ supported: 'Supported', partially_supported: 'Needs verification', contradicted: 'Conflicting', unverified: 'Missing/incomplete', insufficient_evidence: 'Missing/incomplete' }[s] || 'Needs verification')
const formatProject = async (p) => {
  const [requirements, evidence, analysis, history, payment] = await Promise.all([
    call(`/projects/${p.id}/requirements`).catch(() => []),
    call(`/projects/${p.id}/evidence`).catch(() => []),
    call(`/projects/${p.id}/analysis`).catch(() => null),
    call(`/projects/${p.id}/history`).catch(() => ({ events: [] })),
    call(`/projects/${p.id}/payment`).catch(() => null),
  ])
  const findings = analysis?.requirement_findings || []
  const reqs = requirements.map((r) => {
    const f = findings.find((x) => x.requirement_id === r.id)
    return { ...r, status: f ? statusLabel(f.status) : 'Missing/incomplete', score: f?.confidence || 0, evidenceIds: f?.cited_evidence_ids?.map(String) || [] }
  })
  return {
    id: p.id, title: p.title, description: p.description || '', client: `Client #${p.client_id}`, freelancer: `Freelancer #${p.freelancer_id}`,
    freelancerId: p.freelancer_id, clientId: p.client_id, status: p.status, agreement: p.agreement_name ? { name: p.agreement_name, size: 0 } : null,
    amount: p.amount || payment?.amount || null,
    currency: p.currency || payment?.currency || 'USD',
    paypal_order_id: p.paypal_order_id || payment?.order_id || null,
    payment: payment || { payment_state: 'UNPAID', amount: p.amount, currency: p.currency || 'USD' },
    requirements: reqs,
    evidence: evidence.map((e) => { const f = findings.find((x) => x.cited_evidence_ids?.includes(e.id) || x.supporting_evidence_ids?.includes(e.id) || x.contradicting_evidence_ids?.includes(e.id)); return { id: String(e.id), name: e.filename, type: e.mime_type || 'Evidence', size: 0, uploadedAt: e.created_at, status: f ? statusLabel(f.status) : 'Needs verification', score: f?.confidence || 0, requirementId: f?.requirement_id ?? null, note: f?.rationale || 'Not analyzed yet.' } }),
    comments: [], decision: null, analyzedAt: analysis?.generated_at || null,
    timeline: (history.events || []).map((x) => ({ at: x.occurred_at, text: x.summary })), analysis,
  }
}

export const api = {
  register: (name, email, password, role) => call('/auth/register', { ...json('POST', { name, email, password, role }) }),
  login: async (email, password) => {
    const form = new URLSearchParams({ username: email, password })
    const token = await call('/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: form })
    localStorage.setItem('pb_token', token.access_token)
    return call('/auth/me')
  },
  logout: () => call('/auth/logout', { method: 'POST' }),
  listCases: async () => Promise.all((await call('/projects')).map(formatProject)),
  getCase: async (id) => formatProject(await call(`/projects/${id}`)),
  createCase: (data) => call('/projects', { ...json('POST', { title: data.title, description: data.description || null, freelancer_id: Number(data.freelancerId), amount: data.amount ? String(data.amount) : null, currency: data.currency || 'USD' }) }),
  createPayment: (id) => call(`/projects/${id}/payment/create`, { method: 'POST' }),
  capturePayment: (id, token) => call(`/projects/${id}/payment/capture`, { ...json('POST', token ? { token } : {}) }),
  getPayment: (id, refresh = false) => call(`/projects/${id}/payment${refresh ? '?refresh=true' : ''}`),
  uploadAgreement: (id, file) => { const fd = new FormData(); fd.append('file', file); return call(`/projects/${id}/agreement`, { method: 'POST', body: fd }) },
  addRequirement: (id, text) => call(`/projects/${id}/requirements`, { ...json('POST', { text }) }),
  uploadEvidence: (id, file) => { const fd = new FormData(); fd.append('file', file); return call(`/projects/${id}/evidence`, { method: 'POST', body: fd }) },
  runAnalysis: (id) => call(`/projects/${id}/analysis`, { method: 'POST' }),
  createReport: (id) => call(`/projects/${id}/reports`, { method: 'POST' }),
  getReport: (id) => call(`/projects/${id}/reports/latest`),
  decide: (id, decision, notes) => call(`/projects/${id}/reviews`, { ...json('POST', { decision, notes }) }),
  setStatus: (id, status) => call(`/projects/${id}/status`, { ...json('PATCH', { status }) }),
}
