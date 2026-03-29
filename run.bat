@echo off
chcp 65001 >nul
echo ================================================================================
echo Minecraft Mod 版本检测工具
echo ================================================================================
echo.

REM 尝试多种 Python 路径
set PYTHON_PATH=

REM 1. 尝试 py 启动器
where py >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_PATH=py
    goto :run
)

REM 2. 尝试 python 命令
where python >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_PATH=python
    goto :run
)

REM 3. 尝试用户特定路径
if exist "C:\Users\qqqee\AppData\Local\Programs\Python\Python313\python.exe" (
    set PYTHON_PATH=C:\Users\qqqee\AppData\Local\Programs\Python\Python313\python.exe
    goto :run
)

REM 4. 尝试 Python 312
if exist "C:\Users\qqqee\AppData\Local\Programs\Python\Python312\python.exe" (
    set PYTHON_PATH=C:\Users\qqqee\AppData\Local\Programs\Python\Python312\python.exe
    goto :run
)

REM 5. 尝试 Python 311
if exist "C:\Users\qqqee\AppData\Local\Programs\Python\Python311\python.exe" (
    set PYTHON_PATH=C:\Users\qqqee\AppData\Local\Programs\Python\Python311\python.exe
    goto :run
)

REM 6. 尝试系统路径
if exist "C:\Python313\python.exe" (
    set PYTHON_PATH=C:\Python313\python.exe
    goto :run
)

if exist "C:\Python312\python.exe" (
    set PYTHON_PATH=C:\Python312\python.exe
    goto :run
)

:check_failed
echo 错误：找不到 Python，请确保 Python 已安装并添加到 PATH
echo 或者修改此脚本中的 PYTHON_PATH 变量指向您的 Python 安装路径
pause
exit /b 1

:run
"%PYTHON_PATH%" "%~dp0mod_version_checker.py"
pause
