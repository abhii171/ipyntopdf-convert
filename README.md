# NotebookFlow 🚀

A production-ready serverless web application to convert Jupyter and Google Colab Notebooks (`.ipynb`) into publication-ready **HTML** or **PDF** files and download them in a single ZIP archive.

---

## 🌟 Key Features

- **Two Import Methods:**
  - 💻 **Upload from Computer:** Drag-and-drop or batch upload up to 20 `.ipynb` files.
  - ☁️ **Google Drive / Colab Integration:** Search, browse, and multi-select notebooks directly from My Drive and Shared Drives.
- **HTML & PDF Export:** Clean conversion powered by `nbconvert` and headless Chromium via Playwright. Preserves code, Markdown, formulas, outputs, and embedded images without executing code.
- **100% Stateless & Ephemeral:** Zero permanent storage. Uploaded notebooks, intermediate documents, and ZIP archives reside only in temporary storage and are purged upon response streaming or error.
- **Serverless Session Architecture:** Stores Google OAuth tokens in tamper-proof, Fernet-encrypted HttpOnly cookies. Scales across Google Cloud Run instances without requiring Redis or a SQL database.
- **Single ZIP Download:** Streams ZIP archives directly without loading large files into container RAM.
- **Production-Ready Deployments:** Configured for Google Cloud Run (Backend) and Vercel (Frontend), or as a single containerized monolith.

---

## 🏗️ Architecture

```
┌────────────────────────────────────────────────────────┐
│               Frontend (React + Vite)                  │
│       Vercel / Cloud Run Static File Serving           │
└───────────────────────────┬────────────────────────────┘
                            │ HTTPS / Cookie Auth
┌───────────────────────────▼────────────────────────────┐
│              Backend (FastAPI on Cloud Run)            │
│  - Fernet Stateless Session Cookie (No Redis/DB)       │
│  - BackgroundTasks Streaming & Temp Storage Cleanup    │
│  - Concurrency Semaphore & Timeout Guards              │
└──────────────┬──────────────────────────┬──────────────┘
               │                          │
┌──────────────▼─────────────┐   ┌────────▼──────────────┐
│      Google Drive API      │   │  nbconvert Engine     │
│  (Read-Only Notebook Fetch)│   │  (Playwright Chromium)│
└────────────────────────────┘   └───────────────────────┘
```

---

## 🚀 Local Development (Windows PowerShell)

### Option 1: One-Click Production Start
Simply double-click:
```powershell
run_production.bat
```
This builds the frontend (if needed) and serves the complete production app at **http://127.0.0.1:8000**.

### Option 2: Live Development Mode
Double-click:
```powershell
start_dev.bat
```
Starts FastAPI on port 8000 and Vite on port 5173 with hot reload.

### Option 3: Manual Execution
```powershell
# 1. Backend
cd backend
python -m pip install -r requirements.txt
python -m playwright install chromium
python -m uvicorn app:app --reload --port 8000

# 2. Frontend (in a separate terminal)
cd frontend
npm install
npm run dev
```

---

## ☁️ Deploying to Google Cloud Run (Backend)

Google Cloud Run provides auto-scaling serverless container hosting for the FastAPI backend and Playwright Chromium.

### Step 1: Set Google Cloud Secrets / Environment Variables
In your Google Cloud Console or via `gcloud`:
```bash
gcloud run deploy notebookflow-backend \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --concurrency 10 \
  --timeout 300 \
  --set-env-vars="ENVIRONMENT=production,SESSION_SECRET_KEY=YOUR_HEX_SECRET,GOOGLE_CLIENT_ID=YOUR_CLIENT_ID,GOOGLE_CLIENT_SECRET=YOUR_CLIENT_SECRET,GOOGLE_REDIRECT_URI=https://notebookflow-backend-xyz.a.run.app/api/drive/callback,FRONTEND_URL=https://notebookflow.vercel.app,CORS_ORIGINS=https://notebookflow.vercel.app"
```

*Recommended Cloud Run Specs:*
- **Memory:** `2Gi` (Required for headless Chromium PDF generation).
- **CPU:** `2` vCPUs.
- **Timeout:** `300` seconds.

---

## ⚡ Deploying to Vercel (Frontend)

1. Connect your repository to [Vercel](https://vercel.com).
2. Set **Root Directory** to `frontend`.
3. In Vercel Project Settings $\rightarrow$ **Environment Variables**, add:
   ```
   VITE_API_BASE_URL = https://your-cloud-run-backend-url.a.run.app
   ```
4. Click **Deploy**. Vercel will build using [`vercel.json`](file:///c:/Users/Abhijeeth/Downloads/notebook-converter-starter/frontend/vercel.json).

---

## 🔑 Google Cloud Console Setup (Google Drive / Colab)

To enable Google Drive integration:

1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Create or select a project.
3. Enable the **Google Drive API**:
   - Go to **APIs & Services** $\rightarrow$ **Library** $\rightarrow$ search for **Google Drive API** $\rightarrow$ click **Enable**.
4. Configure the **OAuth Consent Screen**:
   - User Type: **External** (or Internal for Workspace).
   - Scopes: Add `.../auth/drive.readonly` and `.../auth/userinfo.email`.
   - Add your test user emails in test mode.
5. Create OAuth 2.0 Credentials:
   - Go to **APIs & Services** $\rightarrow$ **Credentials** $\rightarrow$ **Create Credentials** $\rightarrow$ **OAuth client ID**.
   - Application type: **Web application**.
   - **Authorized JavaScript origins:**
     - `http://localhost:5173`
     - `http://127.0.0.1:8000`
     - `https://your-frontend.vercel.app`
   - **Authorized redirect URIs:**
     - `http://127.0.0.1:8000/api/drive/callback`
     - `https://your-cloud-run-backend.a.run.app/api/drive/callback`
6. Copy the **Client ID** and **Client Secret** into your `.env` or Cloud Run environment variables.

> **Why `drive.readonly` instead of `drive.file`?**
> The `drive.file` scope only grants access to files created by the application or selected through the external Google Picker popup. `drive.readonly` is the least-privileged appropriate scope that allows NotebookFlow to provide a built-in search and selection interface across user Colab notebooks and Shared Drives. It cannot edit, modify, or delete any user documents.

---

## 🔒 Security & Privacy

- **No Code Execution:** Conversion renders existing notebook structure, markdown, LaTeX, and outputs. Python code cells are never run on the server.
- **Zero Permanent Disk Storage:** Files are written to ephemeral directories (`mkdtemp`) and deleted via background tasks immediately following response delivery or upon exception.
- **Safe Filenames:** Filenames are sanitized to prevent directory traversal and shell injection.
- **Resource Limits:** Individual files capped at 15 MB, batch requests capped at 50 MB, maximum 20 notebooks per request, with `asyncio.Semaphore` concurrency limiting.
- **Stateless Tokens:** Access tokens are encrypted using Fernet (AES-GCM) inside an HttpOnly, SameSite, Secure cookie. No server-side database or token store is kept.

---

## 🧪 Testing

Run the automated test suite covering all 15 scenarios:
```powershell
python backend/test_suite.py
```
Outputs:
```
[PASS] Test 1: Health endpoint is operational.
[PASS] Test 2: Single notebook to HTML conversion succeeded.
[PASS] Test 3: Single notebook to PDF conversion succeeded.
[PASS] Test 4: Multiple notebooks to ZIP succeeded.
[PASS] Test 5: Duplicate filenames are safely disambiguated.
[PASS] Test 6: Invalid notebook JSON rejected with 400.
[PASS] Test 7: Oversized notebook rejected with 413.
[PASS] Test 8: Temporary file cleanup verified.
[PASS] Test 9 & 10: OAuth CSRF state cryptographic validation verified.
[PASS] Test: Stateless session Fernet encryption verified.
[PASS] Test 11: Unauthenticated Drive calls correctly return 401.
[PASS] Test 12: Drive auth-url handling verified.
[PASS] Test 13: Drive mock listing and conversion end-to-end verified.
[PASS] Test 14: Drive disconnect and session purge verified.
[PASS] Test 15: CORS configuration verified.
ALL 15 TEST SUITES PASSED SUCCESSFULLY!
```

To enable Google Drive integration:

1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Create or select a project.
3. Enable the **Google Drive API**:
   - Go to **APIs & Services** $\rightarrow$ **Library** $\rightarrow$ search for **Google Drive API** $\rightarrow$ click **Enable**.
4. Configure the **OAuth Consent Screen**:
   - User Type: **External** (or Internal for Workspace).
   - Scopes: Add `.../auth/drive.readonly` and `.../auth/userinfo.email`.
   - Add your test user emails in test mode.
5. Create OAuth 2.0 Credentials:
   - Go to **APIs & Services** $\rightarrow$ **Credentials** $\rightarrow$ **Create Credentials** $\rightarrow$ **OAuth client ID**.
   - Application type: **Web application**.
   - **Authorized JavaScript origins:**
     - `http://localhost:5173`
     - `http://127.0.0.1:8000`
     - `https://your-frontend.vercel.app`
   - **Authorized redirect URIs:**
     - `http://127.0.0.1:8000/api/drive/callback`
     - `https://your-cloud-run-backend.a.run.app/api/drive/callback`
6. Copy the **Client ID** and **Client Secret** into your `.env` or Cloud Run environment variables.

> **Why `drive.readonly` instead of `drive.file`?**
> The `drive.file` scope only grants access to files created by the application or selected through the external Google Picker popup. `drive.readonly` is the least-privileged appropriate scope that allows NotebookFlow to provide a built-in search and selection interface across user Colab notebooks and Shared Drives. It cannot edit, modify, or delete any user documents.

---

## 🔒 Security & Privacy

- **No Code Execution:** Conversion renders existing notebook structure, markdown, LaTeX, and outputs. Python code cells are never run on the server.
- **Zero Permanent Disk Storage:** Files are written to ephemeral directories (`mkdtemp`) and deleted via background tasks immediately following response delivery or upon exception.
- **Safe Filenames:** Filenames are sanitized to prevent directory traversal and shell injection.
- **Resource Limits:** Individual files capped at 15 MB, batch requests capped at 50 MB, maximum 20 notebooks per request, with `asyncio.Semaphore` concurrency limiting.
- **Stateless Tokens:** Access tokens are encrypted using Fernet (AES-GCM) inside an HttpOnly, SameSite, Secure cookie. No server-side database or token store is kept.

---

## 🧪 Testing

Run the automated test suite covering all 15 scenarios:
```powershell
python backend/test_suite.py
```
Outputs:
```
[PASS] Test 1: Health endpoint is operational.
[PASS] Test 2: Single notebook to HTML conversion succeeded.
[PASS] Test 3: Single notebook to PDF conversion succeeded.
[PASS] Test 4: Multiple notebooks to ZIP succeeded.
[PASS] Test 5: Duplicate filenames are safely disambiguated.
[PASS] Test 6: Invalid notebook JSON rejected with 400.
[PASS] Test 7: Oversized notebook rejected with 413.
[PASS] Test 8: Temporary file cleanup verified.
[PASS] Test 9 & 10: OAuth CSRF state cryptographic validation verified.
[PASS] Test: Stateless session Fernet encryption verified.
[PASS] Test 11: Unauthenticated Drive calls correctly return 401.
[PASS] Test 12: Drive auth-url handling verified.
[PASS] Test 13: Drive mock listing and conversion end-to-end verified.
[PASS] Test 14: Drive disconnect and session purge verified.
[PASS] Test 15: CORS configuration verified.
ALL 15 TEST SUITES PASSED SUCCESSFULLY!
```

