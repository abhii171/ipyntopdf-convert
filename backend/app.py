from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile
import asyncio
import re

import nbformat
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from nbconvert import HTMLExporter, WebPDFExporter

app = FastAPI(title="Notebook Converter API", version="0.1.0")

# Allow all origins for seamless development and production access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_FILE_BYTES = 15 * 1024 * 1024
ALLOWED_FORMATS = {"html", "pdf"}

BASE_DIR = Path(__file__).resolve().parent
DIST_DIR = BASE_DIR.parent / "frontend" / "dist"


def safe_stem(filename: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")
    return (stem or "notebook")[:100]


def convert_single_notebook(input_path: Path, output_format: str, target: Path):
    """Synchronous conversion worker run in thread pool."""
    if output_format == "html":
        exporter = HTMLExporter()
        body, _ = exporter.from_filename(str(input_path))
        target.write_text(body, encoding="utf-8")
    else:
        exporter = WebPDFExporter()
        body, _ = exporter.from_filename(str(input_path))
        target.write_bytes(body)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "Notebook Converter",
        "supported_formats": ["html", "pdf"],
    }


@app.post("/api/convert-zip")
async def convert_zip(
    files: list[UploadFile] = File(...),
    output_format: str = Form("html"),
):
    output_format = output_format.lower().strip()
    if output_format not in ALLOWED_FORMATS:
        raise HTTPException(400, "output_format must be 'html' or 'pdf'.")
    if not files:
        raise HTTPException(400, "Upload at least one .ipynb file.")
    if len(files) > 20:
        raise HTTPException(400, "Maximum 20 notebooks per request.")

    with TemporaryDirectory(prefix="notebook_converter_") as temp:
        workdir = Path(temp)
        output_dir = workdir / "converted"
        output_dir.mkdir()
        used_names = set()
        converted = []

        for upload in files:
            original_name = upload.filename or "notebook.ipynb"
            if not original_name.lower().endswith(".ipynb"):
                raise HTTPException(400, f"{original_name}: only .ipynb files are supported.")

            data = await upload.read()
            if len(data) > MAX_FILE_BYTES:
                raise HTTPException(413, f"{original_name}: file exceeds 15 MB.")
            if not data:
                raise HTTPException(400, f"{original_name}: file is empty.")

            input_path = workdir / f"input_{len(converted)}.ipynb"
            try:
                notebook = nbformat.reads(data.decode("utf-8"), as_version=4)
                nbformat.validate(notebook)
                nbformat.write(notebook, input_path)
            except Exception as exc:
                raise HTTPException(400, f"{original_name}: invalid notebook JSON ({exc}).")

            base = safe_stem(original_name)
            unique_base = base
            counter = 2
            while unique_base.lower() in used_names:
                unique_base = f"{base}_{counter}"
                counter += 1
            used_names.add(unique_base.lower())

            ext = "html" if output_format == "html" else "pdf"
            target = output_dir / f"{unique_base}.{ext}"

            try:
                await asyncio.to_thread(convert_single_notebook, input_path, output_format, target)
                converted.append(target)
            except Exception as exc:
                raise HTTPException(
                    500,
                    f"Could not convert {original_name} to {output_format.upper()}. "
                    f"Details: {str(exc)[:300]}",
                )

        zip_path = workdir / f"converted_notebooks_{output_format}.zip"
        with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
            for path in converted:
                archive.write(path, arcname=path.name)

        zip_bytes = zip_path.read_bytes()
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{zip_path.name}"'},
        )


# Mount static assets from built frontend if available
if (DIST_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(DIST_DIR / "assets")), name="assets")


# Serve index.html or static files for frontend SPA
@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
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


# Mount static assets from built frontend if available
if (DIST_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(DIST_DIR / "assets")), name="assets")


# Serve index.html or static files for frontend SPA
@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
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

