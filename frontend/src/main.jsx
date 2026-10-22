import React, { useState, useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import {
  CloudUpload,
  FileCode2,
  FileDown,
  FolderOpen,
  ShieldCheck,
  Sparkles,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  Search,
  CheckSquare,
  Square,
  LogOut,
  Laptop,
  HardDrive
} from 'lucide-react'
import './style.css'

// Resolve API base URL: from Vite env var, or fallback based on current host
const ENV_API_URL = import.meta.env.VITE_API_BASE_URL || ''
const API_BASE = ENV_API_URL || (
  (window.location.port === '8000' || window.location.port === '5173')
    ? ''
    : 'http://127.0.0.1:8000'
)

function formatDate(isoStr) {
  if (!isoStr) return ''
  try {
    const d = new Date(isoStr)
    return d.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric'
    })
  } catch {
    return ''
  }
}

function formatBytes(bytes) {
  if (!bytes) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function App() {
  // Navigation & Import tab
  const [activeTab, setActiveTab] = useState('local') // 'local' | 'drive'

  // Local Upload State
  const [localFiles, setLocalFiles] = useState([])
  const [dragOver, setDragOver] = useState(false)

  // Output format & Global processing state
  const [format, setFormat] = useState('html')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [isError, setIsError] = useState(false)
  const [backendOnline, setBackendOnline] = useState(null)

  // Google Drive State
  const [driveConnected, setDriveConnected] = useState(false)
  const [driveEmail, setDriveEmail] = useState(null)
  const [driveLoading, setDriveLoading] = useState(false)
  const [driveNotebooks, setDriveNotebooks] = useState([])
  const [driveSelectedIds, setDriveSelectedIds] = useState(new Set())
  const [driveSearch, setDriveSearch] = useState('')
  const [driveNextPageToken, setDriveNextPageToken] = useState(null)
  const [driveConfigured, setDriveConfigured] = useState(true)

  useEffect(() => {
    checkHealth()
    checkDriveStatus()

    // Handle OAuth redirect return
    const params = new URLSearchParams(window.location.search)
    if (params.get('drive_connected') === '1') {
      setActiveTab('drive')
      setMessage('Google Drive connected successfully!')
      setIsError(false)
      window.history.replaceState({}, document.title, window.location.pathname)
      fetchDriveNotebooks('', null, false)
    } else if (params.get('drive_error')) {
      setActiveTab('drive')
      setMessage(`Google Drive connection error: ${params.get('drive_error')}`)
      setIsError(true)
      window.history.replaceState({}, document.title, window.location.pathname)
    }

    const timer = setInterval(checkHealth, 10000)
    return () => clearInterval(timer)
  }, [])

  async function checkHealth() {
    try {
      const res = await fetch(`${API_BASE}/api/health`, {
        signal: AbortSignal.timeout(3000),
        credentials: 'include'
      })
      if (res.ok) {
        const data = await res.json()
        setBackendOnline(true)
        if (data.drive_configured !== undefined) {
          setDriveConfigured(data.drive_configured)
        }
      } else {
        setBackendOnline(false)
      }
    } catch {
      setBackendOnline(false)
    }
  }

  async function checkDriveStatus() {
    try {
      const res = await fetch(`${API_BASE}/api/drive/status`, {
        credentials: 'include'
      })
      if (res.ok) {
        const data = await res.json()
        setDriveConnected(data.connected)
        setDriveEmail(data.email)
        if (data.connected && driveNotebooks.length === 0) {
          fetchDriveNotebooks('', null, false)
        }
      }
    } catch {
      // Backend not reached or offline
    }
  }

  // --- Local File Handling ---
  function addLocalFiles(list) {
    const selected = Array.from(list || [])
    const valid = selected.filter(file => file.name.toLowerCase().endsWith('.ipynb'))
    setLocalFiles(current => {
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
      addLocalFiles(e.dataTransfer.files)
    }
  }

  // --- Google Drive Handling ---
  async function connectDrive() {
    try {
      setMessage('')
      setIsError(false)
      const res = await fetch(`${API_BASE}/api/drive/auth-url`, {
        credentials: 'include'
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || 'Could not initiate Google OAuth.')
      }
      const data = await res.json()
      if (data.auth_url) {
        window.location.href = data.auth_url
      }
    } catch (err) {
      setIsError(true)
      setMessage(err.message)
    }
  }

  async function disconnectDrive() {
    try {
      setBusy(true)
      await fetch(`${API_BASE}/api/drive/disconnect`, {
        method: 'POST',
        credentials: 'include'
      })
      setDriveConnected(false)
      setDriveEmail(null)
      setDriveNotebooks([])
      setDriveSelectedIds(new Set())
      setMessage('Google Drive disconnected.')
      setIsError(false)
    } catch (err) {
      setIsError(true)
      setMessage(`Failed to disconnect: ${err.message}`)
    } finally {
      setBusy(false)
    }
  }

  async function fetchDriveNotebooks(searchQuery = driveSearch, pageToken = null, append = false) {
    setDriveLoading(true)
    try {
      const q = encodeURIComponent(searchQuery || '')
      const tokenParam = pageToken ? `&page_token=${encodeURIComponent(pageToken)}` : ''
      const res = await fetch(`${API_BASE}/api/drive/notebooks?query=${q}${tokenParam}`, {
        credentials: 'include'
      })
      if (!res.ok) {
        if (res.status === 401) {
          setDriveConnected(false)
          throw new Error('Google authorization expired or revoked. Please reconnect.')
        }
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || 'Failed to list notebooks from Google Drive.')
      }
      const data = await res.json()
      if (append) {
        setDriveNotebooks(prev => [...prev, ...(data.notebooks || [])])
      } else {
        setDriveNotebooks(data.notebooks || [])
      }
      setDriveNextPageToken(data.nextPageToken || null)
    } catch (err) {
      setIsError(true)
      setMessage(err.message)
    } finally {
      setDriveLoading(false)
    }
  }

  function toggleDriveFile(id) {
    setDriveSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleSelectAllDrive() {
    if (driveSelectedIds.size === driveNotebooks.length) {
      setDriveSelectedIds(new Set())
    } else {
      setDriveSelectedIds(new Set(driveNotebooks.map(nb => nb.id)))
    }
  }

  // --- Conversion Orchestrator ---
  async function handleConvert() {
    if (activeTab === 'local') {
      await convertLocal()
    } else {
      await convertDrive()
    }
  }

  async function convertLocal() {
    if (!localFiles.length) {
      setMessage('Select at least one .ipynb file first.')
      setIsError(true)
      return
    }
    setBusy(true)
    setIsError(false)
    setMessage(`Converting ${localFiles.length} notebook${localFiles.length > 1 ? 's' : ''} to ${format.toUpperCase()}...`)

    try {
      const form = new FormData()
      localFiles.forEach(file => form.append('files', file))
      form.append('output_format', format)

      const response = await fetch(`${API_BASE}/api/convert-zip`, {
        method: 'POST',
        body: form,
        credentials: 'include'
      })

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}))
        throw new Error(errData.detail || `Conversion failed with status ${response.status}.`)
      }

      await downloadZipResponse(response)
      setMessage(`Successfully converted & downloaded ${localFiles.length} file${localFiles.length > 1 ? 's' : ''} as ZIP!`)
      setIsError(false)
    } catch (error) {
      setIsError(true)
      setMessage(error.message)
    } finally {
      setBusy(false)
    }
  }

  async function convertDrive() {
    if (driveSelectedIds.size === 0) {
      setMessage('Select at least one Google Drive / Colab notebook.')
      setIsError(true)
      return
    }
    setBusy(true)
    setIsError(false)
    setMessage(`Downloading ${driveSelectedIds.size} notebook${driveSelectedIds.size > 1 ? 's' : ''} from Drive and converting to ${format.toUpperCase()}...`)

    try {
      const response = await fetch(`${API_BASE}/api/drive/convert`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          file_ids: Array.from(driveSelectedIds),
          output_format: format
        }),
        credentials: 'include'
      })

      if (!response.ok) {
        const errData = await response.json().catch(() => ({}))
        throw new Error(errData.detail || `Conversion failed with status ${response.status}.`)
      }

      await downloadZipResponse(response)
      setMessage(`Successfully converted & downloaded ${driveSelectedIds.size} Drive notebook${driveSelectedIds.size > 1 ? 's' : ''} as ZIP!`)
      setIsError(false)
    } catch (error) {
      setIsError(true)
      setMessage(error.message)
    } finally {
      setBusy(false)
    }
  }

  async function downloadZipResponse(response) {
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `converted_notebooks_${format}.zip`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  }

  const selectedCount = activeTab === 'local' ? localFiles.length : driveSelectedIds.size

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
              <><CheckCircle2 size={14}/> Backend Ready</>
            ) : backendOnline === false ? (
              <><AlertCircle size={14}/> Backend Offline</>
            ) : (
              <><RefreshCw size={14} className="spin"/> Checking...</>
            )}
          </div>
          <div className="nav-pill"><ShieldCheck size={15}/> Private & Stateless</div>
        </div>
      </nav>

      <section className="hero">
        <div className="eyebrow"><Sparkles size={15}/> NOTEBOOK EXPORT STUDIO</div>
        <h1>Your notebooks,<br/><span>ready to share.</span></h1>
        <p className="sub">
          Convert Jupyter and Google Colab notebooks (.ipynb) to polished HTML or PDF files. Download everything in one clean ZIP archive. Zero permanent storage.
        </p>
      </section>

      <section className="panel">
        {/* Import Source Tabs */}
        <div className="tab-bar">
          <button
            type="button"
            className={`tab-btn ${activeTab === 'local' ? 'active' : ''}`}
            onClick={() => { setActiveTab('local'); setMessage('') }}
          >
            <Laptop size={16}/> Upload from Computer
            {localFiles.length > 0 && <span className="tab-badge">{localFiles.length}</span>}
          </button>
          <button
            type="button"
            className={`tab-btn ${activeTab === 'drive' ? 'active' : ''}`}
            onClick={() => { setActiveTab('drive'); setMessage('') }}
          >
            <HardDrive size={16}/> Google Drive / Colab
            {driveSelectedIds.size > 0 && <span className="tab-badge">{driveSelectedIds.size}</span>}
          </button>
        </div>

        {/* Tab A: Local Upload */}
        {activeTab === 'local' && (
          <div>
            <div className="panel-heading" style={{ marginTop: '16px' }}>
              <div>
                <h2>Upload Notebooks</h2>
                <p>Drag and drop or select your local .ipynb files (up to 20 files, max 15MB each).</p>
              </div>
              <span className="step">STEP 01</span>
            </div>

            <label
              className={`dropzone ${dragOver ? 'dropzone-active' : ''}`}
              htmlFor="files"
              onDrop={handleDrop}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={(e) => { e.preventDefault(); setDragOver(false) }}
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
                onChange={e => addLocalFiles(e.target.files)}
              />
            </label>

            {localFiles.length > 0 && (
              <div className="file-list">
                <div className="file-list-title">
                  <FolderOpen size={16}/> Selected files <span>{localFiles.length}/20</span>
                </div>
                {localFiles.map((file, i) => (
                  <div className="file-row" key={`${file.name}-${i}`}>
                    <FileCode2 size={17}/>
                    <span>{file.name}</span>
                    <small>{(file.size / 1024).toFixed(0)} KB</small>
                    <button
                      className="remove"
                      onClick={() => setLocalFiles(current => current.filter((_, index) => index !== i))}
                      aria-label={`Remove ${file.name}`}
                    >
                      ×
                    </button>
                  </div>
                ))}
                <button className="clear" onClick={() => setLocalFiles([])}>Clear selection</button>
              </div>
            )}
          </div>
        )}

        {/* Tab B: Google Drive / Colab */}
        {activeTab === 'drive' && (
          <div style={{ marginTop: '16px' }}>
            {!driveConnected ? (
              <div className="drive-connect-card">
                <div className="drive-symbol">G</div>
                <div className="drive-copy">
                  <h3>Connect your Google Drive</h3>
                  <p>
                    Access your Google Colab and Jupyter notebooks directly from Google Drive.
                    NotebookFlow requests strictly read-only authorization. Note: make sure to save in-progress Colab notebooks to Drive first.
                  </p>
                  {!driveConfigured && (
                    <p style={{ color: '#f87171', fontSize: '11px', marginTop: '6px' }}>
                      Google OAuth credentials are not set on the backend. Provide GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.
                    </p>
                  )}
                </div>
                <button
                  type="button"
                  className="btn-drive-connect"
                  onClick={connectDrive}
                  disabled={busy}
                >
                  <HardDrive size={16}/> Connect Drive
                </button>
              </div>
            ) : (
              <div>
                <div className="drive-header-bar">
                  <div className="drive-user-info">
                    <div className="drive-avatar">G</div>
                    <div>
                      <div className="drive-email">{driveEmail || 'Connected to Google Drive'}</div>
                      <div className="drive-meta">Read-only Colab / Jupyter Access</div>
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button
                      type="button"
                      className="btn-subtle"
                      onClick={() => fetchDriveNotebooks(driveSearch, null, false)}
                      disabled={driveLoading}
                      title="Refresh notebook list"
                    >
                      <RefreshCw size={14} className={driveLoading ? 'spin' : ''}/> Refresh
                    </button>
                    <button
                      type="button"
                      className="btn-subtle btn-danger"
                      onClick={disconnectDrive}
                      disabled={busy}
                      title="Disconnect Google Account"
                    >
                      <LogOut size={14}/> Disconnect
                    </button>
                  </div>
                </div>

                {/* Search & Bulk Selection Bar */}
                <div className="drive-toolbar">
                  <form
                    onSubmit={(e) => {
                      e.preventDefault()
                      fetchDriveNotebooks(driveSearch, null, false)
                    }}
                    style={{ flex: 1, display: 'flex', position: 'relative' }}
                  >
                    <Search size={15} style={{ position: 'absolute', left: '12px', top: '11px', color: '#687b9e' }}/>
                    <input
                      type="text"
                      className="search-input"
                      placeholder="Search notebooks in Drive..."
                      value={driveSearch}
                      onChange={(e) => setDriveSearch(e.target.value)}
                    />
                  </form>
                  {driveNotebooks.length > 0 && (
                    <button
                      type="button"
                      className="btn-subtle"
                      onClick={toggleSelectAllDrive}
                    >
                      {driveSelectedIds.size === driveNotebooks.length ? (
                        <><CheckSquare size={15} style={{ color: '#8ca5ff' }}/> Deselect All</>
                      ) : (
                        <><Square size={15}/> Select All ({driveNotebooks.length})</>
                      )}
                    </button>
                  )}
                </div>

                {/* Notebook File Picker List */}
                <div className="drive-picker-container">
                  {driveLoading && driveNotebooks.length === 0 ? (
                    <div className="drive-empty">
                      <RefreshCw size={24} className="spin" style={{ color: '#8ca5ff' }}/>
                      <p>Searching Google Drive for notebooks...</p>
                    </div>
                  ) : driveNotebooks.length === 0 ? (
                    <div className="drive-empty">
                      <FileCode2 size={28} style={{ color: '#475569' }}/>
                      <p>No .ipynb notebooks found in your Drive.</p>
                      <small className="muted">Ensure your Colab notebooks have been saved to Google Drive.</small>
                    </div>
                  ) : (
                    <>
                      {driveNotebooks.map((nb) => {
                        const selected = driveSelectedIds.has(nb.id)
                        return (
                          <div
                            key={nb.id}
                            className={`drive-row ${selected ? 'selected' : ''}`}
                            onClick={() => toggleDriveFile(nb.id)}
                          >
                            <span className="drive-check">
                              {selected ? <CheckSquare size={18} style={{ color: '#8ca5ff' }}/> : <Square size={18} style={{ color: '#4c5d80' }}/>}
                            </span>
                            <FileCode2 size={18} style={{ color: '#8ca8ff', flexShrink: 0 }}/>
                            <div className="drive-row-details">
                              <span className="drive-row-name">{nb.name}</span>
                              <div className="drive-row-sub">
                                {nb.modifiedTime && <span>Modified {formatDate(nb.modifiedTime)}</span>}
                                {nb.size && <span>· {formatBytes(nb.size)}</span>}
                              </div>
                            </div>
                          </div>
                        )
                      })}

                      {driveNextPageToken && (
                        <div style={{ textAlign: 'center', padding: '12px' }}>
                          <button
                            type="button"
                            className="btn-subtle"
                            onClick={() => fetchDriveNotebooks(driveSearch, driveNextPageToken, true)}
                            disabled={driveLoading}
                          >
                            {driveLoading ? <RefreshCw size={14} className="spin"/> : 'Load more notebooks'}
                          </button>
                        </div>
                      )}
                    </>
                  )}
                </div>

                {driveSelectedIds.size > 0 && (
                  <div className="selected-summary">
                    <span>{driveSelectedIds.size} notebook{driveSelectedIds.size > 1 ? 's' : ''} selected</span>
                    <button className="clear" onClick={() => setDriveSelectedIds(new Set())}>Clear selection</button>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Step 2: Choose Output Format (HTML vs PDF) */}
        <div className="format-title">
          Choose output format <span>All files will be packed into a ZIP</span>
        </div>
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

        {/* Action Button */}
        <button
          className="convert"
          disabled={busy || selectedCount === 0}
          onClick={handleConvert}
        >
          {busy ? (
            <>
              <RefreshCw size={18} className="spin" />
              Converting {selectedCount} notebook{selectedCount > 1 ? 's' : ''}…
            </>
          ) : (
            <>
              Convert & download ZIP ({selectedCount} file{selectedCount !== 1 ? 's' : ''}) <FileDown size={18}/>
            </>
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
          <ShieldCheck size={14}/>
          Files are processed temporarily in serverless RAM/disk and purged immediately upon completion.
        </p>
      </section>

      {/* Colab / Architecture Info Footer */}
      <section className="drive-card">
        <div className="drive-symbol">⚡</div>
        <div className="drive-copy">
          <h3>Stateless Serverless Conversion</h3>
          <p>
            Powered by FastAPI, nbconvert, and headless Chromium. Ready for high-concurrency deployment on Google Cloud Run and Vercel.
          </p>
        </div>
        <span className="coming">PRODUCTION</span>
      </section>
      <footer>NotebookFlow · Built for students, researchers, and developers</footer>
    </main>
  )
}

createRoot(document.getElementById('root')).render(<App />)
