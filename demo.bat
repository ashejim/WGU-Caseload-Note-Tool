@echo off
REM Launch the OFFLINE DEMO — the whole tool on synthetic sample data, with no
REM Salesforce/Mongoose login and no browser. Great for contributors.
REM   demo.bat            launch (builds sample data on first run)
REM   demo.bat --reset    rebuild the sample data from scratch
cd /d "%~dp0"
".venv\Scripts\python.exe" -m scripts.demo %*
