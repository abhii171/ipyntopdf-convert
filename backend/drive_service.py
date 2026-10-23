"""
Google Drive and OAuth 2.0 integration service for NotebookFlow.
Handles read-only notebook discovery and retrieval from Google Drive and Colab.
"""

import io
import os
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import googleapiclient.discovery
from googleapiclient.http import MediaIoBaseDownload
import nbformat
import requests
from dotenv import load_dotenv
from notebook_utils import sanitize_and_parse_notebook

load_dotenv()

# Least-privileged scope for listing and downloading user notebooks from My Drive and Shared Drives
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/userinfo.email"]


def get_oauth_config() -> Tuple[str, str, str]:
    """Retrieve OAuth configuration from environment variables."""
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("GOOGLE_REDIRECT_URI", "http://127.0.0.1:8000/api/drive/callback").strip()
    return client_id, client_secret, redirect_uri


def is_drive_configured() -> bool:
    """Check if Google Drive OAuth credentials are configured."""
    client_id, client_secret, _ = get_oauth_config()
    return bool(client_id and client_secret)


def build_auth_url(state: str) -> str:
    """Build the Google OAuth 2.0 authorization URL."""
    client_id, _, redirect_uri = get_oauth_config()
    if not client_id:
        raise ValueError("GOOGLE_CLIENT_ID environment variable is not configured.")

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(DRIVE_SCOPES),
        "access_type": "offline",  # Request refresh token for seamless sessions
        "prompt": "consent",
        "state": state,
        "include_granted_scopes": "true",
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"


def exchange_code_for_tokens(code: str) -> Dict[str, Any]:
    """Exchange authorization code for access and refresh tokens."""
    client_id, client_secret, redirect_uri = get_oauth_config()
    token_url = "https://oauth2.googleapis.com/token"

    response = requests.post(
        token_url,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )

    if not response.ok:
        raise RuntimeError(f"Failed to exchange token with Google: {response.text}")

    token_data = response.json()

    # Fetch user's email for session display
    email = None
    access_token = token_data.get("access_token")
    if access_token:
        try:
            userinfo = requests.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=5,
            )
            if userinfo.ok:
                email = userinfo.json().get("email")
        except Exception:
            pass

    return {
        "access_token": token_data.get("access_token"),
        "refresh_token": token_data.get("refresh_token"),
        "token_uri": token_url,
        "client_id": client_id,
        "client_secret": client_secret,
        "scopes": DRIVE_SCOPES,
        "email": email,
    }


def get_credentials_from_session(session_data: Dict[str, Any]) -> Credentials:
    """Reconstruct Google Credentials from stateless decrypted session data."""
    creds = Credentials(
        token=session_data.get("access_token"),
        refresh_token=session_data.get("refresh_token"),
        token_uri=session_data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=session_data.get("client_id"),
        client_secret=session_data.get("client_secret"),
        scopes=session_data.get("scopes", DRIVE_SCOPES),
    )

    # Refresh token if expired
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            session_data["access_token"] = creds.token
        except Exception as exc:
            raise RuntimeError(f"Google authorization expired or revoked. Please reconnect: {exc}")

    return creds


def list_drive_notebooks(
    creds: Credentials,
    search_query: str = "",
    page_token: Optional[str] = None,
    page_size: int = 25,
) -> Dict[str, Any]:
    """
    Search and list Jupyter / Colab notebooks (.ipynb) across My Drive and Shared Drives.
    """
    service = googleapiclient.discovery.build("drive", "v3", credentials=creds, cache_discovery=False)

    # Filter strictly for .ipynb files and exclude trashed items
    q_parts = [
        "trashed = false",
        "(mimeType = 'application/x-ipynb+json' or name contains '.ipynb')",
    ]

    if search_query:
        # Sanitize search query to prevent injection in Drive API query string
        clean_q = search_query.replace("'", "\\'").replace("\\", "\\\\")
        q_parts.append(f"name contains '{clean_q}'")

    q = " and ".join(q_parts)

    results = (
        service.files()
        .list(
            q=q,
            pageSize=min(page_size, 50),
            pageToken=page_token,
            fields="nextPageToken, files(id, name, mimeType, modifiedTime, size, iconLink)",
            orderBy="modifiedTime desc",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            spaces="drive",
        )
        .execute()
    )

    files = results.get("files", [])
    # Filter files strictly to ensure they end in .ipynb or have notebook mimetype
    notebooks = []
    for f in files:
        name = f.get("name", "")
        if name.lower().endswith(".ipynb") or f.get("mimeType") == "application/x-ipynb+json":
            notebooks.append(
                {
                    "id": f.get("id"),
                    "name": name if name.lower().endswith(".ipynb") else f"{name}.ipynb",
                    "modifiedTime": f.get("modifiedTime"),
                    "size": int(f.get("size", 0)) if f.get("size") else None,
                }
            )

    return {
        "notebooks": notebooks,
        "nextPageToken": results.get("nextPageToken"),
    }


def download_drive_notebook(creds: Credentials, file_id: str) -> Tuple[str, nbformat.NotebookNode]:
    """
    Download a notebook from Google Drive using authorized API request and return its filename and validated node.
    """
    service = googleapiclient.discovery.build("drive", "v3", credentials=creds, cache_discovery=False)

    # Get file metadata
    file_meta = service.files().get(fileId=file_id, fields="id, name, trashed", supportsAllDrives=True).execute()

    if file_meta.get("trashed"):
        raise ValueError(f"The file '{file_meta.get('name')}' is in Google Drive trash.")

    original_name = file_meta.get("name") or "notebook.ipynb"
    if not original_name.lower().endswith(".ipynb"):
        original_name = f"{original_name}.ipynb"

    # Download file content stream
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()

    raw_bytes = fh.getvalue()
    if not raw_bytes:
        raise ValueError(f"Notebook '{original_name}' is empty (0 bytes).")

    # Parse and sanitize notebook
    try:
        notebook = sanitize_and_parse_notebook(raw_bytes)
        return original_name, notebook
    except Exception as exc:
        raise ValueError(f"'{original_name}' is not a valid Jupyter Notebook JSON: {exc}")


def revoke_token(token: Optional[str]) -> bool:
    """Revoke Google OAuth token when disconnecting."""
    if not token:
        return True
    try:
        resp = requests.post(
            f"https://oauth2.googleapis.com/revoke?token={token}",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=5,
        )
        return resp.ok
    except Exception:
        return False

