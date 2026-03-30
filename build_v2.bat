@echo off
chcp 65001 >nul
echo ================================================================================
echo Minecraft Mod 版本检测工具 v2 - 打包脚本
echo (参考 PCL2 逻辑重构版)
echo ================================================================================
echo.

REM 检查 Python
where py >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_PATH=py
    goto :build
)

where python >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_PATH=python
    goto :build
)

if exist "C:\Users\qqqee\AppData\Local\Programs\Python\Python313\python.exe" (
    set PYTHON_PATH=C:\Users\qqqee\AppData\Local\Programs\Python\Python313\python.exe
    goto :build
)

echo 错误：找不到 Python
pause
exit /b 1

:build
echo 开始打包 v2 版本...
echo.

REM 检查依赖
echo 检查依赖...
"%PYTHON_PATH%" -m pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo 安装 PyInstaller...
    "%PYTHON_PATH%" -m pip install pyinstaller
)

REM 清理旧的构建文件
if exist "build" (
    echo 清理旧的构建文件...
    rmdir /s /q build
)

if exist "dist\MinecraftModCheckerV2" (
    echo 清理旧的发布文件...
    rmdir /s /q "dist\MinecraftModCheckerV2"
)

echo.
echo 使用 PyInstaller 打包...
echo.

REM 使用 PyInstaller 打包
REM 注意：不再打包 config.json，让程序在运行时自动创建
"%PYTHON_PATH%" -m PyInstaller --clean ^
    --onefile ^
    --name "MinecraftModCheckerV2" ^
    --icon=NONE ^
    --console ^
    --hidden-import=requests ^
    --hidden-import=packaging ^
    --hidden-import=concurrent.futures ^
    --hidden-import=dataclasses ^
    mod_version_checker_v2.py

if %errorlevel% equ 0 (
    echo.
    echo ================================================================================
    echo 打包成功！
    echo ================================================================================
    echo.
    echo 可执行文件位置：dist\MinecraftModCheckerV2.exe
    echo.
    echo 请将以下文件一起分发：
    echo   - dist\MinecraftModCheckerV2.exe
    echo   - config.json (配置文件，可选)
    echo   - 配置兼容性说明.md (配置说明，可选)
    echo   - README.md (使用说明，可选)
    echo.
    echo v2 版本新特性:
    echo   - Hash 精确匹配 (CurseForge: MurmurHash2, Modrinth: SHA1)
    echo   - 智能缓存机制 (6 小时缓存)
    echo   - 并行查询优化 (同时查询两个平台)
    echo   - 精确版本和加载器匹配
    echo   - 批量 API 调用减少请求次数
    echo.
    echo 可以运行 test_exe.bat 测试程序是否正常
    echo.
    pause
    start dist
) else (
    echo.
    echo 打包失败！请检查错误信息。
    echo.
    pause
)
