$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Fail($Text) { Write-Host ""; Write-Host "ERROR: $Text" -ForegroundColor Red; Read-Host "Press Enter to close"; exit 1 }

Write-Host "== Checking Python 3.12 ==" -ForegroundColor Cyan
$Python = $null
if (Get-Command py.exe -ErrorAction SilentlyContinue) {
    & py -3.12 --version *> $null
    if ($LASTEXITCODE -eq 0) { $Python = "launcher" }
}
if (-not $Python) {
    $PythonExe = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    if (Test-Path $PythonExe) { $Python = $PythonExe }
}
if (-not $Python) {
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) { Fail "Python 3.12 is missing and winget is unavailable. Install Python 3.12 from python.org." }
    & winget install --id Python.Python.3.12 -e --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { Fail "Python installation failed. Install Python 3.12 manually and retry." }
    $env:Path = "$env:LOCALAPPDATA\Programs\Python\Python312;$env:LOCALAPPDATA\Programs\Python\Python312\Scripts;$env:Path"
    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        & py -3.12 --version *> $null
        if ($LASTEXITCODE -eq 0) { $Python = "launcher" }
    }
    if (-not $Python) {
        $PythonExe = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
        if (Test-Path $PythonExe) { $Python = $PythonExe }
    }
}
if (-not $Python) { Fail "Python was installed but could not be found. Restart Windows and run setup again." }

Write-Host "== Creating virtual environment ==" -ForegroundColor Cyan
if (-not (Test-Path (Join-Path $Root ".venv\Scripts\python.exe"))) {
    if ($Python -eq "launcher") { & py -3.12 -m venv .venv } else { & $Python -m venv .venv }
    if ($LASTEXITCODE -ne 0) { Fail "Could not create Python virtual environment." }
}
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

Write-Host "== Installing Python packages ==" -ForegroundColor Cyan
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Fail "pip upgrade failed." }
& $VenvPython -m pip install -r (Join-Path $Root "requirements.txt")
if ($LASTEXITCODE -ne 0) { Fail "Python packages installation failed." }

Write-Host "== Downloading Russian speech model ==" -ForegroundColor Cyan
$Models = Join-Path $Root "models"
$ModelDir = Join-Path $Models "vosk-model-small-ru-0.22"
if (-not (Test-Path $ModelDir)) {
    New-Item -ItemType Directory -Force -Path $Models | Out-Null
    $ModelZip = Join-Path $env:TEMP "vosk-model-small-ru-0.22.zip"
    try {
        Invoke-WebRequest "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip" -OutFile $ModelZip
        Expand-Archive -LiteralPath $ModelZip -DestinationPath $Models -Force
    } catch { Fail "Could not download or extract Vosk model: $($_.Exception.Message)" }
    finally { if (Test-Path $ModelZip) { Remove-Item $ModelZip -Force -ErrorAction SilentlyContinue } }
}
if (-not (Test-Path (Join-Path $ModelDir "conf\model.conf"))) { Fail "Vosk model folder is incomplete. Delete the model folder and rerun setup." }

Write-Host "== Checking Ollama ==" -ForegroundColor Cyan
$OllamaCmd = Get-Command ollama.exe -ErrorAction SilentlyContinue
$OllamaExe = if ($OllamaCmd) { $OllamaCmd.Source } else { $null }
if (-not $OllamaExe) {
    $Candidates = @((Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"), (Join-Path $env:ProgramFiles "Ollama\ollama.exe"))
    $OllamaExe = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $OllamaExe) {
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) { Fail "Ollama is missing and winget is unavailable. Install it from ollama.com." }
    & winget install --id Ollama.Ollama -e --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { Fail "Ollama installation failed. Install it manually and rerun setup." }
    $Candidates = @((Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"), (Join-Path $env:ProgramFiles "Ollama\ollama.exe"))
    $OllamaExe = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $OllamaExe) { Fail "Ollama was installed but could not be located. Restart Windows and rerun setup." }

Write-Host "== Starting Ollama and downloading Qwen ==" -ForegroundColor Cyan
try { Invoke-RestMethod "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null }
catch {
    Start-Process -FilePath $OllamaExe -ArgumentList "serve" -WindowStyle Hidden
    $Ready = $false
    for ($i = 0; $i -lt 45; $i++) {
        Start-Sleep -Seconds 2
        try { Invoke-RestMethod "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null; $Ready = $true; break } catch {}
    }
    if (-not $Ready) { Fail "Ollama server did not start. Open Ollama from Start menu and rerun setup." }
}
& $OllamaExe pull qwen2.5:3b
if ($LASTEXITCODE -ne 0) { Fail "Could not download Qwen 2.5 3B. Check internet and disk space, then rerun setup." }

Write-Host "== Creating desktop shortcut ==" -ForegroundColor Cyan
$Shell = New-Object -ComObject WScript.Shell
$Desktop = [Environment]::GetFolderPath("Desktop")
$Shortcut = $Shell.CreateShortcut((Join-Path $Desktop "Димасик.lnk"))
$Shortcut.TargetPath = $VenvPython
$Shortcut.Arguments = '"' + (Join-Path $Root "assistant\main.py") + '"'
$Shortcut.WorkingDirectory = $Root
$Shortcut.Save()

Write-Host ""
Write-Host "Installation completed. Start Димасик from the desktop shortcut." -ForegroundColor Green
Read-Host "Press Enter to close"
exit 0
