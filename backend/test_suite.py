"""
Comprehensive Automated Test Suite for NotebookFlow Serverless Architecture.
Tests local file conversion, stateless sessions, OAuth state security,
Drive conversion, error states, and temporary storage cleanup.
"""

import io
import os
import shutil
import tempfile
import time
from unittest.mock import MagicMock, patch
from zipfile import ZipFile

import nbformat
from fastapi.testclient import TestClient

# Ensure backend directory is in path
import sys
sys.path.insert(0, os.path.dirname(__file__))

from app import app
from session_manager import (
    create_csrf_state,
    decrypt_session_data,
    encrypt_session_data,
    verify_csrf_state,
)


def create_sample_notebook(title: str = "Test Notebook") -> bytes:
    """Helper to generate a valid v4 notebook in memory."""
    nb = nbformat.v4.new_notebook()
    nb.cells.append(nbformat.v4.new_markdown_cell(f"# {title}\nTesting serverless conversion."))
    nb.cells.append(nbformat.v4.new_code_cell("x = 10\nprint(x * 2)"))
    return nbformat.writes(nb).encode("utf-8")


client = TestClient(app)


def test_01_health_endpoint():
    """Verify health endpoint returns status, supported formats, and resource limits."""
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "html" in data["supported_formats"]
    assert "pdf" in data["supported_formats"]
    assert data["limits"]["max_file_size_mb"] == 15
    print("[PASS] Test 1: Health endpoint is operational.")


def test_02_single_notebook_to_html():
    """Test 1: Single notebook conversion to HTML packaged in ZIP."""
    nb_bytes = create_sample_notebook("HTML Export Test")
    files = [("files", ("analysis.ipynb", nb_bytes, "application/x-ipynb+json"))]
    data = {"output_format": "html"}

    res = client.post("/api/convert-zip", files=files, data=data)
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"

    # Unpack ZIP in memory and inspect contents
    with ZipFile(io.BytesIO(res.content)) as z:
        names = z.namelist()
        assert len(names) == 1
        assert names[0] == "analysis.html"
        html_content = z.read(names[0]).decode("utf-8")
        assert "HTML Export Test" in html_content
        assert "print" in html_content
    print("[PASS] Test 2: Single notebook to HTML conversion succeeded.")


def test_03_single_notebook_to_pdf():
    """Test 2: Single notebook conversion to PDF via Playwright Chromium."""
    nb_bytes = create_sample_notebook("PDF Export Test")
    files = [("files", ("document.ipynb", nb_bytes, "application/x-ipynb+json"))]
    data = {"output_format": "pdf"}

    res = client.post("/api/convert-zip", files=files, data=data)
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"

    with ZipFile(io.BytesIO(res.content)) as z:
        names = z.namelist()
        assert len(names) == 1
        assert names[0] == "document.pdf"
        pdf_bytes = z.read(names[0])
        # Validate standard PDF file signature %PDF-
        assert pdf_bytes.startswith(b"%PDF-")
    print("[PASS] Test 3: Single notebook to PDF conversion succeeded.")


def test_04_multiple_notebooks_to_zip():
    """Test 3: Multiple notebooks converted and packaged into one ZIP."""
    files = [
        ("files", ("nb1.ipynb", create_sample_notebook("NB 1"), "application/x-ipynb+json")),
        ("files", ("nb2.ipynb", create_sample_notebook("NB 2"), "application/x-ipynb+json")),
        ("files", ("nb3.ipynb", create_sample_notebook("NB 3"), "application/x-ipynb+json")),
    ]
    res = client.post("/api/convert-zip", files=files, data={"output_format": "html"})
    assert res.status_code == 200

    with ZipFile(io.BytesIO(res.content)) as z:
        names = z.namelist()
        assert len(names) == 3
        assert "nb1.html" in names
        assert "nb2.html" in names
        assert "nb3.html" in names
    print("[PASS] Test 4: Multiple notebooks to ZIP succeeded.")


def test_05_duplicate_filenames():
    """Test 4: Two files with identical names are disambiguated safely."""
    files = [
        ("files", ("report.ipynb", create_sample_notebook("First"), "application/x-ipynb+json")),
        ("files", ("report.ipynb", create_sample_notebook("Second"), "application/x-ipynb+json")),
    ]
    res = client.post("/api/convert-zip", files=files, data={"output_format": "html"})
    assert res.status_code == 200

    with ZipFile(io.BytesIO(res.content)) as z:
        names = z.namelist()
        assert len(names) == 2
        assert "report.html" in names
        assert "report_2.html" in names
    print("[PASS] Test 5: Duplicate filenames are safely disambiguated.")


def test_06_invalid_notebook_json():
    """Test 5: Corrupt / non-JSON file rejected with clear 400 error."""
    bad_bytes = b"This is plain text, not a valid Jupyter notebook."
    files = [("files", ("bad.ipynb", bad_bytes, "application/x-ipynb+json"))]
    res = client.post("/api/convert-zip", files=files, data={"output_format": "html"})
    assert res.status_code == 400
    assert "invalid notebook JSON" in res.json()["detail"]
    print("[PASS] Test 6: Invalid notebook JSON rejected with 400.")


def test_07_oversized_upload():
    """Test 6: File exceeding 15MB limit is rejected with 413."""
    huge_data = b"x" * (16 * 1024 * 1024)
    files = [("files", ("huge.ipynb", huge_data, "application/x-ipynb+json"))]
    res = client.post("/api/convert-zip", files=files, data={"output_format": "html"})
    assert res.status_code == 413
    assert "exceeds maximum size" in res.json()["detail"]
    print("[PASS] Test 7: Oversized notebook rejected with 413.")


def test_08_temporary_file_cleanup():
    """Test 8: Ensure temporary directories are cleaned up after request."""
    # Count current temporary directories matching prefix
    temp_root = tempfile.gettempdir()
    initial_dirs = [d for d in os.listdir(temp_root) if d.startswith("notebook_flow_")]

    files = [("files", ("clean.ipynb", create_sample_notebook("Cleanup"), "application/x-ipynb+json"))]
    res = client.post("/api/convert-zip", files=files, data={"output_format": "html"})
    assert res.status_code == 200

    # Wait a moment for background task to execute
    time.sleep(0.3)
    post_dirs = [d for d in os.listdir(temp_root) if d.startswith("notebook_flow_")]
    # Temporary directory should have been removed
    assert len(post_dirs) <= len(initial_dirs)
    print("[PASS] Test 8: Temporary file cleanup verified.")


def test_09_oauth_state_validation():
    """Test 9 & 10: OAuth CSRF state token generation, validation, and tampering rejection."""
    state = create_csrf_state()
    assert state is not None
    assert verify_csrf_state(state) is True

    # Tampered state
    tampered = state[:-4] + "abcd"
    assert verify_csrf_state(tampered) is False

    # Expired state
    assert verify_csrf_state(state, max_age_seconds=-1) is False
    print("[PASS] Test 9 & 10: OAuth CSRF state cryptographic validation verified.")


def test_10_stateless_session_encryption():
    """Test: Stateless session cookie encryption and decryption."""
    data = {
        "access_token": "ya29.sample_token_xyz",
        "email": "user@example.com",
        "refresh_token": "1//sample_refresh_abc",
    }
    encrypted = encrypt_session_data(data)
    assert encrypted != ""
    assert "sample_token_xyz" not in encrypted  # Ciphertext hides token

    decrypted = decrypt_session_data(encrypted)
    assert decrypted["access_token"] == data["access_token"]
    assert decrypted["email"] == data["email"]

    # Tampered cookie fails decryption gracefully
    assert decrypt_session_data("invalid-ciphertext-1234") is None
    print("[PASS] Test: Stateless session Fernet encryption verified.")


def test_11_drive_endpoints_unauthorized():
    """Test 13: Drive notebook listing & conversion reject unauthenticated requests."""
    res_list = client.get("/api/drive/notebooks")
    assert res_list.status_code == 401
    assert "Google Drive not connected" in res_list.json()["detail"]

    res_conv = client.post("/api/drive/convert", json={"file_ids": ["dummy-id"]})
    assert res_conv.status_code == 401
    print("[PASS] Test 11: Unauthenticated Drive calls correctly return 401.")


def test_12_drive_auth_url_diagnostic():
    """Test: Calling auth-url when credentials are not configured."""
    with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": "", "GOOGLE_CLIENT_SECRET": ""}):
        res = client.get("/api/drive/auth-url")
        assert res.status_code == 503
        assert "not configured" in res.json()["detail"]

    # When configured
    with patch.dict(os.environ, {
        "GOOGLE_CLIENT_ID": "mock-client-id.apps.googleusercontent.com",
        "GOOGLE_CLIENT_SECRET": "mock-secret"
    }):
        res = client.get("/api/drive/auth-url")
        assert res.status_code == 200
        assert "accounts.google.com" in res.json()["auth_url"]
        assert "mock-client-id" in res.json()["auth_url"]
    print("[PASS] Test 12: Drive auth-url handling verified.")


def test_13_mock_drive_listing_and_conversion():
    """Test 11, 12, 14, 15: Mock Google Drive API to verify listing, search, and conversion flow."""
    mock_session = {
        "access_token": "mock-access-token",
        "refresh_token": "mock-refresh-token",
        "email": "student@colab.edu",
        "client_id": "test-client",
        "client_secret": "test-secret",
    }
    cookie_val = encrypt_session_data(mock_session)
    client.cookies.set("nbf_session", cookie_val)

    # Test status endpoint
    res_status = client.get("/api/drive/status")
    assert res_status.status_code == 200
    assert res_status.json()["connected"] is True
    assert res_status.json()["email"] == "student@colab.edu"

    # Test mock notebook listing
    with patch("app.get_credentials_from_session") as mock_creds, patch("app.list_drive_notebooks") as mock_list:
        mock_creds.return_value = MagicMock()
        mock_list.return_value = {
            "notebooks": [
                {
                    "id": "file-123",
                    "name": "MachineLearning_Week1.ipynb",
                    "modifiedTime": "2026-10-22T10:00:00Z",
                    "size": 45000,
                }
            ],
            "nextPageToken": None,
        }
        res_list = client.get("/api/drive/notebooks?query=MachineLearning")
        assert res_list.status_code == 200
        assert len(res_list.json()["notebooks"]) == 1
        assert res_list.json()["notebooks"][0]["id"] == "file-123"

    # Test mock Drive conversion to ZIP
    with patch("app.get_credentials_from_session") as mock_creds, patch("app.download_drive_notebook") as mock_download:
        mock_creds.return_value = MagicMock()
        nb_node = nbformat.reads(create_sample_notebook("Colab Drive Model").decode("utf-8"), as_version=4)
        mock_download.return_value = ("MachineLearning_Week1.ipynb", nb_node)

        res_conv = client.post(
            "/api/drive/convert",
            json={"file_ids": ["file-123"], "output_format": "html"},
        )
        assert res_conv.status_code == 200
        assert res_conv.headers["content-type"] == "application/zip"

        with ZipFile(io.BytesIO(res_conv.content)) as z:
            names = z.namelist()
            assert "MachineLearning_Week1.html" in names
            assert "Colab Drive Model" in z.read("MachineLearning_Week1.html").decode("utf-8")

    print("[PASS] Test 13: Drive mock listing and conversion end-to-end verified.")


def test_14_disconnect_drive():
    """Test: Disconnecting clears session cookie."""
    cookie_val = encrypt_session_data({"access_token": "token-to-revoke"})
    client.cookies.set("nbf_session", cookie_val)

    with patch("app.revoke_token") as mock_revoke:
        mock_revoke.return_value = True
        res = client.post("/api/drive/disconnect")
        assert res.status_code == 200
        assert res.json()["status"] == "disconnected"
        set_cookie = res.headers.get("set-cookie", "")
        assert "nbf_session" in set_cookie
        assert "Max-Age=0" in set_cookie or 'expires=' in set_cookie.lower()

    # Clear cookie from client to simulate browser applying Set-Cookie
    client.cookies.delete("nbf_session")
    res_status = client.get("/api/drive/status")
    assert res_status.json()["connected"] is False
    print("[PASS] Test 14: Drive disconnect and session purge verified.")


def test_15_cors_headers():
    """Test 16: Verify CORS headers and preflight handling."""
    res = client.options(
        "/api/convert-zip",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert res.status_code == 200
    assert "access-control-allow-origin" in res.headers
    print("[PASS] Test 15: CORS configuration verified.")


if __name__ == "__main__":
    print("=" * 60)
    print("Running NotebookFlow Comprehensive Test Suite...")
    print("=" * 60)
    test_01_health_endpoint()
    test_02_single_notebook_to_html()
    test_03_single_notebook_to_pdf()
    test_04_multiple_notebooks_to_zip()
    test_05_duplicate_filenames()
    test_06_invalid_notebook_json()
    test_07_oversized_upload()
    test_08_temporary_file_cleanup()
    test_09_oauth_state_validation()
    test_10_stateless_session_encryption()
    test_11_drive_endpoints_unauthorized()
    test_12_drive_auth_url_diagnostic()
    test_13_mock_drive_listing_and_conversion()
    test_14_disconnect_drive()
    test_15_cors_headers()
    print("=" * 60)
    print("ALL 15 TEST SUITES PASSED SUCCESSFULLY!")
    print("=" * 60)
