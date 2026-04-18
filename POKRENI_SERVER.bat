@echo off
cd /d "%~dp0"
echo ========================================
echo  Knjiznica API v8.5.6 - Lokalni server
echo ========================================

REM Postavi env varijable iz .env datoteke
if exist ".env" (
    for /f "usebackq tokens=1,2 delims==" %%A in (".env") do (
        if not "%%A"=="" if not "%%A:~0,1%"=="#" set "%%A=%%B"
    )
    echo [OK] .env ucitan
) else (
    echo [UPOZORENJE] .env datoteka ne postoji!
    echo Kopirajte env_lokalni.env u .env i prilagodite vrijednosti.
    pause
    exit /b 1
)

REM Provjeri je li uvicorn instaliran
uvicorn --version >nul 2>&1
if errorlevel 1 (
    echo [INFO] Instaliram dependencies...
    pip install -r requirements.txt
)

echo.
echo Pokrecemo server na http://127.0.0.1:8000
echo Swagger docs: http://127.0.0.1:8000/docs
echo License admin: http://127.0.0.1:8000/admin/license/dashboard
echo.
echo Pritisnite Ctrl+C za zaustavljanje.
echo.

uvicorn app.server_main:app --reload --host 127.0.0.1 --port 8000
