@echo off
rem Builds dist\TobaccoVisionGUI.exe. Run "pip install -r requirements.txt" once first.
cd /d "%~dp0"

python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name "TobaccoVisionGUI" ^
    --collect-all tkinterdnd2 ^
    main.py
if errorlevel 1 goto failed

rem Check the exe has everything inside it
dist\TobaccoVisionGUI.exe --self-test "%TEMP%\TobaccoVisionGUI-selftest.txt"
set result=%errorlevel%
type "%TEMP%\TobaccoVisionGUI-selftest.txt"
if not "%result%"=="0" goto selftest_failed

echo.
echo Done. The program is at: dist\TobaccoVisionGUI.exe
pause
exit /b 0

:selftest_failed
echo.
echo BUILD FAILED: the exe was built but its self-test failed (see above).
echo A "No module named ..." error means a package is missing from requirements.txt
pause
exit /b 1

:failed
echo.
echo BUILD FAILED
echo If  "No module named PyInstaller", run: pip install -r requirements.txt
pause
exit /b 1
