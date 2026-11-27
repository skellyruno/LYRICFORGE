param([string]$Old,[string]$OldLedger,[string]$New,[string]$NewLedger,[string]$Evidence='integrated-cleanup-evidence')
$ErrorActionPreference='Stop'
$Old=(Resolve-Path $Old).Path;$OldLedger=(Resolve-Path $OldLedger).Path
$New=(Resolve-Path $New).Path;$NewLedger=(Resolve-Path $NewLedger).Path
if ((Get-FileHash $Old).Hash.ToLowerInvariant() -ne '2ca6062fa7aad995dd9b874398b3112b1ef4fee9cab6839387faca27965f3b5d') {throw 'Wrong prior installer'}
if ((Get-FileHash $New).Hash.ToLowerInvariant() -ne 'e80c6ad4d2c47f244e71ab90954b5f40951db01de2c9da245b740d65954410f1') {throw 'Wrong optimized installer'}
$root=(Resolve-Path "$PSScriptRoot/../..").Path
Set-Location $root
New-Item -ItemType Directory -Force $Evidence|Out-Null
$evidence=(Resolve-Path $Evidence).Path
$python=(Get-Command python).Source
$env:PYTHONPATH=Join-Path $root 'packaging'
$env:LYRICFORGE_DATA=Join-Path $env:RUNNER_TEMP ('CleanupWorkspace-'+[Guid]::NewGuid().ToString('N'))
$env:HF_HOME=Join-Path $env:RUNNER_TEMP ('CleanupModels-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force $env:LYRICFORGE_DATA,$env:HF_HOME|Out-Null
function Run-Checked([string]$Exe,[string[]]$LaunchArguments,[int]$Timeout=300000) {
  $info=[System.Diagnostics.ProcessStartInfo]::new();$info.FileName=$Exe;$info.WorkingDirectory=Split-Path $Exe;$info.UseShellExecute=$false
  foreach ($a in $LaunchArguments) {$info.ArgumentList.Add($a)}
  $p=[System.Diagnostics.Process]::Start($info)
  if (-not $p.WaitForExit($Timeout)) { & taskkill.exe /PID $p.Id /T /F|Out-Host;throw "Timed out: $Exe" }
  if ($p.ExitCode -ne 0) { throw "$Exe returned $($p.ExitCode)" }
}
function Install([string]$Setup,[string]$Target,[string]$Label) {
  Run-Checked $Setup @('/SP-','/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/DIR=$Target","/LOG=$evidence/$Label.log",'/TASKS=')
}
function Uninstall([string]$Target) {
  Run-Checked (Join-Path $Target 'unins000.exe') @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART')
}
function Smoke([string]$Target) {
  foreach ($arg in @('--self-test','--ai-self-test','--native-self-test')) {Run-Checked (Join-Path $Target 'SkellyMotion.exe') @($arg)}
}
$seed=Join-Path $env:RUNNER_TEMP ('VerifiedSeed-'+[Guid]::NewGuid().ToString('N'))
Install $New $seed 'verified-seed'
& $python "$PSScriptRoot/repack_verified.py" copy $seed $NewLedger "$root/dist/SkellyMotion"
if ($LASTEXITCODE -ne 0) {throw 'Exact runtime copy failed'}
Uninstall $seed
& $python "$PSScriptRoot/generate_cleanup_installer.py" "$root/packaging/SkellyMotion.iss" $OldLedger $NewLedger "$root/packaging/SkellyMotion-CleanupCandidate.iss"
if ($LASTEXITCODE -ne 0) {throw 'Cleanup allowlist generation failed'}
$compiler=Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
if (-not (Test-Path $compiler)) {
  choco install innosetup --yes --no-progress
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path $compiler)) {throw 'Inno Setup unavailable'}
}
& $compiler "$root/packaging/SkellyMotion-CleanupCandidate.iss"
if ($LASTEXITCODE -ne 0) {throw 'Cleanup installer compile failed'}
$setup=(Resolve-Path 'dist/installer/SkellyMotion-Setup.exe').Path
$size=(Get-Item $setup).Length
if ($size -gt 70509261) {throw 'Installer exceeded half-size target'}
$record=[ordered]@{installer_bytes=$size;installer_sha256=(Get-FileHash $setup).Hash.ToLowerInvariant();target_bytes=70509261;source_installer_sha256=(Get-FileHash $New).Hash.ToLowerInvariant();passed=$false}
$record|ConvertTo-Json|Set-Content (Join-Path $evidence 'installer-size.json')
$clean=Join-Path $env:RUNNER_TEMP ('CleanInstall-'+[Guid]::NewGuid().ToString('N'))
Install $setup $clean 'clean-install'
& $python -c "import json,sys;from pathlib import Path;from payload_integrity import compare,manifest;compare(json.loads(Path(sys.argv[2]).read_text(encoding='utf-8-sig')),manifest(Path(sys.argv[1])))" $clean $NewLedger
if ($LASTEXITCODE -ne 0) {throw 'Clean install bytes changed'}
Smoke $clean
Uninstall $clean
$target=Join-Path $env:RUNNER_TEMP ('ActualUpgrade-'+[Guid]::NewGuid().ToString('N'))
Install $Old $target 'legacy-install'
Smoke $target
$changed='_internal/av-18.1.1.dist-info/INSTALLER'
$user='_internal/av.libs/user-note.keep'
Set-Content -LiteralPath (Join-Path $target $changed) -Value 'Locally modified legacy file'
Set-Content -LiteralPath (Join-Path $target $user) -Value 'Unrelated user-owned file'
function File-Ledger([string]$name,[string]$out) {
  $file=Join-Path $target $name
  $m=@{};$m[$name]=@((Get-Item $file).Length,(Get-FileHash $file).Hash.ToLowerInvariant())
  $m|ConvertTo-Json -Depth 4|Set-Content $out
}
$changedLedger=Join-Path $evidence 'changed-legacy.json';$userLedger=Join-Path $evidence 'user-note.json'
File-Ledger $changed $changedLedger;File-Ledger $user $userLedger
$sentinels=@{}
foreach ($file in @("$env:LYRICFORGE_DATA/project.json","$env:HF_HOME/model.keep")) {
  Set-Content -LiteralPath $file -Value 'Existing workspace or model'
  $sentinels[$file]=(Get-FileHash $file).Hash
}
function Preserve {
  foreach ($file in $sentinels.Keys) {
    if (-not (Test-Path $file) -or (Get-FileHash $file).Hash -ne $sentinels[$file]) {throw 'Workspace/model lost'}
  }
}
foreach ($label in @('actual-upgrade','repeat-upgrade')) {
  Install $setup $target $label
  & $python "$PSScriptRoot/repack_verified.py" upgrade $target $OldLedger $NewLedger (Join-Path $evidence "$label.json") $changedLedger $userLedger
  if ($LASTEXITCODE -ne 0) {throw 'Integrated cleanup verification failed'}
  Preserve
  Smoke $target
}
& "$root/packaging/direct-media/capture_stable_welcome.ps1" (Join-Path $target 'SkellyMotion.exe') (Join-Path $evidence 'SkellyMotion-Installed-WebView2.png')
Uninstall $target
Preserve
if ((Test-Path (Join-Path $target 'SkellyMotion.exe')) -or -not (Test-Path (Join-Path $target $user))) {throw 'Uninstall safety failed'}
$record.passed=$true;$record.exact_runtime_bytes=$true;$record.actual_upgrade=$true;$record.repeat_upgrade=$true;$record.workspace_preserved=$true;$record.native_ui=$true
$record|ConvertTo-Json|Set-Content (Join-Path $evidence 'installer-size.json')
$record|ConvertTo-Json|Write-Host
