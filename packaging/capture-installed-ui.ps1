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
    Start-Sleep -Seconds 3
    $rect = New-Object InstalledMotionWindow+RECT
    if (-not [InstalledMotionWindow]::GetWindowRect($handle, [ref]$rect)) { throw 'Cannot read installed window bounds' }
    $w = $rect.Right-$rect.Left; $h = $rect.Bottom-$rect.Top
    $area = [System.Windows.Forms.Screen]::FromHandle($handle).WorkingArea
    if ($w -lt 400 -or $h -lt 300 -or $w -gt 3840 -or $h -gt 2160) { throw 'Invalid installed window dimensions' }
    $bmp = [System.Drawing.Bitmap]::new($w,$h)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    try {
        $g.CopyFromScreen($rect.Left,$rect.Top,0,0,$bmp.Size)
        $bmp.Save($Output,[System.Drawing.Imaging.ImageFormat]::Png)
    } finally { $g.Dispose(); $bmp.Dispose() }
    if ($rect.Left -lt $area.Left -or $rect.Top -lt $area.Top -or $rect.Right -gt $area.Right -or $rect.Bottom -gt $area.Bottom) { throw 'Installed window outside desktop work area' }
    if (-not $p.WaitForExit(110000)) { throw 'Installed native responsiveness timed out' }
    if ($p.ExitCode -ne 0) { throw "Installed native responsiveness failed: $($p.ExitCode)" }
    Write-Host "Installed native UI passed: $w x $h"
} finally {
    if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
}
