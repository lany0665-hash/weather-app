@echo off
title Weather App

cd /d "%~dp0"
start http://localhost:8000
python app.py

pause