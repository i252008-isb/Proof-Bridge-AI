import { useRef, useState } from 'react'
import { UploadCloud } from 'lucide-react'

const MAX = 10 * 1024 * 1024
const OK = /\.(pdf|docx|png|jpe?g|webp)$/i

export default function DropZone({ onFiles, accept, multiple, label, busy }) {
  const ref = useRef()
  const [over, setOver] = useState(false)
  const [error, setError] = useState('')
  const handle = (list) => {
    const files = [...list]
    const bad = files.find((f) => !OK.test(f.name) || f.size > MAX)
    if (bad) return setError(`"${bad.name}" was rejected. Use a supported file type under 10 MB.`)
    setError('')
    if (files.length) onFiles(multiple ? files : [files[0]])
  }
  return (
    <>
      <div
        className={`drop ${over ? 'over' : ''}`}
        onClick={() => ref.current.click()}
        onDragOver={(e) => { e.preventDefault(); setOver(true) }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); handle(e.dataTransfer.files) }}
      >
        <UploadCloud size={32} />
        <b>{busy ? 'Uploading...' : label}</b>
        <small>Drag and drop, or click to browse. Max 10 MB per file.</small>
        <input ref={ref} type="file" hidden accept={accept} multiple={multiple} onChange={(e) => { handle(e.target.files); e.target.value = '' }} />
      </div>
      {error && <p className="error">{error}</p>}
    </>
  )
}
