@echo off
REM ============================================================
REM  Gera o instalador do Manhua Translator (rodar no Windows).
REM  Resultado: installer_output\ManhuaTranslator-Setup-X.Y.Z.exe
REM  Precisa de: Python 3.10-3.12 e Inno Setup 6 instalados.
REM ============================================================
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 goto :sem_python

if not exist .venv\Scripts\activate.bat py -3.12 -m venv .venv
if not exist .venv\Scripts\activate.bat py -3 -m venv .venv
call .venv\Scripts\activate.bat

python -m pip install --upgrade pip
pip install -r requirements-build.txt
if errorlevel 1 goto :erro

for /f %%v in ('python -c "from app_paths import APP_VERSION; print(APP_VERSION)"') do set VERSION=%%v

pyinstaller ManhuaTranslator.spec --noconfirm --clean
if errorlevel 1 goto :erro

set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" goto :sem_inno

"%ISCC%" /DAppVersion=%VERSION% installer.iss
if errorlevel 1 goto :erro

echo.
echo Pronto! Instalador em: installer_output\ManhuaTranslator-Setup-%VERSION%.exe
pause
exit /b 0

:sem_python
echo Python nao encontrado. Instale em https://www.python.org/downloads/ marcando "Add python.exe to PATH".
pause
exit /b 1

:sem_inno
echo Inno Setup 6 nao encontrado. Instale em https://jrsoftware.org/isdl.php e rode este arquivo de novo.
echo A pasta dist\ManhuaTranslator ja foi gerada e o app funciona rodando dist\ManhuaTranslator\ManhuaTranslator.exe
pause
exit /b 1

:erro
echo.
echo Ocorreu um erro. Role a janela para cima para ver a mensagem.
pause
exit /b 1
