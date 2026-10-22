from pathlib import Path
from tempfile import mkdtemp
from zipfile import ZIP_DEFLATED, ZipFile
import asyncio
import os
import re
import shutil
from typing import List, Optional

from dotenv import load_dotenv

# Load environment variables before reading configuration
load_dotenv()
load_dotenv(Path(__file__).resolve().parent / ".env")
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import BackgroundTasks, Cookie, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import nbformat
from nbconvert import HTMLExporter, WebPDFExporter
from pydantic import BaseModel, Field

from drive_service import (
    build_auth_url,
    download_drive_notebook,
    exchange_code_for_tokens,
    get_credentials_from_session,
    is_drive_configured,
    list_drive_notebooks,
    revoke_token,
)
from session_manager import (
    SESSION_COOKIE_NAME,
    create_csrf_state,
    decrypt_session_data,
    encrypt_session_data,
    verify_csrf_state,
)

app = FastAPI(
    title="NotebookFlow API",
    version="1.0.0",
    description="Stateless Notebook Converter with Google Drive / Colab Integration for Serverless Deployment",
)

# Configuration & Resource Limits for Cloud Run
MAX_FILE_BYTES = 15 * 1024 * 1024       # 15 MB per notebook
MAX_TOTAL_BYTES = 50 * 1024 * 1024      # 50 MB total upload per request
MAX_NOTEBOOKS = 20                      # Maximum 20 notebooks per request
CONVERSION_TIMEOUT_SECONDS = int(os.getenv("CONVERSION_TIMEOUT_SECONDS", "60"))
MAX_CONCURRENT_CONVERSIONS = int(os.getenv("MAX_CONCURRENT_CONVERSIONS", "4"))
ALLOWED_FORMATS = {"html", "pdf"}

# Concurrency semaphore to prevent CPU/memory starvation on serverless containers
conversion_semaphore = asyncio.Semaphore(MAX_CONCURRENT_CONVERSIONS)

BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR.parent / "frontend" / "dist"

# Configure CORS for local development and production Vercel / custom domains
cors_env = os.getenv("CORS_ORIGINS", "").strip()
if cors_env:
    allowed_origins = [orig.strip() for orig in cors_env.split(",") if orig.strip()]
else:
    allowed_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
    ]

# Determine production cookie security settings
IS_PRODUCTION = os.getenv("ENVIRONMENT", "development").lower() == "production"
FRONTEND_URL = os.getenv("FRONTEND_URL", "").strip()

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins if allowed_origins != ["*"] else [],
    allow_origin_regex=r".*" if allowed_origins == ["*"] else None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def safe_stem(filename: str) -> str:
    """Sanitize filename to prevent path traversal and shell injection."""
    stem = Path(filename).stem
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")
    return (stem or "notebook")[:100]


def cleanup_directory(directory_path: str):
    """Safely remove a temporary directory after response is streamed."""
    try:
        shutil.rmtree(directory_path, ignore_errors=True)
    except Exception:
        pass


def convert_single_notebook(input_path: Path, output_format: str, target: Path):
    """
    Synchronous conversion worker run in thread pool.
    Preserves existing markdown, equations, images, code cells, and outputs.
    Code is never executed.
    """
    if output_format == "html":
        exporter = HTMLExporter()
        # HTMLExporter preserves outputs and images embedded in the notebook without executing code
        body, _ = exporter.from_filename(str(input_path))
        target.write_text(body, encoding="utf-8")
    else:
        # WebPDFExporter uses Playwright headless chromium to generate clean, print-ready PDF
        exporter = WebPDFExporter()
        body, _ = exporter.from_filename(str(input_path))
        target.write_bytes(body)


def get_current_session(request: Request) -> Optional[dict]:
    """Retrieve and decrypt session cookie from incoming request."""
    cookie_val = request.cookies.get(SESSION_COOKIE_NAME)
    if not cookie_val:
        return None
    return decrypt_session_data(cookie_val)


# --- Health & Diagnostic Endpoints ---


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "NotebookFlow Serverless API",
        "drive_configured": is_drive_configured(),
        "supported_formats": sorted(list(ALLOWED_FORMATS)),
        "limits": {
            "max_file_size_mb": MAX_FILE_BYTES // (1024 * 1024),
            "max_total_size_mb": MAX_TOTAL_BYTES // (1024 * 1024),
            "max_notebooks_per_request": MAX_NOTEBOOKS,
            "timeout_seconds": CONVERSION_TIMEOUT_SECONDS,
        },
    }


# --- Local File Upload Conversion ---


@app.post("/api/convert-zip")
async def convert_zip(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    output_format: str = Form("html"),
):
    output_format = output_format.lower().strip()
    if output_format not in ALLOWED_FORMATS:
        raise HTTPException(400, "output_format must be 'html' or 'pdf'.")
    if not files:
        raise HTTPException(400, "Upload at least one .ipynb file.")
    if len(files) > MAX_NOTEBOOKS:
        raise HTTPException(400, f"Maximum {MAX_NOTEBOOKS} notebooks per request.")

    # Create isolated temporary directory
    workdir = Path(mkdtemp(prefix="notebook_flow_upload_"))

    try:
        output_dir = workdir / "converted"
        output_dir.mkdir(exist_ok=True)
        used_names = set()
        converted_paths = []
        total_bytes = 0

        for upload in files:
            original_name = upload.filename or "notebook.ipynb"
            if not original_name.lower().endswith(".ipynb"):
                raise HTTPException(400, f"'{original_name}': only .ipynb files are supported.")

            data = await upload.read()
            total_bytes += len(data)
            if len(data) > MAX_FILE_BYTES:
                raise HTTPException(413, f"'{original_name}' exceeds maximum size of 15 MB.")
            if total_bytes > MAX_TOTAL_BYTES:
                raise HTTPException(413, f"Total upload size exceeds 50 MB limit.")
            if not data:
                raise HTTPException(400, f"'{original_name}' is empty (0 bytes).")

            input_path = workdir / f"input_{len(converted_paths)}.ipynb"
            try:
                notebook = nbformat.reads(data.decode("utf-8"), as_version=4)
                nbformat.validate(notebook)
                nbformat.write(notebook, input_path)
            except Exception as exc:
                raise HTTPException(400, f"'{original_name}' contains invalid notebook JSON ({exc}).")

            base = safe_stem(original_name)
            unique_base = base
            counter = 2
            while unique_base.lower() in used_names:
                unique_base = f"{base}_{counter}"
                counter += 1
            used_names.add(unique_base.lower())

            ext = "html" if output_format == "html" else "pdf"
            target = output_dir / f"{unique_base}.{ext}"

            # Run conversion inside concurrency semaphore and timeout guard
            async with conversion_semaphore:
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(convert_single_notebook, input_path, output_format, target),
                        timeout=CONVERSION_TIMEOUT_SECONDS,
                    )
                    converted_paths.append(target)
                except asyncio.TimeoutError:
                    raise HTTPException(
                        504,
                        f"Conversion of '{original_name}' timed out after {CONVERSION_TIMEOUT_SECONDS}s.",
                    )
                except Exception as exc:
                    raise HTTPException(
                        500,
                        f"Could not convert '{original_name}' to {output_format.upper()}. Details: {str(exc)[:300]}",
                    )

        zip_path = workdir / f"converted_notebooks_{output_format}.zip"
        with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
            for path in converted_paths:
                archive.write(path, arcname=path.name)

        # Stream ZIP file directly to avoid buffering archive into RAM
        # BackgroundTasks guarantees removal of temporary directory upon completion
        background_tasks.add_task(cleanup_directory, str(workdir))
        return FileResponse(
            path=str(zip_path),
            media_type="application/zip",
            filename=zip_path.name,
            background=background_tasks,
        )

    except Exception:
        # Immediate cleanup on any uncaught exception
        cleanup_directory(str(workdir))
        raise


# --- Google Drive & OAuth 2.0 Endpoints ---


@app.get("/api/drive/auth-url")
def get_drive_auth_url(request: Request):
    """Generate Google OAuth 2.0 authorization URL with signed CSRF state."""
    if not is_drive_configured():
        raise HTTPException(
            503,
            "Google Drive integration is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables.",
        )

    state = create_csrf_state()
    auth_url = build_auth_url(state)
    return {"auth_url": auth_url}


@app.get("/api/drive/callback")
def handle_drive_callback(
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
):
    """Exchange OAuth authorization code for tokens and store in secure encrypted cookie."""
    if error:
        return RedirectResponse(
            url=f"{FRONTEND_URL or '/'}?drive_error={error}",
            status_code=302,
        )
    if not code or not state:
        raise HTTPException(400, "Missing required OAuth parameters (code or state).")

    if not verify_csrf_state(state):
        raise HTTPException(403, "Invalid or expired OAuth CSRF state. Please try connecting again.")

    try:
        token_data = exchange_code_for_tokens(code)
    except Exception as exc:
        raise HTTPException(500, f"OAuth exchange failed: {exc}")

    encrypted_cookie = encrypt_session_data(token_data)

    target_redirect = FRONTEND_URL or "/"
    if "?" in target_redirect:
        redirect_url = f"{target_redirect}&drive_connected=1"
    else:
        redirect_url = f"{target_redirect}?drive_connected=1"

    response = RedirectResponse(url=redirect_url, status_code=302)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=encrypted_cookie,
        path="/",
        httponly=True,
        secure=IS_PRODUCTION,
        samesite="lax",
        max_age=86400 * 7,  # 7 days
    )
    return response


@app.get("/api/drive/status")
def get_drive_status(request: Request):
    """Return whether the current user is connected with Google Drive."""
    session = get_current_session(request)
    if not session or not session.get("access_token"):
        return {"connected": False, "email": None}
    return {
        "connected": True,
        "email": session.get("email"),
    }


@app.get("/api/drive/notebooks")
def list_notebooks(
    request: Request,
    query: str = Query("", description="Search term for notebook title"),
    page_token: Optional[str] = Query(None, description="Next page token for pagination"),
):
    """List .ipynb notebooks from user's Google Drive and Shared Drives."""
    session = get_current_session(request)
    if not session or not session.get("access_token"):
        raise HTTPException(401, "Google Drive not connected. Please authorize first.")

    try:
        creds = get_credentials_from_session(session)
        result = list_drive_notebooks(creds, search_query=query, page_token=page_token)
        return result
    except Exception as exc:
        raise HTTPException(500, f"Error fetching notebooks from Google Drive: {exc}")


class DriveConvertRequest(BaseModel):
    file_ids: List[str] = Field(..., min_items=1, max_items=MAX_NOTEBOOKS)
    output_format: str = "html"


@app.post("/api/drive/convert")
async def convert_drive_notebooks(
    payload: DriveConvertRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Download selected notebooks from Google Drive, convert to HTML or PDF,
    package into ZIP, and stream response. Zero permanent disk storage.
    """
    session = get_current_session(request)
    if not session or not session.get("access_token"):
        raise HTTPException(401, "Google Drive not connected. Please authorize first.")

    output_format = payload.output_format.lower().strip()
    if output_format not in ALLOWED_FORMATS:
        raise HTTPException(400, "output_format must be 'html' or 'pdf'.")

    try:
        creds = get_credentials_from_session(session)
    except Exception as exc:
        raise HTTPException(401, str(exc))

    workdir = Path(mkdtemp(prefix="notebook_flow_drive_"))

    try:
        output_dir = workdir / "converted"
        output_dir.mkdir(exist_ok=True)
        used_names = set()
        converted_paths = []

        for file_id in payload.file_ids:
            try:
                original_name, notebook = download_drive_notebook(creds, file_id)
            except Exception as exc:
                raise HTTPException(400, f"Failed to download notebook (ID: {file_id}): {exc}")

            input_path = workdir / f"drive_input_{len(converted_paths)}.ipynb"
            nbformat.write(notebook, input_path)

            base = safe_stem(original_name)
            unique_base = base
            counter = 2
            while unique_base.lower() in used_names:
                unique_base = f"{base}_{counter}"
                counter += 1
            used_names.add(unique_base.lower())

            ext = "html" if output_format == "html" else "pdf"
            target = output_dir / f"{unique_base}.{ext}"

            async with conversion_semaphore:
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(convert_single_notebook, input_path, output_format, target),
                        timeout=CONVERSION_TIMEOUT_SECONDS,
                    )
                    converted_paths.append(target)
                except asyncio.TimeoutError:
                    raise HTTPException(
                        504,
                        f"Conversion of '{original_name}' timed out after {CONVERSION_TIMEOUT_SECONDS}s.",
                    )
                except Exception as exc:
                    raise HTTPException(
                        500,
                        f"Could not convert '{original_name}' to {output_format.upper()}. Details: {str(exc)[:300]}",
                    )

        zip_path = workdir / f"converted_notebooks_{output_format}.zip"
        with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
            for path in converted_paths:
                archive.write(path, arcname=path.name)

        # Stream ZIP file directly; background cleanup removes temp directory
        background_tasks.add_task(cleanup_directory, str(workdir))
        return FileResponse(
            path=str(zip_path),
            media_type="application/zip",
            filename=zip_path.name,
            background=background_tasks,
        )

    except Exception:
        cleanup_directory(str(workdir))
        raise


@app.post("/api/drive/disconnect")
def disconnect_drive(request: Request):
    session = get_current_session(request)
    if session:
        token = session.get("refresh_token") or session.get("access_token")
        revoke_token(token)

    response = JSONResponse({"status": "disconnected"})
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=IS_PRODUCTION,
        samesite="lax",
    )
    return response


# --- Static SPA Frontend Serving (When Running as Unified Monolith / Local / Docker) ---

if (DIST_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(DIST_DIR / "assets")), name="assets")


@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    # Allow API routes to 404 naturally
    if full_path.startswith("api/"):
        raise HTTPException(404, "API endpoint not found.")
    if not DIST_DIR.exists():
        return Response(
            content="Frontend not built yet. Run 'npm run build' inside frontend directory.",
            media_type="text/plain",
            status_code=503,
        )
    candidate = DIST_DIR / full_path
    if full_path and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(DIST_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
