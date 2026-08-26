# PersonalWindowGLM 一键打包脚本（Windows）
#
# 产物链：PyInstaller(后端 onedir) → Tauri resources → NSIS 安装包
# 用法：
#   powershell -File build_release.ps1              # 完整打包
#   powershell -File build_release.ps1 -SkipBackend  # 后端无改动时跳过 PyInstaller
#
# 前置要求：
#   - Python 3.11 + requirements.txt 依赖 + pyinstaller
#   - Node.js 18+（frontend/node_modules 已安装）
#   - Rust MSVC 工具链
# 详细说明见 PACKAGING_GUIDE.md

param(
    [switch]$SkipBackend
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

# ---------- 1. PyInstaller 打包 Python 后端（onedir） ----------
if (-not $SkipBackend) {
    Write-Host "`n[1/2] PyInstaller 打包后端 sidecar..." -ForegroundColor Cyan
    Push-Location $root
    try {
        python -m PyInstaller backend_service.spec --noconfirm --distpath dist-sidecar
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败（exit=$LASTEXITCODE）" }
    }
    finally { Pop-Location }

    $backendExe = Join-Path $root "dist-sidecar\backend_service\backend_service.exe"
    if (-not (Test-Path $backendExe)) { throw "未找到产物: $backendExe" }
    Write-Host "后端产物: $backendExe" -ForegroundColor Green
}

# ---------- 2. Tauri 构建安装包（NSIS） ----------
Write-Host "`n[2/2] Tauri 构建安装包..." -ForegroundColor Cyan
Push-Location (Join-Path $root "frontend")
try {
    npm run tauri build
    if ($LASTEXITCODE -ne 0) { throw "tauri build 失败（exit=$LASTEXITCODE）" }
}
finally { Pop-Location }

# ---------- 汇总产物 ----------
$bundleDir = Join-Path $root "frontend\src-tauri\target\release\bundle\nsis"
$installers = Get-ChildItem -Path $bundleDir -Filter "*-setup.exe" -ErrorAction SilentlyContinue
if ($installers) {
    Write-Host "`n打包完成，安装包:" -ForegroundColor Green
    $installers | ForEach-Object {
        Write-Host ("  {0}  ({1:N0} MB)" -f $_.FullName, ($_.Length / 1MB)) -ForegroundColor Green
    }
} else {
    Write-Warning "未在 $bundleDir 找到 *-setup.exe，请检查上方构建日志"
}
