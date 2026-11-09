@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 goto :error
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
if errorlevel 1 goto :error
python -m pip install -r requirements-local.txt
if errorlevel 1 goto :error
python -m playwright install chromium
if errorlevel 1 goto :error
if not exist ".env" (
  echo.
  echo Missing .env file.
  echo Run: vercel link
  echo Then: vercel env pull .env --environment=production
  echo Keep .env private. Never upload it to GitHub.
  pause
  exit /b 1
)
findstr /b /c:"DATABASE_URL=" ".env" >nul
if errorlevel 1 (
  findstr /b /c:"POSTGRES_URL=" ".env" >nul
  if errorlevel 1 (
    echo The .env file has no DATABASE_URL or POSTGRES_URL.
    echo Pull the production Neon environment with: vercel env pull .env --environment=production
    pause
    exit /b 1
  )
)
echo.
echo Mirage local sender is starting.
echo Open http://127.0.0.1:5000/whatsapp and click Connect WhatsApp / QR.
echo Keep this window open while sending.
python app.py
goto :eof
:error
echo.
echo Setup failed. Review the message above and try again.
pause
exit /b 1
