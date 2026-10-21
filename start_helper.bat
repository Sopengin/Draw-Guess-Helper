@echo off
cd /d "%~dp0"
echo ============================================
echo  Draw & Guess Assistant - helper
echo ============================================
python helper\main.py --config config.json
echo.
echo helper stopped.
pause
