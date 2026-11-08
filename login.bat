@echo off
title Bing Rewards - One-Time Login
cls
echo ========================================================
echo   Bing Rewards - One-Time Browser Login
echo ========================================================
echo.
echo Launching browser... Please wait a few seconds.
echo.

"C:\Users\royar\AppData\Local\Python\pythoncore-3.15-64\python.exe" "%~dp0setup_login.py"

if exist "%~dp0browser_state.json" (
    echo.
    echo ========================================================
    echo   Uploading session to GitHub...
    echo ========================================================
    "C:\Program Files\Git\cmd\git.exe" -C "%~dp0." add browser_state.json .github/workflows/restock-monitor.yml monitor.py
    "C:\Program Files\Git\cmd\git.exe" -C "%~dp0." commit -m "Add Playwright browser session for permanent login"
    "C:\Program Files\Git\cmd\git.exe" -C "%~dp0." push origin main
    echo.
    echo ========================================================
    echo   ALL DONE! Your session is uploaded to GitHub.
    echo   The monitor will now run in the cloud automatically.
    echo   You never have to run this again!
    echo ========================================================
) else (
    echo.
    echo Error: browser_state.json was not created.
)

echo.
pause
