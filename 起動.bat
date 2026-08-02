@echo off
rem ARK Breeding Timer 起動用（コンソールを出さずに起動する）
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
if not exist "%PY%" set "PY=pythonw"
start "" "%PY%" "%~dp0ark_breeding_timer.py"
