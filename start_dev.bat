@echo off
title NotebookFlow Dev Environment
echo ====================================================
echo Starting NotebookFlow in Development Mode...
echo ====================================================

cd /d "%~dp0"

start "NotebookFlow Backend" cmd /k "cd backend && python -m uvicorn app:app --reload --port 8000"
start "NotebookFlow Frontend" cmd /k "cd frontend && npm run dev"

timeout /t 3 >nul
start http://localhost:5173

