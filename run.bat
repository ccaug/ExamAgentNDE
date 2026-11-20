@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul || (echo Python no esta instalado o no esta en el PATH. Instala Python 3.10+ y marca "Add to PATH". & pause & exit /b 1)
if not exist .venv (python -m venv .venv)
call .venv\Scripts\activate.bat
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
if not exist .env copy .env.example .env >nul
where ollama >nul 2>nul || echo [AVISO] Ollama no esta instalado o no esta en el PATH (https://ollama.com).
echo.
echo ExamAgent NDE 2.1 - Panel: http://127.0.0.1:8765
echo Los modelos se eligen solos segun tu hardware; si faltan, el panel ofrece descargarlos.
echo (Deja esta ventana abierta mientras corriges. Ctrl+C para cerrar.)
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8765"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
pause
