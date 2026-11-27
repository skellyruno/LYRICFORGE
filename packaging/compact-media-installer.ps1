param([string]$ExistingSetup='', [string]$Candidate='', [string]$EvidenceDirectory='compact-media-evidence')
$ErrorActionPreference='Stop'
New-Item -ItemType Directory -Force $EvidenceDirectory | Out-Null
$evidence=(Resolve-Path $EvidenceDirectory).Path
$ledger=Join-Path $evidence 'payload-manifest.json'
$root=(Resolve-Path "$PSScriptRoot/..").Path
function Run-Checked([string]$Exe,[string]$Args,[int]$TimeoutMs) {
    $p=Start-Process -FilePath $Exe -ArgumentList $Args -WorkingDirectory (Split-Path $Exe) -PassThru
    if (-not $p.WaitForExit($TimeoutMs)) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue; throw "Timed out: $Exe" }
    if ($p.ExitCode -ne 0) { throw "$Exe exited $($p.ExitCode)" }
}
if ($ExistingSetup) {
    $setup=(Resolve-Path $ExistingSetup).Path
    if ((Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'f5137dede3c9fc71860dffa444768f90e05327eb931f941be0480b131cd207ed') { throw 'Wrong existing setup' }
    python "$PSScriptRoot/payload_integrity.py" baseline "$root/dist/SkellyMotion" $ledger
    if ($LASTEXITCODE -ne 0) { throw 'Baseline identity failed' }
} else {
    if (-not $Candidate) { throw 'Missing candidate FFmpeg' }
    python "$PSScriptRoot/compact_ffmpeg_payload.py" stage "$root/dist/SkellyMotion" $ledger --candidate $Candidate
    if ($LASTEXITCODE -ne 0) { throw 'Replacement identity failed' }
    $compiler=Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
    if (-not (Test-Path -LiteralPath $compiler)) {
        choco install innosetup --yes --no-progress
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $compiler)) { throw 'Installer compiler unavailable' }
    }
    & $compiler "$PSScriptRoot/SkellyMotion.iss"
    if ($LASTEXITCODE -ne 0) { throw 'Installer compiler failed' }
    $setup=(Resolve-Path "$root/dist/installer/SkellyMotion-Setup.exe").Path
}
$target=Join-Path $env:RUNNER_TEMP ('SkellyMotion-CompactMedia-'+[Guid]::NewGuid().ToString('N'))
$env:LYRICFORGE_DATA=Join-Path $env:RUNNER_TEMP ('SkellyMotion-CompactData-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force $env:LYRICFORGE_DATA | Out-Null
$sentinel=Join-Path $env:LYRICFORGE_DATA 'preserve.txt'
Set-Content -LiteralPath $sentinel -Value 'preserve existing workspace'
$sentinelHash=(Get-FileHash $sentinel -Algorithm SHA256).Hash
$log=Join-Path $evidence 'install.log'
$installArgs='/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="'+$target+'" /LOG="'+$log+'" /TASKS=""'
try {
    Run-Checked $setup $installArgs 300000
    if ($ExistingSetup) { python "$PSScriptRoot/payload_integrity.py" installed $target $ledger }
    else { python "$PSScriptRoot/compact_ffmpeg_payload.py" installed $target $ledger }
    if ($LASTEXITCODE -ne 0) { throw 'Installed file identity failed' }
    $exe=Join-Path $target 'SkellyMotion.exe'
    foreach ($arg in @('--self-test','--ai-self-test','--native-self-test')) { Run-Checked $exe $arg 120000 }
    & "$PSScriptRoot/capture-rendered-ui.ps1" $exe (Join-Path $evidence 'SkellyMotion-Installed-WebView2.png')
    Run-Checked (Join-Path $target 'unins000.exe') '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART' 120000
    if ((Test-Path $exe) -or -not (Test-Path $sentinel) -or (Get-FileHash $sentinel -Algorithm SHA256).Hash -ne $sentinelHash) { throw 'Uninstall safety check failed' }
    $bytes=(Get-Item $setup).Length
    $result=[ordered]@{installer_bytes=$bytes;installer_sha256=(Get-FileHash $setup -Algorithm SHA256).Hash.ToLowerInvariant();original_zip_bytes=141018522;prior_setup_bytes=98400089;reduction_percent=[Math]::Round(100*(1-$bytes/141018522),2);half_size_target_met=($bytes -le 70509261);identical_installed_payload=$true;painted_native_ui=$true;workspace_preserved=$true}
    $result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidence 'installer-size.json') -Encoding utf8
    $result | ConvertTo-Json | Write-Host
    if (-not $ExistingSetup -and $bytes -ge 98400089) { throw 'Candidate installer not smaller than verified setup' }
} finally {
    if (Test-Path $log) { Get-Content $log -Tail 20 }
}
