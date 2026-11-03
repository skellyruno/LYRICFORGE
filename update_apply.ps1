param(
  [Parameter(Mandatory=$true)][string]$InstallDir,
  [Parameter(Mandatory=$true)][string]$PreparedDir,
  [Parameter(Mandatory=$true)][int]$OldPid,
  [Parameter(Mandatory=$true)][string]$LogPath
)

$ErrorActionPreference = "Stop"
function Write-UpdateLog([string]$Text) {
  $line = (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " " + $Text
  [System.IO.File]::AppendAllText($LogPath, $line + [Environment]::NewLine)
}

$target = [System.IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
$stage = [System.IO.Path]::GetFullPath($PreparedDir).TrimEnd('\')
$parent = Split-Path -Parent $target
$name = Split-Path -Leaf $target
$incoming = Join-Path $parent ($name + ".incoming-" + [guid]::NewGuid().ToString('N'))
$backup = Join-Path $parent ($name + ".previous")
$rolledBack = $false
$renamed = $false

try {
  Write-UpdateLog "Installing verified SkellyMotion update from staging directory"
  if (-not (Test-Path -LiteralPath (Join-Path $stage 'SkellyMotion.exe'))) {
    throw "The staged update has no SkellyMotion.exe"
  }
  if (-not (Test-Path -LiteralPath (Join-Path $stage '_internal'))) {
    throw "The staged update has no _internal runtime"
  }
  if (-not (Test-Path -LiteralPath $target)) { throw "Installed app directory is missing" }

  # Copy before touching the working install. Copy across disks is supported.
  New-Item -ItemType Directory -Path $incoming -Force | Out-Null
  Copy-Item -Path (Join-Path $stage '*') -Destination $incoming -Recurse -Force
  if (-not (Test-Path -LiteralPath (Join-Path $incoming 'SkellyMotion.exe'))) {
    throw "The new app copy is incomplete"
  }
  Write-UpdateLog "Update copied; waiting for old EXE to exit"
  try { Wait-Process -Id $OldPid -Timeout 75 -ErrorAction Stop }
  catch {
    $running = Get-Process -Id $OldPid -ErrorAction SilentlyContinue
    if ($running) { throw "SkellyMotion is still running; cannot replace its files" }
  }

  # Keep one backup for rollback. Never touch %LOCALAPPDATA%\LyricForge user data.
  if (Test-Path -LiteralPath $backup) {
    Remove-Item -LiteralPath $backup -Recurse -Force
  }
  $moved = $false
  for ($i = 0; $i -lt 15 -and -not $moved; $i++) {
    try {
      Rename-Item -LiteralPath $target -NewName (Split-Path -Leaf $backup) -ErrorAction Stop
      $moved = $true
    } catch { Start-Sleep -Milliseconds 750 }
  }
  if (-not $moved) { throw "Could not move the previous app folder" }
  $renamed = $true
  Rename-Item -LiteralPath $incoming -NewName $name
  if (-not (Test-Path -LiteralPath (Join-Path $target 'SkellyMotion.exe'))) {
    throw "Updated app missing after install"
  }
  Write-UpdateLog "Update installed; previous version retained in " + $backup
  Start-Process -FilePath (Join-Path $target "SkellyMotion.exe") -WorkingDirectory $target
  Write-UpdateLog "New SkellyMotion started"
} catch {
  Write-UpdateLog ("UPDATE FAILED: " + $_.Exception.Message)
  if ($renamed -and -not (Test-Path -LiteralPath $target) -and
      (Test-Path -LiteralPath $backup)) {
    try {
      Rename-Item -LiteralPath $backup -NewName $name
      $rolledBack = $true
      Write-UpdateLog "Previous version restored"
    } catch { Write-UpdateLog ("ROLLBACK FAILED: " + $_.Exception.Message) }
  }
  if ($rolledBack) {
    try {
      Start-Process -FilePath (Join-Path $target "SkellyMotion.exe") -WorkingDirectory $target
    } catch {}
  }
} finally {
  if (Test-Path -LiteralPath $incoming) {
    try { Remove-Item -LiteralPath $incoming -Recurse -Force } catch {}
  }
}
