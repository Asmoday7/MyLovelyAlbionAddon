@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 -m albion_trade_desk serve --open
) else (
  python -m albion_trade_desk serve --open
)
if errorlevel 1 pause
