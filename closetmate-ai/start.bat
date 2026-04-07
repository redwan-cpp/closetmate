@echo off
title ClosetMate Backend
echo.
echo  ================================
echo    ClosetMate AI Backend
echo    http://localhost:8000
echo    http://localhost:8000/docs
echo  ================================
echo.
echo  Press Ctrl+C to stop the server.
echo.

cd /d "%~dp0"
call venv\Scripts\activate.bat
venv\Scripts\uvicorn.exe main:app --host 0.0.0.0 --port 8000 --reload

pause
