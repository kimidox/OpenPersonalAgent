@echo off
chcp 65001 >nul
echo ========================================
echo   PersonalWindowGLM 打包工具
echo ========================================
echo.
echo 请选择打包方式:
echo   1. 目录模式 (onedir) - 生成文件夹，启动快
echo   2. 单文件模式 (onefile) - 生成单独exe，便于分发
echo.
set /p choice=请输入选项 (1 或 2):

if "%choice%"=="1" goto onedir
if "%choice%"=="2" goto onefile
echo 无效选项，请重新运行脚本
pause
exit

:onedir
echo.
echo [INFO] 正在使用目录模式打包...
echo [INFO] 输出位置: dist\PersonalWindowGLM\
pyinstaller PersonalWindowGLM.spec --clean
if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo   ✓ 打包成功！
    echo   输出目录: dist\PersonalWindowGLM\
    echo ========================================
) else (
    echo.
    echo ✗ 打包失败，请检查错误信息
)
goto end

:onefile
echo.
echo [INFO] 正在使用单文件模式打包...
echo [INFO] 输出位置: dist\PersonalWindowGLM.exe
pyinstaller PersonalWindowGLM_onefile.spec --clean
if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo   ✓ 打包成功！
    echo   输出文件: dist\PersonalWindowGLM.exe
    echo ========================================
) else (
    echo.
    echo ✗ 打包失败，请检查错误信息
)
goto end

:end
echo.
pause
