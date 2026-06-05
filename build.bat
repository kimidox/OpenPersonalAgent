@echo off
chcp 65001 >nul
echo ========================================
echo   PersonalWindowGLM 打包工具
echo ========================================
echo.
echo 【打包说明】
echo.
echo 1. 模型外置机制：
echo    - ASR/TTS模型不打包进exe，运行时自动下载
echo    - 模型存储位置：%APPDATA%\OpenPersonalAgent\model\
echo    - 大幅减小打包体积（约减少430MB）
echo.
echo 2. UPX压缩选项：
echo    - 目录模式（onedir）：默认启用UPX压缩
echo    - 单文件模式（onefile）：默认禁用UPX（启动慢）
echo    - UPX下载地址：https://github.com/upx/upx/releases
echo    - 安装后将UPX添加到PATH环境变量
echo.
echo 3. 打包前准备：
echo    - 清理 __pycache__ 目录
echo    - 清理 build 目录
echo    - 确保 .env 文件存在
echo.
echo 4. 打包后体积参考：
echo    - 目录模式（无UPX）：约 150-200 MB
echo    - 目录模式（有UPX）：约 100-120 MB
echo    - 单文件模式：约 150-180 MB
echo.
echo ========================================
echo.
echo 请选择打包方式:
echo   1. 目录模式 (onedir) - 生成文件夹，启动快，推荐
echo   2. 单文件模式 (onefile) - 生成单独exe，便于分发
echo   3. 目录模式 (禁用UPX) - 不使用UPX压缩
echo.
set /p choice=请输入选项 (1/2/3):

if "%choice%"=="1" goto onedir_upx
if "%choice%"=="2" goto onefile
if "%choice%"=="3" goto onedir_no_upx
echo 无效选项，请重新运行脚本
pause
exit

:onedir_upx
echo.
echo [INFO] 正在使用目录模式打包（启用UPX压缩）...
echo [INFO] 输出位置: dist\OpenPersonalAgent\
echo.
echo [步骤1] 清理临时文件...
if exist "__pycache__" rd /s /q "__pycache__"
if exist "build" rd /s /q "build"
for /d /r %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"
echo [完成] 临时文件已清理
echo.
echo [步骤2] 开始打包...
echo [提示] UPX压缩需要UPX已安装并添加到PATH
echo [提示] 如未安装UPX，请使用选项3（禁用UPX）
echo.
pyinstaller PersonalWindowGLM.spec --clean
if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo   ✓ 打包成功！
    echo ========================================
    echo.
    echo 输出目录: dist\OpenPersonalAgent\
    echo.
    echo 【后续步骤】
    echo 1. 首次运行时，模型会自动下载到用户数据目录
    echo 2. 或手动下载模型，详见 MODEL_DOWNLOAD.md
    echo 3. 配置文件位于 %APPDATA%\OpenPersonalAgent\.env
    echo.
    if exist "dist\OpenPersonalAgent" (
        echo 【体积信息】
        for /f %%A in ('dir /s "dist\OpenPersonalAgent" ^| findstr "File(s)"') do echo 打包目录总大小: %%A
    )
) else (
    echo.
    echo ✗ 打包失败，请检查错误信息
    echo [提示] 如果UPX相关错误，请尝试选项3（禁用UPX）
)
goto end

:onedir_no_upx
echo.
echo [INFO] 正在使用目录模式打包（禁用UPX压缩）...
echo [INFO] 输出位置: dist\OpenPersonalAgent\
echo.
echo [步骤1] 清理临时文件...
if exist "__pycache__" rd /s /q "__pycache__"
if exist "build" rd /s /q "build"
for /d /r %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"
echo [完成] 临时文件已清理
echo.
echo [步骤2] 临时禁用UPX...
echo [提示] 正在修改spec文件禁用UPX...
powershell -Command "(Get-Content 'PersonalWindowGLM.spec') -replace 'upx_enable = True', 'upx_enable = False' | Set-Content 'PersonalWindowGLM.spec'"
echo.
echo [步骤3] 开始打包...
pyinstaller PersonalWindowGLM.spec --clean
echo.
echo [步骤4] 恢复UPX配置...
powershell -Command "(Get-Content 'PersonalWindowGLM.spec') -replace 'upx_enable = False', 'upx_enable = True' | Set-Content 'PersonalWindowGLM.spec'"
echo.
if %errorlevel% equ 0 (
    echo ========================================
    echo   ✓ 打包成功！
    echo ========================================
    echo.
    echo 输出目录: dist\OpenPersonalAgent\
    echo.
    echo 【后续步骤】
    echo 1. 首次运行时，模型会自动下载到用户数据目录
    echo 2. 或手动下载模型，详见 MODEL_DOWNLOAD.md
    echo 3. 配置文件位于 %APPDATA%\OpenPersonalAgent\.env
    echo.
    if exist "dist\OpenPersonalAgent" (
        echo 【体积信息】
        for /f %%A in ('dir /s "dist\OpenPersonalAgent" ^| findstr "File(s)"') do echo 打包目录总大小: %%A
    )
) else (
    echo.
    echo ✗ 打包失败，请检查错误信息
)
goto end

:onefile
echo.
echo [INFO] 正在使用单文件模式打包...
echo [INFO] 输出位置: dist\OpenPersonalAgent.exe
echo.
echo [步骤1] 清理临时文件...
if exist "__pycache__" rd /s /q "__pycache__"
if exist "build" rd /s /q "build"
for /d /r %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d"
echo [完成] 临时文件已清理
echo.
echo [步骤2] 开始打包...
echo [提示] 单文件模式启动较慢（需解压到临时目录）
echo [提示] 单文件模式默认禁用UPX压缩
echo.
pyinstaller PersonalWindowGLM_onefile.spec --clean
if %errorlevel% equ 0 (
    echo.
    echo ========================================
    echo   ✓ 打包成功！
    echo ========================================
    echo.
    echo 输出文件: dist\OpenPersonalAgent.exe
    echo.
    echo 【后续步骤】
    echo 1. 首次运行时，模型会自动下载到用户数据目录
    echo 2. 或手动下载模型，详见 MODEL_DOWNLOAD.md
    echo 3. 配置文件位于 %APPDATA%\OpenPersonalAgent\.env
    echo.
    if exist "dist\OpenPersonalAgent.exe" (
        echo 【体积信息】
        for /f %%A in ('dir "dist\OpenPersonalAgent.exe" ^| findstr "OpenPersonalAgent.exe"') do echo 打包文件大小: %%A
    )
) else (
    echo.
    echo ✗ 打包失败，请检查错误信息
)
goto end

:end
echo.
echo ========================================
echo   打包完成
echo ========================================
echo.
echo 【注意事项】
echo - 模型文件不包含在打包结果中
echo - 首次运行程序会自动下载模型（约430MB）
echo - 如需提前下载模型，运行: python download_models.py
echo - 详细说明请查看 PACKAGING_GUIDE.md
echo.
pause