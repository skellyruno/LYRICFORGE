# Build and verify the same onedir payload that passed the package smoke tests.
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
    Run-Checked $exe '--self-test' 120000
    Run-Checked $exe '--native-self-test' 120000
    Run-Checked (Join-Path $target 'unins000.exe') '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART' 120000
    if (Test-Path -LiteralPath $exe) { throw 'Uninstall left the installed application executable' }
    Write-Host 'Single installer: silent install, bundled startup, native imports and uninstall passed.'
    Get-FileHash -Algorithm SHA256 -LiteralPath $setup | Format-List
} finally {
    if (Test-Path $log) { Get-Content $log -Tail 30 }
}
