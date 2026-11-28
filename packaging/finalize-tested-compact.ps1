param([string]$ExistingSetup='', [string]$Candidate='', [string]$EvidenceDirectory='compact-media-evidence')
$ErrorActionPreference='Stop'
New-Item -ItemType Directory -Force $EvidenceDirectory | Out-Null
$evidence=(Resolve-Path $EvidenceDirectory).Path
$ledger=Join-Path $evidence 'payload-manifest.json'
$root=(Resolve-Path "$PSScriptRoot/..").Path
function Run-Checked([string]$Exe,[string[]]$LaunchArguments,[int]$TimeoutMs) {
    # $Args is PowerShell's automatic variable, case insensitive. Use a
    # distinct name and .NET ArgumentList to avoid shell quote loss.
    $info=[System.Diagnostics.ProcessStartInfo]::new()
    $info.FileName=$Exe
    $info.WorkingDirectory=Split-Path $Exe
    $info.UseShellExecute=$false
    foreach ($arg in $LaunchArguments) { $info.ArgumentList.Add($arg) }
    if ($info.ArgumentList.Count -ne $LaunchArguments.Count -or $info.ArgumentList.Count -eq 0) { throw 'Launch argument loss' }
    Write-Host ("Starting {0}; arguments: {1}" -f $Exe,($LaunchArguments | ConvertTo-Json -Compress))
    $p=[System.Diagnostics.Process]::Start($info)
    if (-not $p.WaitForExit($TimeoutMs)) {
        Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -eq $p.Id -or $_.ParentProcessId -eq $p.Id } | Select-Object ProcessId,Name,CommandLine | Format-List | Out-String | Write-Host
        & taskkill.exe /PID $p.Id /T /F | Out-Host
        throw "Timed out: $Exe"
    }
    if ($p.ExitCode -ne 0) { throw "$Exe exited $($p.ExitCode)" }
}
if ($ExistingSetup) {
    $setup=(Resolve-Path $ExistingSetup).Path
    if ((Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'f5137dede3c9fc71860dffa444768f90e05327eb931f941be0480b131cd207ed') { throw 'Wrong existing setup' }
    python "$PSScriptRoot/payload_integrity.py" baseline "$root/dist/SkellyMotion" $ledger
    if ($LASTEXITCODE -ne 0) { throw 'Baseline identity failed' }
} else {
    if (-not $Candidate) { throw 'Missing candidate FFmpeg' }
    $Candidate=(Resolve-Path $Candidate).Path
    if ((Get-FileHash $Candidate -Algorithm SHA256).Hash.ToLowerInvariant() -ne '861fe956cca8c442eeac82e5971fff0273a166e6410e98269fefbdf6731ae117') { throw 'Wrong tested compact FFmpeg' }
    python "$PSScriptRoot/compact_ffmpeg_payload.py" stage "$root/dist/SkellyMotion" $ledger --candidate $Candidate
    if ($LASTEXITCODE -ne 0) { throw 'Replacement identity failed' }
    # Restore approved icon in the already-tested executable; its frozen Python archive is unchanged.
    python "$PSScriptRoot/restore_original_icon.py" stage "$root/dist/SkellyMotion" "$root/static/skellyhub.ico" --ledger $ledger --evidence (Join-Path $evidence 'icon-provenance.json')
    if ($LASTEXITCODE -ne 0) { throw 'Original icon restoration failed' }
    # Change only the two stale logo references; reuse the verified original PNG.
    python "$PSScriptRoot/restore_editor_header.py" "$root/dist/SkellyMotion" "$root/static/index.html" $ledger (Join-Path $evidence 'editor-header-provenance.json')
    if ($LASTEXITCODE -ne 0) { throw 'Editor header restoration failed' }
    $compiler=Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
    if (-not (Test-Path -LiteralPath $compiler)) {
        choco install innosetup --yes --no-progress
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $compiler)) { throw 'Installer compiler unavailable' }
    }
    & $compiler "$PSScriptRoot/SkellyMotion.iss"
    if ($LASTEXITCODE -ne 0) { throw 'Installer compiler failed' }
    $setup=(Resolve-Path "$root/dist/installer/SkellyMotion-Setup.exe").Path
    python "$PSScriptRoot/restore_original_icon.py" verify $setup "$root/static/skellyhub.ico"
    if ($LASTEXITCODE -ne 0) { throw 'Installer embedded icon mismatch' }
}
$target=Join-Path $env:RUNNER_TEMP ('SkellyMotion-CompactMedia-'+[Guid]::NewGuid().ToString('N'))
$env:LYRICFORGE_DATA=Join-Path $env:RUNNER_TEMP ('SkellyMotion-CompactData-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force $env:LYRICFORGE_DATA | Out-Null
$sentinel=Join-Path $env:LYRICFORGE_DATA 'preserve.txt'
Set-Content -LiteralPath $sentinel -Value 'preserve existing workspace'
$sentinelHash=(Get-FileHash $sentinel -Algorithm SHA256).Hash
$log=Join-Path $evidence 'install.log'
$installArgs=@('/SP-','/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOCANCEL',"/DIR=$target","/LOG=$log",'/TASKS=')
$compiled=[ordered]@{installer_bytes=(Get-Item $setup).Length;installer_sha256=(Get-FileHash $setup -Algorithm SHA256).Hash.ToLowerInvariant();original_zip_bytes=141018522;verified_installation=$false}
$compiled | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidence 'compiled-size.json') -Encoding utf8
$compiled | ConvertTo-Json | Write-Host
try {
    Run-Checked $setup $installArgs 300000
    if (-not (Test-Path -LiteralPath $log)) { throw 'Setup failed to produce requested install log' }
    if ($ExistingSetup) { python "$PSScriptRoot/payload_integrity.py" installed $target $ledger }
    else { python "$PSScriptRoot/compact_ffmpeg_payload.py" installed $target $ledger }
    if ($LASTEXITCODE -ne 0) { throw 'Installed file identity failed' }
    $exe=Join-Path $target 'SkellyMotion.exe'
    if (-not $ExistingSetup) {
        python "$PSScriptRoot/restore_original_icon.py" verify $exe "$root/static/skellyhub.ico"
        if ($LASTEXITCODE -ne 0) { throw 'Installed original icon mismatch' }
    }
    foreach ($arg in @('--self-test','--ai-self-test','--native-self-test')) { Run-Checked $exe @($arg) 120000 }
    & "$PSScriptRoot/capture-rendered-ui.ps1" $exe (Join-Path $evidence 'SkellyMotion-Installed-WebView2.png')
    Run-Checked (Join-Path $target 'unins000.exe') @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART') 120000
    if ((Test-Path $exe) -or -not (Test-Path $sentinel) -or (Get-FileHash $sentinel -Algorithm SHA256).Hash -ne $sentinelHash) { throw 'Uninstall safety check failed' }
    $bytes=(Get-Item $setup).Length
    $result=[ordered]@{installer_bytes=$bytes;installer_sha256=(Get-FileHash $setup -Algorithm SHA256).Hash.ToLowerInvariant();original_zip_bytes=141018522;prior_setup_bytes=98400089;reduction_percent=[Math]::Round(100*(1-$bytes/141018522),2);half_size_target_met=($bytes -le 70509261);identical_installed_payload=$true;painted_native_ui=$true;workspace_preserved=$true}
    $result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidence 'installer-size.json') -Encoding utf8
    $result | ConvertTo-Json | Write-Host
    if (-not $ExistingSetup -and $bytes -ge 98400089) { throw 'Candidate installer not smaller than verified setup' }
} finally {
    if (Test-Path $log) { Get-Content $log -Tail 20 }
}
