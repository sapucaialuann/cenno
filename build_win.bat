@echo off
setlocal
cd /d "%~dp0"

set VENV=.venv-build-win

if not exist "%VENV%\Scripts\python.exe" (
    python -m venv "%VENV%"
    "%VENV%\Scripts\pip" install --upgrade pip -q
)
"%VENV%\Scripts\pip" install -q -r requirements-build-win.txt

echo == icon
"%VENV%\Scripts\python" -c ^
  "from PIL import Image; img=Image.open('assets/icon_1024.png').resize((256,256),Image.LANCZOS); img.save('assets/icon.ico')"
if errorlevel 1 (
    echo WARNING: Could not create icon.ico, building without it.
)

echo == exe
"%VENV%\Scripts\pyinstaller" --noconfirm --clean --log-level WARN Cenno_win.spec

if exist "dist\Cenno\Cenno.exe" (
    echo.
    echo BUILD_OK: dist\Cenno\Cenno.exe
) else (
    echo BUILD FAILED – check output above.
    exit /b 1
)
