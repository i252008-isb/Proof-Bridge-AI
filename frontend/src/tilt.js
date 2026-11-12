// Adds a gentle 3D tilt to cards and stat tiles. Purely visual; no layout changes.
const SEL = '.card, .stat'
const MAX = 5
export function initTilt() {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
  document.addEventListener('mousemove', (e) => {
    const el = e.target.closest?.(SEL)
    document.querySelectorAll('.tilt-on').forEach((n) => { if (n !== el) reset(n) })
    if (!el || el.matches('.card:has(table), .card:has(form)')) return
    const r = el.getBoundingClientRect()
    const x = (e.clientX - r.left) / r.width - 0.5
    const y = (e.clientY - r.top) / r.height - 0.5
    el.classList.add('tilt-on')
    el.style.setProperty('--ry', `${x * MAX * 2}deg`)
    el.style.setProperty('--rx', `${-y * MAX * 2}deg`)
  })
  document.addEventListener('mouseleave', () => document.querySelectorAll('.tilt-on').forEach(reset))
}
function reset(n) { n.classList.remove('tilt-on'); n.style.removeProperty('--rx'); n.style.removeProperty('--ry') }
