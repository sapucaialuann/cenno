@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem ===========================================================================
rem  Builds Cenno for Windows:
rem     1. dist\Cenno\Cenno.exe          (PyInstaller)
rem     2. dist\Cenno-<version>-Setup.exe (Inno Setup installer)
rem
rem  Usage:
rem     build_win.bat              exe + installer
rem     build_win.bat exe-only     just the exe (no Inno Setup needed)
rem
rem  Optional environment variables:
rem     CENNO_ISCC          full path to ISCC.exe, if it is not in a usual place
rem     CENNO_SIGN_PFX      code-signing certificate (.pfx) to sign both binaries
rem     CENNO_SIGN_PWD      password for that certificate
rem ===========================================================================

set "VENV=.venv-build-win"
set "ISSU=Cenno.iss"

rem ---- version (single source of truth: the VERSION file) -------------------
set "VERSION="
for /f "usebackq delims=" %%v in ("VERSION") do if not defined VERSION set "VERSION=%%v"
if not defined VERSION (
    echo ERROR: could not read the version from the VERSION file.
    exit /b 1
)

echo == building Cenno v%VERSION%

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

echo == clean dist
if exist "dist" rmdir /s /q "dist"

echo == exe
"%VENV%\Scripts\pyinstaller" --noconfirm --clean --log-level WARN Cenno_win.spec

if not exist "dist\Cenno\Cenno.exe" (
    echo.
    echo BUILD FAILED - check the output above.
    exit /b 1
)

echo == bundle check
"%VENV%\Scripts\python" installer\check_bundle.py "dist\Cenno"
if errorlevel 1 (
    echo.
    echo BUILD FAILED - the build is not self-contained, see above.
    exit /b 1
)

rem ---- installer ------------------------------------------------------------
if /i "%~1"=="exe-only" goto :sign

echo == installer
call :find_iscc
if not defined ISCC (
    echo.
    echo WARNING: Inno Setup 6 not found, so no installer was built.
    echo          Install it from https://jrsoftware.org/isdl.php and run this
    echo          script again, or point CENNO_ISCC at ISCC.exe.
    goto :sign
)

rem The version lives only in the VERSION file; the installer gets it here.
"%ISCC%" /DAppVersion=%VERSION% "installer\%ISSU%"
if errorlevel 1 (
    echo.
    echo ERROR: the installer failed to compile - check the output above.
    exit /b 1
)

rem ---- code signing ---------------------------------------------------------
:sign
if defined CENNO_SIGN_PFX (
    if not defined CENNO_SIGN_PWD (
        echo.
        echo WARNING: CENNO_SIGN_PWD is not set, so nothing was signed.
        echo          Set it to the password of the certificate and build again.
    ) else (
        where signtool.exe >nul 2>&1
        if errorlevel 1 (
            echo.
            echo ERROR: signtool.exe not found. It comes with the Windows SDK.
            exit /b 1
        )
        echo == signing
        signtool sign /f "%CENNO_SIGN_PFX%" /p "%CENNO_SIGN_PWD%" /fd SHA256 /td SHA256 /tr http://timestamp.digicert.com "dist\Cenno\Cenno.exe"
        if errorlevel 1 (
            echo ERROR: could not sign Cenno.exe
            exit /b 1
        )
        if exist "dist\Cenno-%VERSION%-Setup.exe" (
            signtool sign /f "%CENNO_SIGN_PFX%" /p "%CENNO_SIGN_PWD%" /fd SHA256 /td SHA256 /tr http://timestamp.digicert.com "dist\Cenno-%VERSION%-Setup.exe"
            if errorlevel 1 (
                echo ERROR: could not sign the installer
                exit /b 1
            )
        )
    )
)

echo.
if exist "dist\Cenno-%VERSION%-Setup.exe" (
    echo BUILD_OK: dist\Cenno-%VERSION%-Setup.exe
) else (
    echo BUILD_OK: dist\Cenno\Cenno.exe
)
exit /b 0

rem ---- helpers --------------------------------------------------------------
:find_iscc
set "ISCC="
if defined CENNO_ISCC if exist "%CENNO_ISCC%" set "ISCC=%CENNO_ISCC%"
if defined ISCC exit /b 0
for %%p in (
    "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    "%ProgramFiles%\Inno Setup 6\ISCC.exe"
    "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
) do if not defined ISCC if exist "%%~p" set "ISCC=%%~p"
if defined ISCC exit /b 0
for /f "delims=" %%i in ('where iscc.exe 2^>nul') do if not defined ISCC set "ISCC=%%i"
exit /b 0
