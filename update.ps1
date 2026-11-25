param(
 [Parameter(Mandatory=$true)][string]$DownloadUrl,
 [Parameter(Mandatory=$true)][string]$TargetDir,
 [Parameter(Mandatory=$true)][int]$ProcessId
)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$temp=$null
try {
 try { Wait-Process -Id $ProcessId -Timeout 30 -ErrorAction SilentlyContinue } catch {}
 $temp=Join-Path $env:TEMP ('DimasikUpdate-'+[guid]::NewGuid().ToString('N'))
 $zip=Join-Path $temp 'update.zip'
 $expanded=Join-Path $temp 'expanded'
 New-Item -ItemType Directory -Force -Path $expanded | Out-Null

 # curl.exe is faster than the legacy PowerShell web progress pipeline.
 $curl=Get-Command curl.exe -ErrorAction SilentlyContinue
 if ($curl) {
   & $curl.Source -L --fail --silent --show-error --retry 3 --retry-delay 1 --connect-timeout 20 --output $zip $DownloadUrl
   if ($LASTEXITCODE -ne 0) { throw "Download failed (curl exit code $LASTEXITCODE)." }
 } else {
   [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
   Invoke-WebRequest -Uri $DownloadUrl -OutFile $zip -UseBasicParsing
 }
 if (!(Test-Path $zip) -or (Get-Item $zip).Length -lt 1024) { throw 'Downloaded update archive is empty or incomplete.' }

 Expand-Archive -LiteralPath $zip -DestinationPath $expanded -Force
 $source=Join-Path $expanded 'Dimasik'
 if (!(Test-Path (Join-Path $source 'Dimasik.exe'))) {
   $source=Get-ChildItem $expanded -Directory | Select-Object -First 1 -ExpandProperty FullName
 }
 if (!(Test-Path (Join-Path $source 'Dimasik.exe'))) { throw 'Downloaded package does not contain Dimasik.exe.' }
 New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null

 # Multi-threaded copy; preserve the user's config.
 robocopy $source $TargetDir /E /MT:8 /R:1 /W:1 /XF config.json | Out-Null
 if ($LASTEXITCODE -ge 8) { throw 'Could not replace application files.' }

 Start-Process (Join-Path $TargetDir 'Dimasik.exe') -WorkingDirectory $TargetDir
 Remove-Item $temp -Recurse -Force -ErrorAction SilentlyContinue
} catch {
 Add-Type -AssemblyName PresentationFramework
 [System.Windows.MessageBox]::Show(('Update failed: '+$_.Exception.Message),'Dimasik updater') | Out-Null
}
