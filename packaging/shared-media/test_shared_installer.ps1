param(
    [Parameter(Mandatory=$true)][string]$Fixtures,
    [Parameter(Mandatory=$true)][string]$Model,
    [Parameter(Mandatory=$true)][string]$Reference,
    [string]$EvidenceDirectory='shared-candidate/evidence'
)
$ErrorActionPreference='Stop'
$root=(Resolve-Path "$PSScriptRoot/../..").Path
Set-Location $root
$fixtures=(Resolve-Path $Fixtures).Path
$model=(Resolve-Path $Model).Path
$reference=(Resolve-Path $Reference).Path
New-Item -ItemType Directory -Force $EvidenceDirectory | Out-Null
$evidence=(Resolve-Path $EvidenceDirectory).Path
$bundle=(Resolve-Path 'dist/SkellyMotion').Path
$env:PYTHONPATH=Join-Path $root 'packaging'
$ledger=Join-Path $evidence 'shared-payload-manifest.json'
python -c "import json,sys;from pathlib import Path;from payload_integrity import manifest;Path(sys.argv[2]).write_text(json.dumps(manifest(Path(sys.argv[1])),indent=2),encoding='utf-8')" $bundle $ledger
if ($LASTEXITCODE -ne 0) { throw 'Manifest failed' }
$compiler=Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
if (-not (Test-Path -LiteralPath $compiler)) {
    choco install innosetup --yes --no-progress
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $compiler)) { throw 'Inno Setup unavailable' }
}
& $compiler "$root/packaging/SkellyMotion.iss"
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed' }
$setup=(Resolve-Path 'dist/installer/SkellyMotion-Setup.exe').Path
$bytes=(Get-Item $setup).Length
$record=[ordered]@{installer_bytes=$bytes;installer_sha256=(Get-FileHash $setup -Algorithm SHA256).Hash.ToLowerInvariant();
 original_zip_bytes=141018522;prior_verified_installer_bytes=84779843;target_bytes=70509261;
 reduction_percent=[Math]::Round(100*(1-$bytes/141018522),2);
 half_size_target_met=($bytes -le 70509261);verified_installation=$false}
$record | ConvertTo-Json | Set-Content (Join-Path $evidence 'shared-installer-size.json') -Encoding utf8
$record | ConvertTo-Json | Write-Host
# Size is recorded even if a later gate fails. No experimental installer
# reaches the stable artifact unless every gate and the exact target pass.
function Run-Checked([string]$Exe,[string[]]$LaunchArguments,[int]$TimeoutMs) {
    $info=[System.Diagnostics.ProcessStartInfo]::new()
    $info.FileName=$Exe; $info.WorkingDirectory=Split-Path $Exe; $info.UseShellExecute=$false
    foreach ($arg in $LaunchArguments) { $info.ArgumentList.Add($arg) }
    $p=[System.Diagnostics.Process]::Start($info)
    if (-not $p.WaitForExit($TimeoutMs)) {
        & taskkill.exe /PID $p.Id /T /F | Out-Host
        throw "Timed out: $Exe"
    }
    if ($p.ExitCode -ne 0) { throw "$Exe exited $($p.ExitCode)" }
}
$target=Join-Path $env:RUNNER_TEMP ('SkellyMotion-Shared-'+[Guid]::NewGuid().ToString('N'))
$env:LYRICFORGE_DATA=Join-Path $env:RUNNER_TEMP ('SkellyMotion-SharedWorkspace-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force $env:LYRICFORGE_DATA | Out-Null
$sentinel=Join-Path $env:LYRICFORGE_DATA 'preserve.txt'
Set-Content $sentinel 'preserve existing project'
$before=(Get-FileHash $sentinel).Hash
$log=Join-Path $evidence 'install.log'
# Exclude vendor paths during actual installed smoke: the package must be
# self-contained, with no MSYS2/FFmpeg/Python source DLL directory fallback.
$previousPath=$env:PATH
$env:PATH="$env:SystemRoot\System32;$env:SystemRoot"
Remove-Item Env:SKELLY_CI_SHARED_DLL_DIR -ErrorAction SilentlyContinue
try {
    Run-Checked $setup @('/SP-','/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',"/DIR=$target","/LOG=$log",'/TASKS=') 300000
    if (-not (Test-Path $log)) { throw 'Missing setup log' }
    $exe=Join-Path $target 'SkellyMotion.exe'
    foreach ($arg in @('--self-test','--ai-self-test','--native-self-test')) { Run-Checked $exe @($arg) 120000 }
    Run-Checked $exe @('--shared-media-proof','snapshot',$fixtures,$model,(Join-Path $evidence 'installed-ai-proof.json'),'--dll-root',(Join-Path $target '_internal')) 900000
    & "$root/packaging/capture-rendered-ui.ps1" $exe (Join-Path $evidence 'SkellyMotion-Installed-WebView2.png')
    Run-Checked (Join-Path $target 'unins000.exe') @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') 120000
    if ((Test-Path $exe) -or -not (Test-Path $sentinel) -or (Get-FileHash $sentinel).Hash -ne $before) { throw 'Uninstall or workspace safety failed' }
} finally {
    $env:PATH=$previousPath
    if (Test-Path $log) { Get-Content $log -Tail 25 }
}
python "$root/packaging/shared-media/shared_media_proof.py" compare $reference (Join-Path $evidence 'installed-ai-proof.json') (Join-Path $evidence 'installed-ai-parity.json')
if ($LASTEXITCODE -ne 0) { throw 'Frozen inference parity failed' }
$record.verified_installation=$true
$record.painted_native_ui=$true
$record.workspace_preserved=$true
$record.installed_inference_parity=$true
$record | ConvertTo-Json | Set-Content (Join-Path $evidence 'shared-installer-size.json') -Encoding utf8
$record | ConvertTo-Json | Write-Host
if (-not $record.half_size_target_met) { throw 'Verified candidate exceeds the exact half-size target; do not publish' }
