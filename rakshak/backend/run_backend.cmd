@echo off
cd /d "E:\PROGRAM_PROJECTS\SIH\anpr-new\rakshak\backend"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 >> uvicorn.out.log 2>> uvicorn.err.log