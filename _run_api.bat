@echo off 
title SPED-API (porta 8000) 
cd /d "C:\Users\bmb19\OneDrive\Documentos\work\SPED\" 
call ".venv-win\Scripts\activate.bat" 
set PYTHONPATH=C:\Users\bmb19\OneDrive\Documentos\work\SPED\ 
python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000 
pause 
