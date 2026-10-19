@echo off
rem Start the company-network site (see docs\deploy-lan-vi.md). Double-click, or: start-lan.cmd [start|stop|backup] [IP]
rem Runs start-lan.ps1 without changing the PowerShell execution policy of this computer.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-lan.ps1" %*
if "%~1"=="" pause
