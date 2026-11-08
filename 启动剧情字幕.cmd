@echo off
cd /d "%~dp0"
set "DOL_PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%DOL_PYTHON%" set "DOL_PYTHON=python"
"%DOL_PYTHON%" -X utf8 -u "%~dp0tools\story_subtitles.py"
if errorlevel 1 pause
