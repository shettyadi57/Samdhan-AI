# SAMDHAN AI - Local Launcher PowerShell Script
Set-Location -Path $PSScriptRoot
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host " Starting SAMDHAN AI Local Development Environment" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Cyan

# Start FastAPI backend
Write-Host "[1/2] Starting FastAPI Backend on http://127.0.0.1:8000 ..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "python -m uvicorn backend.integrity_pipeline:app --host 127.0.0.1 --port 8000 --reload"

# Start Vite frontend
Write-Host "[2/2] Starting Vite Frontend on http://localhost:5173 ..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "npm run dev"

Start-Sleep -Seconds 2
Write-Host "Opening SAMDHAN AI in your browser..." -ForegroundColor Green
Start-Process "http://localhost:5173/"

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host " SAMDHAN AI is now running locally!" -ForegroundColor Green
Write-Host " Frontend UI:  http://localhost:5173/" -ForegroundColor White
Write-Host " Backend Docs: http://127.0.0.1:8000/docs" -ForegroundColor White
Write-Host "========================================================" -ForegroundColor Cyan
