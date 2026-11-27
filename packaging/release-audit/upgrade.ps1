param([string]$Old,[string]$New,[string]$OldLedger,[string]$NewLedger,[string]$Evidence='upgrade-evidence')
$ErrorActionPreference='Stop'
$Old=(Resolve-Path $Old).Path;$New=(Resolve-Path $New).Path
if ((Get-FileHash $Old).Hash.ToLowerInvariant() -ne '2ca6062fa7aad995dd9b874398b3112b1ef4fee9cab6839387faca27965f3b5d') { throw 'Wrong old installer' }
if ((Get-FileHash $New).Hash.ToLowerInvariant() -ne '6a015a814c14849a306e854fb2b62972c3d122cd8165a9f219ad4b010905ecc4') { throw 'Wrong half-size installer' }
$OldLedger=(Resolve-Path $OldLedger).Path;$NewLedger=(Resolve-Path $NewLedger).Path
New-Item -ItemType Directory -Force $Evidence|Out-Null
$Evidence=(Resolve-Path $Evidence).Path
$root=(Resolve-Path "$PSScriptRoot/../..").Path
$target=Join-Path $env:RUNNER_TEMP ('SkellyUpgrade-'+[Guid]::NewGuid().ToString('N'))
$env:LYRICFORGE_DATA=Join-Path $env:RUNNER_TEMP ('SkellyWorkspace-'+[Guid]::NewGuid().ToString('N'))
$env:HF_HOME=Join-Path $env:RUNNER_TEMP ('SkellyModels-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force $env:LYRICFORGE_DATA,$env:HF_HOME|Out-Null
function Invoke-Checked([string]$Exe,[string[]]$LaunchArguments,[int]$Timeout=300000) {
  $info=[System.Diagnostics.ProcessStartInfo]::new();$info.FileName=$Exe;$info.WorkingDirectory=Split-Path $Exe;$info.UseShellExecute=$false
  foreach ($a in $LaunchArguments) {$info.ArgumentList.Add($a)}
  $p=[System.Diagnostics.Process]::Start($info)
  if (-not $p.WaitForExit($Timeout)) { & taskkill.exe /PID $p.Id /T /F|Out-Host;throw "Timed out: $Exe" }
  if ($p.ExitCode -ne 0) { throw "$Exe returned $($p.ExitCode)" }
}
function Install([string]$Setup,[string]$Label) {
  Invoke-Checked $Setup @('/SP-','/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/DIR=$target","/LOG=$Evidence/$Label.log",'/TASKS=')
}
# Actual old/new installers share AppId. Use isolated runner directories only.
Install $Old 'old-install'
$exe=Join-Path $target 'SkellyMotion.exe'
Invoke-Checked $exe @('--self-test')
Invoke-Checked $exe @('--ai-self-test')
# Seed independent project-like, imported media, cache and model sentinel files.
# These are deliberately synthetic preservation fixtures, not user projects.
$sentinels=@{}
foreach ($path in @("$env:LYRICFORGE_DATA/project/lyrics.json","$env:LYRICFORGE_DATA/project/imported.wav","$env:HF_HOME/cache/model.keep","$target/user-note.keep")) {
  New-Item -ItemType Directory -Force (Split-Path $path)|Out-Null
  [IO.File]::WriteAllText($path,"upgrade-preserve:"+[Guid]::NewGuid())
  $sentinels[$path]=(Get-FileHash $path).Hash
}
function Verify-Preserved {
  foreach ($path in $sentinels.Keys) {
    if (-not (Test-Path -LiteralPath $path) -or (Get-FileHash $path).Hash -ne $sentinels[$path]) { throw "Preservation failed: $path" }
  }
}
$env:PYTHONPATH=Join-Path $root 'packaging'
Install $New 'in-place-upgrade'
Verify-Preserved
python "$PSScriptRoot/verify_upgrade.py" $target $OldLedger $NewLedger (Join-Path $Evidence 'upgrade-payload.json')
if ($LASTEXITCODE -ne 0) { throw 'Upgrade payload comparison failed' }
foreach ($arg in @('--self-test','--ai-self-test','--native-self-test')) {Invoke-Checked $exe @($arg)}
& "$root/packaging/direct-media/capture_stable_welcome.ps1" $exe (Join-Path $Evidence 'Upgrade-Native-UI.png')
# Exercise the local hardware-encoder diagnostic on this exact installed binary.
# Standard hosted runners are not proof of physical GPU acceleration.
& "$root/packaging/release-audit/Test-SkellyMotion-GPU.ps1" -InstallPath $target -Output (Join-Path $Evidence 'runner-gpu-smoke.json')
$gpu=Get-Content (Join-Path $Evidence 'runner-gpu-smoke.json') -Raw | ConvertFrom-Json
if (-not ($gpu.cases | Where-Object { $_.encoder -eq 'libx264' -and $_.valid })) { throw 'CPU control encode failed' }
Install $New 'repeat-install'
Verify-Preserved
python "$PSScriptRoot/verify_upgrade.py" $target $OldLedger $NewLedger (Join-Path $Evidence 'reinstall-payload.json')
if ($LASTEXITCODE -ne 0) { throw 'Repeat install payload comparison failed' }
Invoke-Checked $exe @('--self-test')
# Test conservative cleanup on a real upgrade, never in a user's workspace.
# A changed app-owned metadata file must be preserved, even if obsolete.
$changed=Join-Path $target '_internal/av-18.1.1.dist-info/INSTALLER'
if (-not (Test-Path $changed)) { throw 'Expected old metadata file missing' }
Set-Content -LiteralPath $changed -Value 'modified-by-local-owner'
$changedHash=(Get-FileHash $changed).Hash
python "$PSScriptRoot/cleanup_legacy_media.py" $target $OldLedger $NewLedger (Join-Path $Evidence 'cleanup-dry-run.json')
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $changed)) { throw 'Dry-run failed' }
python "$PSScriptRoot/cleanup_legacy_media.py" $target $OldLedger $NewLedger (Join-Path $Evidence 'cleanup-applied.json') --apply
if ($LASTEXITCODE -ne 0) { throw 'Exact legacy cleanup failed' }
$cleanup=Get-Content (Join-Path $Evidence 'cleanup-applied.json') -Raw | ConvertFrom-Json
if ($cleanup.removed_bytes -lt 70000000 -or (Get-FileHash $changed).Hash -ne $changedHash) { throw 'Cleanup preservation or recovery failed' }
Verify-Preserved
Invoke-Checked $exe @('--self-test')
Invoke-Checked $exe @('--ai-self-test')
Invoke-Checked (Join-Path $target 'unins000.exe') @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART')
Verify-Preserved
if (Test-Path $exe) { throw 'Application still present after uninstall' }
@{passed=$true;old_to_half_size=$true;repeat_install=$true;workspace_and_model_sentinels_preserved=$true;native_ui=$true;uninstall=$true;exact_legacy_cleanup_tested=$true;removed_legacy_bytes=$cleanup.removed_bytes;modified_file_preserved_before_uninstall=$true} | ConvertTo-Json | Set-Content (Join-Path $Evidence 'upgrade-result.json')
