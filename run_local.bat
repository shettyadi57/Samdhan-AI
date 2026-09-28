@echo off
cd /d "%~dp0"
echo ========================================================
echo Starting SAMDHAN AI Local Development Environment
echo ========================================================

echo [1/2] Starting FastAPI Backend on http://127.0.0.1:8000 ...
start "SAMDHAN AI Backend" cmd /k "python -m uvicorn backend.integrity_pipeline:app --host 127.0.0.1 --port 8000 --reload"

echo [2/2] Starting Vite Frontend on http://localhost:5173 ...
start "SAMDHAN AI Frontend" cmd /k "npm run dev"

timeout /t 2 /nobreak >nul
echo Opening SAMDHAN AI in your browser...
start http://localhost:5173/

echo ========================================================
echo SAMDHAN AI is now running locally!
echo Backend Docs: http://127.0.0.1:8000/docs
echo Frontend UI:  http://localhost:5173/
echo ========================================================
