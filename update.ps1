param(
 [Parameter(Mandatory=$true)][string]$DownloadUrl,
 [Parameter(Mandatory=$true)][string]$TargetDir,
 [Parameter(Mandatory=$true)][int]$ProcessId
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
try {
 try { Wait-Process -Id $ProcessId -Timeout 30 -ErrorAction SilentlyContinue } catch {}
 $temp=Join-Path $env:TEMP ('DimasikUpdate-'+[guid]::NewGuid().ToString('N'))
 $zip=Join-Path $temp 'update.zip'; $expanded=Join-Path $temp 'expanded'
 New-Item -ItemType Directory -Force -Path $expanded | Out-Null
 Invoke-WebRequest -Uri $DownloadUrl -OutFile $zip
 Expand-Archive -LiteralPath $zip -DestinationPath $expanded -Force
 $source=Join-Path $expanded 'Dimasik'
 if (!(Test-Path (Join-Path $source 'Dimasik.exe'))) { $source=Get-ChildItem $expanded -Directory | Select-Object -First 1 -ExpandProperty FullName }
 if (!(Test-Path (Join-Path $source 'Dimasik.exe'))) { throw 'Downloaded package does not contain Dimasik.exe.' }
 New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
 robocopy $source $TargetDir /E /R:3 /W:1 /XF config.json | Out-Null
 if ($LASTEXITCODE -ge 8) { throw 'Could not replace application files.' }
 Start-Process (Join-Path $TargetDir 'Dimasik.exe') -WorkingDirectory $TargetDir
 Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue
} catch {
 Add-Type -AssemblyName PresentationFramework
 [System.Windows.MessageBox]::Show(('Update failed: '+$_.Exception.Message),'Dimasik updater') | Out-Null
}
