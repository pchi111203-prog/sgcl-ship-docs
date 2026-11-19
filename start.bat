@echo off
REM Khoi chay SGCL tren Windows - mo http://localhost:8000 sau khi chay
cd /d "%~dp0"
if not exist frontend\dist (
  cd frontend
  call npm install
  call npm run build
  cd ..
)
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
