@echo off
title ClosetMate Backend

:: Get local LAN IP (first non-loopback IPv4)
for /f "tokens=2 delims=:" %%A in ('ipconfig ^| findstr /C:"IPv4"') do (
    set "LOCAL_IP=%%A"
    goto :found
)
:found
set LOCAL_IP=%LOCAL_IP: =%

echo.
echo  ============================================================
echo    ClosetMate AI Backend
echo  ============================================================
echo.
echo    Local:   http://localhost:8000
echo    Network: http://%LOCAL_IP%:8000
echo    API Docs: http://%LOCAL_IP%:8000/docs
echo.
echo    The Expo app will auto-connect to: http://%LOCAL_IP%:8000
echo    (as long as your phone is on the same Wi-Fi)
echo.
echo    Press Ctrl+C to stop the server.
echo  ============================================================
echo.

cd /d "%~dp0"
call venv\Scripts\activate.bat
venv\Scripts\uvicorn.exe main:app --host 0.0.0.0 --port 8000 --reload

pause
