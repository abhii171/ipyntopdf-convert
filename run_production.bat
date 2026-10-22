@echo off
title NotebookFlow Production Website
echo ====================================================
echo Starting NotebookFlow Full Production Web Server...
echo ====================================================

cd /d "%~dp0"

:: Ensure frontend build exists
if not exist "frontend\dist\index.html" (
    echo Building frontend...
    cd frontend
    call npm run build
    cd ..
)

echo.
echo Server running at http://127.0.0.1:8000
echo Opening web browser...
start http://127.0.0.1:8000

cd backend
python -m uvicorn app:app --host 127.0.0.1 --port 8000
pause

