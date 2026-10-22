import React, { useState, useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import { CloudUpload, FileCode2, FileDown, FolderOpen, ShieldCheck, Sparkles, CheckCircle2, AlertCircle, RefreshCw } from 'lucide-react'
import './style.css'

function App() {
  const [files, setFiles] = useState([])
  const [format, setFormat] = useState('html')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [isError, setIsError] = useState(false)
  const [backendOnline, setBackendOnline] = useState(null)
  const [dragOver, setDragOver] = useState(false)

  const apiBase = (window.location.port === '8000' || window.location.port === '5173')
    ? ''
    : 'http://127.0.0.1:8000'

  useEffect(() => {
    checkHealth()
    const timer = setInterval(checkHealth, 8000)
    return () => clearInterval(timer)
  }, [])

  async function checkHealth() {
    try {
      const res = await fetch(`${apiBase}/api/health`, { signal: AbortSignal.timeout(3000) })
      if (res.ok) {
        setBackendOnline(true)
      } else {
        setBackendOnline(false)
      }
    } catch {
      setBackendOnline(false)
    }
  }

  function addFiles(list) {
    const selected = Array.from(list || [])
    const valid = selected.filter(file => file.name.toLowerCase().endsWith('.ipynb'))
    setFiles(current => {
      const combined = [...current, ...valid]
      const unique = []
      const names = new Set()
      for (const f of combined) {
        if (!names.has(f.name)) {
          names.add(f.name)
          unique.push(f)
        }
      }
      return unique.slice(0, 20)
    })

    if (selected.length !== valid.length) {
      setMessage('Only .ipynb notebook files are accepted.')
      setIsError(true)
    } else {
      setMessage('')
      setIsError(false)
    }
  }

  function handleDrop(e) {
    e.preventDefault()
    setDragOver(false)
    if (e.dataTransfer?.files?.length) {
      addFiles(e.dataTransfer.files)
    }
  }

  function handleDragOver(e) {
    e.preventDefault()
    setDragOver(true)
  }

  function handleDragLeave(e) {
    e.preventDefault()
    setDragOver(false)
  }

  async function convert() {
    if (!files.length) {
      setMessage('Choose at least one .ipynb file first.')
      setIsError(true)
      return
    }
    setBusy(true)
    setIsError(false)
    setMessage(`Converting ${files.length} notebook${files.length > 1 ? 's' : ''} to ${format.toUpperCase()}... Please wait.`)
    try {
      const form = new FormData()
      files.forEach(file => form.append('files', file))
      form.append('output_format', format)

      const response = await fetch(`${apiBase}/api/convert-zip`, {
        method: 'POST',
        body: form,
      })

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}))
        throw new Error(errData.detail || `Conversion failed with status ${response.status}.`)
      }

      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `converted_notebooks_${format}.zip`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)

      setIsError(false)
      setMessage(`Successfully converted & downloaded ${files.length} file${files.length > 1 ? 's' : ''} as ZIP!`)
    } catch (error) {
      setIsError(true)
      setMessage(`${error.message} (Is the FastAPI backend running on port 8000?)`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="page">
      <nav className="nav">
        <div className="brand">
          <span className="brand-icon"><FileCode2 size={20}/></span>
          Notebook<span>Flow</span>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <div
            className="nav-pill"
            style={{
              borderColor: backendOnline === true ? '#234e32' : backendOnline === false ? '#5c2b2b' : '#29344d',
              background: backendOnline === true ? '#0e2316' : backendOnline === false ? '#291414' : '#141c30',
              color: backendOnline === true ? '#4ade80' : backendOnline === false ? '#f87171' : '#a9b8d2',
              cursor: 'pointer'
            }}
            onClick={checkHealth}
            title="Click to check backend status"
          >
            {backendOnline === true ? (
              <><CheckCircle2 size={14}/> Backend Ready (Port 8000)</>
            ) : backendOnline === false ? (
              <><AlertCircle size={14}/> Backend Offline</>
            ) : (
              <><RefreshCw size={14} className="spin"/> Checking Backend...</>
            )}
          </div>
          <div className="nav-pill"><ShieldCheck size={15}/> Private by design</div>
        </div>
      </nav>

      <section className="hero">
        <div className="eyebrow"><Sparkles size={15}/> NOTEBOOK EXPORT STUDIO</div>
        <h1>Your notebooks,<br/><span>ready to share.</span></h1>
        <p className="sub">Convert Jupyter notebooks (.ipynb) to polished HTML or PDF files, then download everything in one convenient ZIP archive.</p>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Convert notebooks</h2>
            <p>Upload or drag & drop one or more .ipynb files.</p>
          </div>
          <span className="step">STEP 01</span>
        </div>

        <label
          className={`dropzone ${dragOver ? 'dropzone-active' : ''}`}
          htmlFor="files"
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
        >
          <span className="upload-icon"><CloudUpload size={27}/></span>
          <strong>Drop notebook files here</strong>
          <span className="muted">or click to browse · up to 20 files</span>
          <span className="browse">Choose files</span>
          <input
            id="files"
            type="file"
            accept=".ipynb,application/json"
            multiple
            onChange={e => addFiles(e.target.files)}
          />
        </label>

        {files.length > 0 && (
          <div className="file-list">
            <div className="file-list-title">
              <FolderOpen size={16}/> Selected files <span>{files.length}/20</span>
            </div>
            {files.map((file, i) => (
              <div className="file-row" key={`${file.name}-${i}`}>
                <FileCode2 size={17}/>
                <span>{file.name}</span>
                <small>{(file.size / 1024).toFixed(0)} KB</small>
                <button
                  className="remove"
                  onClick={() => setFiles(current => current.filter((_, index) => index !== i))}
                  aria-label={`Remove ${file.name}`}
                >
                  ×
                </button>
              </div>
            ))}
            <button className="clear" onClick={() => setFiles([])}>Clear selection</button>
          </div>
        )}

        <div className="format-title">Choose output format <span>All files will be packed into a ZIP</span></div>
        <div className="formats">
          <button
            type="button"
            className={`format-card ${format === 'html' ? 'selected' : ''}`}
            onClick={() => setFormat('html')}
          >
            <span className="format-icon html">‹/›</span>
            <span><strong>HTML</strong><small>Share & view in any web browser</small></span>
            <span className="radio">{format === 'html' ? '●' : '○'}</span>
          </button>
          <button
            type="button"
            className={`format-card ${format === 'pdf' ? 'selected' : ''}`}
            onClick={() => setFormat('pdf')}
          >
            <span className="format-icon pdf"><FileDown size={21}/></span>
            <span><strong>PDF</strong><small>Clean print-ready document</small></span>
            <span className="radio">{format === 'pdf' ? '●' : '○'}</span>
          </button>
        </div>

        <button className="convert" disabled={busy || files.length === 0} onClick={convert}>
          {busy ? (
            <>
              <RefreshCw size={18} className="spin" /> Converting {files.length} file{files.length > 1 ? 's' : ''}…
            </>
          ) : (
            <>Convert & download ZIP <FileDown size={18}/></>
          )}
        </button>

        {message && (
          <p
            className="message"
            role="status"
            style={{
              color: isError ? '#f87171' : '#4ade80',
              background: isError ? 'rgba(239, 68, 68, 0.1)' : 'rgba(34, 197, 94, 0.1)',
              padding: '10px 14px',
              borderRadius: '8px',
              border: `1px solid ${isError ? 'rgba(239, 68, 68, 0.2)' : 'rgba(34, 197, 94, 0.2)'}`
            }}
          >
            {message}
          </p>
        )}

        <p className="privacy">
          <ShieldCheck size={14}/> Files are processed securely in temporary storage and removed immediately after conversion.
        </p>
      </section>

      <section className="drive-card">
        <div className="drive-symbol">G</div>
        <div className="drive-copy">
          <h3>Have notebooks in Google Colab?</h3>
          <p>Download your Colab notebooks as <code>.ipynb</code> and drop them above, or connect Google Drive in future releases.</p>
        </div>
        <span className="coming">READY</span>
      </section>
      <footer>NotebookFlow · Built for students, researchers, and developers</footer>
    </main>
  )
}

createRoot(document.getElementById('root')).render(<App />)
