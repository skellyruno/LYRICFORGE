param([Parameter(Mandatory=$true)][string]$Exe, [Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class InstalledMotionWindow {
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr handle, out RECT rect);
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr handle);
}
'@
$p = Start-Process -FilePath $Exe -ArgumentList '--window-self-test' -WorkingDirectory (Split-Path $Exe) -PassThru
try {
    $handle = [IntPtr]::Zero
    for ($i=0; $i -lt 60; $i++) {
        $p.Refresh()
        if ($p.HasExited) { throw 'Installed editor closed before native capture' }
        $handle = $p.MainWindowHandle
        if ($handle -ne [IntPtr]::Zero) { break }
        Start-Sleep -Seconds 1
    }
    if ($handle -eq [IntPtr]::Zero) { throw 'No installed native window' }
    [InstalledMotionWindow]::SetForegroundWindow($handle) | Out-Null
    # Native handles exist before WebView2 has painted its first document.
    # The CI caller clears only its own previous test log before launch.
    $log = Join-Path $env:LOCALAPPDATA 'LyricForge/logs/desktop.log'
    $ready = $false
    for ($i=0; $i -lt 160; $i++) {
        $p.Refresh()
        if ($p.HasExited) { throw 'Installed editor closed before its document loaded' }
        if ((Test-Path $log) -and ((Get-Content -LiteralPath $log -Raw -ErrorAction SilentlyContinue) -match 'editor document loaded')) {
            $ready = $true
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if (-not $ready) { throw 'WebView2 document never loaded for visual capture' }
    Start-Sleep -Milliseconds 1200
    $rect = New-Object InstalledMotionWindow+RECT
    if (-not [InstalledMotionWindow]::GetWindowRect($handle, [ref]$rect)) { throw 'Cannot read installed window bounds' }
    $w = $rect.Right-$rect.Left; $h = $rect.Bottom-$rect.Top
    $area = [System.Windows.Forms.Screen]::FromHandle($handle).WorkingArea
    if ($w -lt 400 -or $h -lt 300 -or $w -gt 3840 -or $h -gt 2160) { throw 'Invalid installed window dimensions' }
    $painted = $false
    for ($attempt=0; $attempt -lt 12; $attempt++) {
        $p.Refresh()
        if ($p.HasExited) { break }
        [InstalledMotionWindow]::SetForegroundWindow($handle) | Out-Null
        $bmp = [System.Drawing.Bitmap]::new($w,$h)
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        try {
            $g.CopyFromScreen($rect.Left,$rect.Top,0,0,$bmp.Size)
            # Exclude title bar and borders. A uniform near-black content
            # rectangle is not proof of a working visible editor.
            $colors = [System.Collections.Generic.HashSet[int]]::new()
            $visible = 0; $samples = 0
            for ($y=[int]($h*.12); $y -lt [int]($h*.90); $y+=8) {
                for ($x=[int]($w*.05); $x -lt [int]($w*.95); $x+=8) {
                    $c=$bmp.GetPixel($x,$y)
                    $key=([int]($c.R -shr 4) -shl 8) -bor ([int]($c.G -shr 4) -shl 4) -bor [int]($c.B -shr 4)
                    [void]$colors.Add($key)
                    if ([Math]::Max($c.R,[Math]::Max($c.G,$c.B)) -ge 48) { $visible++ }
                    $samples++
                }
            }
            $bmp.Save($Output,[System.Drawing.Imaging.ImageFormat]::Png)
            $painted=($colors.Count -ge 12 -and $samples -gt 0 -and ($visible/$samples) -ge .008)
            Write-Host "Native screenshot content: $($colors.Count) quantized colors; $visible/$samples bright samples"
        } finally { $g.Dispose(); $bmp.Dispose() }
        if ($painted) { break }
        Start-Sleep -Milliseconds 350
    }
    if (-not $painted) { throw 'Native screenshot is blank or insufficiently painted; visual verification failed' }
    if ($rect.Left -lt $area.Left -or $rect.Top -lt $area.Top -or $rect.Right -gt $area.Right -or $rect.Bottom -gt $area.Bottom) { throw 'Installed window outside desktop work area' }
    if (-not $p.WaitForExit(110000)) { throw 'Installed native responsiveness timed out' }
    if ($p.ExitCode -ne 0) { throw "Installed native responsiveness failed: $($p.ExitCode)" }
    Write-Host "Installed native UI passed: $w x $h"
} finally {
    if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
}
