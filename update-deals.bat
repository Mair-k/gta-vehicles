@echo off
setlocal
cd /d "%~dp0"
set "PY=py -3"
%PY% --version >nul 2>nul || set "PY=python"
%PY% --version >nul 2>nul || goto :nopy

echo [1/2] fetching this week's deals ...
%PY% scripts\update_deals.py
echo.
echo [2/2] rebuilding the page ...
%PY% scripts\build_site.py
echo.
echo Done. Open GTA线上全车辆清单.html
echo.
pause
exit /b 0

:nopy
echo [X] Python not found. Install Python 3, or run manually:
echo     python scripts/update_deals.py
echo     python scripts/build_site.py
pause
exit /b 1
