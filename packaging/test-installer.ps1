# Build and verify the same onedir payload that passed the package smoke tests.
param([switch]$VerifyCanonicalPayload, [string]$EvidenceDirectory = '')
$ErrorActionPreference = 'Stop'
$command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
$compiler = if ($command) { $command.Source } else { $null }
if (-not $compiler) {
    foreach ($root in @(${env:ProgramFiles(x86)}, $env:ProgramFiles)) {
        if ($root) {
            $candidate = Join-Path $root 'Inno Setup 6\ISCC.exe'
            if (Test-Path -LiteralPath $candidate) { $compiler = $candidate; break }
        }
    }
}
if (-not $compiler) { throw 'Inno Setup 6 compiler is required (install from the official Inno Setup project).' }
if ($VerifyCanonicalPayload) {
    if (-not $EvidenceDirectory) { throw 'Canonical verification requires an evidence directory' }
    New-Item -ItemType Directory -Force $EvidenceDirectory | Out-Null
    $EvidenceDirectory = (Resolve-Path $EvidenceDirectory).Path
    $ledger = Join-Path $EvidenceDirectory 'payload-manifest.json'
    python (Join-Path $PSScriptRoot 'payload_integrity.py') baseline (Join-Path $PSScriptRoot '../dist/SkellyMotion') $ledger
    if ($LASTEXITCODE -ne 0) { throw 'Canonical payload verification failed' }
}
& $compiler (Join-Path $PSScriptRoot 'SkellyMotion.iss')
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compiler failed: $LASTEXITCODE" }
$setup = (Resolve-Path "$PSScriptRoot/../dist/installer/SkellyMotion-Setup.exe").Path
$target = Join-Path $env:RUNNER_TEMP ('SkellyMotion-InstallSmoke-' + [Guid]::NewGuid().ToString('N'))
$log = Join-Path $env:RUNNER_TEMP 'SkellyMotion-Setup-Smoke.log'
function Run-Checked([string]$Path, [string]$Arguments, [int]$TimeoutMs) {
    $p = Start-Process -FilePath $Path -ArgumentList $Arguments -WorkingDirectory (Split-Path $Path) -PassThru
    if (-not $p.WaitForExit($TimeoutMs)) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue; throw "Timed out: $Path" }
    if ($p.ExitCode -ne 0) { throw "$Path failed: $($p.ExitCode)" }
}
try {
    Run-Checked $setup "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=`"$target`" /LOG=`"$log`" /TASKS=`"`"" 300000
    $exe = Join-Path $target 'SkellyMotion.exe'
    foreach ($file in @('SkellyMotion.exe', '_internal/pythonnet/runtime/Python.Runtime.dll', '_internal/webview/lib/Microsoft.Web.WebView2.Core.dll')) {
        if (-not (Test-Path -LiteralPath (Join-Path $target $file))) { throw "Installed payload missing $file" }
    }
    if ($VerifyCanonicalPayload) {
        python (Join-Path $PSScriptRoot 'payload_integrity.py') installed $target $ledger
        if ($LASTEXITCODE -ne 0) { throw 'Installed payload verification failed' }
        # Isolate the smoke-test workspace from any existing profile. The
        # sentinel verifies uninstall does not remove unrelated user files.
        $env:LYRICFORGE_DATA = Join-Path $env:RUNNER_TEMP ('SkellyMotion-DataSmoke-' + [Guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force $env:LYRICFORGE_DATA | Out-Null
        $sentinel = Join-Path $env:LYRICFORGE_DATA 'preserve-user-data.txt'
        Set-Content -LiteralPath $sentinel -Value 'preserve-existing-workspace'
        $sentinelHash = (Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash
    }
    Run-Checked $exe '--self-test' 120000
    Run-Checked $exe '--ai-self-test' 120000
    Run-Checked $exe '--native-self-test' 120000
    if ($VerifyCanonicalPayload) {
        & (Join-Path $PSScriptRoot 'capture-installed-ui.ps1') $exe (Join-Path $EvidenceDirectory 'SkellyMotion-Installed-WebView2.png')
        if ($LASTEXITCODE -ne 0) { throw 'Installed native UI check failed' }
    }
    Run-Checked (Join-Path $target 'unins000.exe') '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART' 120000
    if (Test-Path -LiteralPath $exe) { throw 'Uninstall left the installed application executable' }
    if ($VerifyCanonicalPayload) {
        if (-not (Test-Path -LiteralPath $sentinel) -or (Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash -ne $sentinelHash) { throw 'Uninstall changed the external workspace' }
        $bytes = (Get-Item -LiteralPath $setup).Length
        $original = 141018522
        $result = [ordered]@{
            producer = '13d8311ad66f39418110db4785170f5846e8cce2'
            original_zip_bytes = $original
            installer_bytes = $bytes
            reduction_percent = [Math]::Round(100.0 * (1.0 - $bytes / $original), 2)
            half_size_target_met = ($bytes -le $original / 2)
            installer_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $setup).Hash.ToLowerInvariant()
            installed_payload_identical = $true
            workspace_preserved = $true
            installed_native_ui_passed = $true
        }
        $result | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $EvidenceDirectory 'installer-size.json') -Encoding utf8
        $result | ConvertTo-Json | Write-Host
        if ($bytes -ge $original) { throw 'Installer is not smaller than the original download' }
    }
    Write-Host 'Single installer: silent install, bundled startup, native imports and uninstall passed.'
    Get-FileHash -Algorithm SHA256 -LiteralPath $setup | Format-List
} finally {
    if (Test-Path $log) { Get-Content $log -Tail 30 }
}
