# Сборка Fluidd Desktop: PyInstaller (dist\FluiddDesktop) + установщик Inno Setup (dist\FluiddDesktop-Setup-<версия>.exe).
# Запуск: powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
$version = & $python -c "import fluid_desktop; print(fluid_desktop.__version__)"
Write-Host "Version: $version"

& $python -m pip install -q -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

& $python -m PyInstaller --noconfirm --clean --noconsole `
    --name FluiddDesktop `
    --icon assets\icon.ico `
    --exclude-module tkinter `
    main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# Убираем из сборки то, что не нужно приложению: отладочные ресурсы WebEngine, DevTools,
# QML и переводы кроме русского/английского. Это ~200 МБ.
$qt = "dist\FluiddDesktop\_internal\PySide6"
Remove-Item -Force "$qt\resources\*.debug.*", "$qt\resources\qtwebengine_devtools_resources*.pak" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "$qt\qml" -ErrorAction SilentlyContinue
Get-ChildItem "$qt\translations\qtwebengine_locales\*.pak" |
    Where-Object { $_.BaseName -notin @("ru", "en-US") } | Remove-Item -Force
Get-ChildItem "$qt\translations\*.qm" |
    Where-Object { $_.BaseName -notmatch "_(ru|en)$" } | Remove-Item -Force

$iscc = @(
    (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source,
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 (ISCC.exe) not found: winget install JRSoftware.InnoSetup" }

& $iscc "/DAppVersion=$version" installer\FluiddDesktop.iss
if ($LASTEXITCODE -ne 0) { throw "ISCC failed" }

Write-Host "Done: dist\FluiddDesktop-Setup-$version.exe"
