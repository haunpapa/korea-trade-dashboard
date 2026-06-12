@echo off
chcp 65001 >nul
cd /d %~dp0
echo [관세청 데이터 수집 → GitHub 업로드]
py scripts\export_static.py --push || python scripts\export_static.py --push
echo.
pause
