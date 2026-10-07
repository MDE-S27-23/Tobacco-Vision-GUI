@echo off
rem Builds dist\TobaccoVisionGUI.exe. Run "pip install -r requirements.txt" once first.
cd /d "%~dp0"

python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "TobaccoVisionGUI" ^
    --collect-all tkinterdnd2 ^
    main.py
if errorlevel 1 goto failed

echo.
echo Done. The program is at: dist\TobaccoVisionGUI.exe
pause
exit /b 0

:failed
echo.
echo BUILD FAILED
echo If  "No module named PyInstaller", run: pip install -r requirements.txt
pause
exit /b 1
