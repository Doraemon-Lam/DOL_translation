@echo off
cd /d "%~dp0"
echo Select translation mode:
echo   1. DeepSeek API
echo   2. Local Hunyuan translation 1.8B (fast)
echo   3. Local Qwen 2.5 7B (quality)
choice /c 123 /n /m "Enter 1, 2 or 3: "
if errorlevel 3 (set "TASK_PROVIDER=local") else if errorlevel 2 (set "TASK_PROVIDER=local-fast") else (set "TASK_PROVIDER=deepseek")
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Load.ps1" -NoUi
if errorlevel 1 (
  echo Failed to load localization. Start the game first and check build\bin\loader.log.
  pause
  exit /b 1
)
python -X utf8 -u "%~dp0tools\auto_quest.py" --provider %TASK_PROVIDER%
pause
