@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo  DiskCC build script  (output: dist\DiskCC.exe)
echo ============================================

where python >nul 2>nul || (echo Python not found, install Python 3.9+ first && pause && exit /b 1)

echo [1/3] Installing dependencies (using Tencent PyPI mirror)...
set MIRROR=https://mirrors.cloud.tencent.com/pypi/simple
python -m pip install --upgrade pip -i %MIRROR%
python -m pip install -r requirements.txt -i %MIRROR%
python -m pip install -r requirements-build.txt -i %MIRROR%

echo [2/3] Cleaning old build...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
rem 注意：DiskCC.spec 是项目自带且手工维护的打包配置，绝不能删除！

echo [3/3] Building single-file exe with PyInstaller (DiskCC.spec)...
python -m PyInstaller --noconfirm --clean DiskCC.spec

if errorlevel 1 (
  echo Build FAILED
  pause
  exit /b 1
)

echo [3.5/3] Computing SHA256 (for antivirus whitelisting)...
certutil -hashfile dist\DiskCC.exe SHA256 > dist\DiskCC.exe.sha256.txt
type dist\DiskCC.exe.sha256.txt

rem Remove intermediate build folder; the single exe is self-contained
if exist build rmdir /s /q build

echo.
echo =====================================================
echo  DONE. The final program is a SINGLE file:
echo    dist\DiskCC.exe
echo  Share it by sending ONLY this one exe file.
echo  It is fully self-contained and runs on any Windows PC
echo  (no install, no Python, no extra folders needed).
echo =====================================================
pause
