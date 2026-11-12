import { useState } from 'react'
import { Sun, Moon } from 'lucide-react'

const KEY = 'pb-theme'

export default function ThemeToggle({ floating }) {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme || 'dark')
  const toggle = () => {
    const next = theme === 'dark' ? 'light' : 'dark'
    document.documentElement.dataset.theme = next
    try { localStorage.setItem(KEY, next) } catch { /* storage unavailable */ }
    setTheme(next)
  }
  return (
    <button type="button" role="switch" aria-checked={theme === 'light'} aria-label="Switch between dark and light mode"
      title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
      className={`theme-toggle${floating ? ' floating' : ''}`} onClick={toggle}>
      <Moon size={14} /><Sun size={14} /><i />
    </button>
  )
}
