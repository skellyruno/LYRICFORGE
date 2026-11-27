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
    # A shown HWND is not proof that WebView2 has painted. Retry screen captures
    # while the real DOM/resize smoke is running. Require actual app content.
    $painted = $false
    for ($attempt=0; $attempt -lt 120; $attempt++) {
      if ($p.HasExited) { break }
      $rect = New-Object InstalledMotionWindow+RECT
      if (-not [InstalledMotionWindow]::GetWindowRect($handle, [ref]$rect)) { throw 'Cannot read installed window bounds' }
      $w = $rect.Right-$rect.Left; $h = $rect.Bottom-$rect.Top
      if ($w -lt 400 -or $h -lt 300 -or $w -gt 3840 -or $h -gt 2160) { throw 'Invalid installed window dimensions' }
      $bmp = [System.Drawing.Bitmap]::new($w,$h)
      $g = [System.Drawing.Graphics]::FromImage($bmp)
      try {
        $g.CopyFromScreen($rect.Left,$rect.Top,0,0,$bmp.Size)
        $green=0; $light=0
        for ($y=80; $y -lt ($h-24); $y+=5) {
          for ($x=20; $x -lt ($w-20); $x+=5) {
            $c=$bmp.GetPixel($x,$y)
            if ($c.G -gt 100 -and $c.G -gt ($c.R+55) -and $c.G -gt ($c.B+55)) { $green++ }
            if ($c.R -gt 140 -and $c.G -gt 140 -and $c.B -gt 140) { $light++ }
          }
        }
        if ($green -gt 15 -and $light -gt 35) {
          $bmp.Save($Output,[System.Drawing.Imaging.ImageFormat]::Png)
          $painted=$true
          break
        }
      } finally { $g.Dispose(); $bmp.Dispose() }
      Start-Sleep -Milliseconds 250
    }
    if (-not $painted) { throw 'No painted Skelly welcome captured during real native smoke' }
    $rect = New-Object InstalledMotionWindow+RECT
    if (-not [InstalledMotionWindow]::GetWindowRect($handle, [ref]$rect)) { throw 'Cannot read installed window bounds' }
    $w = $rect.Right-$rect.Left; $h = $rect.Bottom-$rect.Top
    $area = [System.Windows.Forms.Screen]::FromHandle($handle).WorkingArea
    if ($w -lt 400 -or $h -lt 300 -or $w -gt 3840 -or $h -gt 2160) { throw 'Invalid installed window dimensions' }
    if ($rect.Left -lt $area.Left -or $rect.Top -lt $area.Top -or $rect.Right -gt $area.Right -or $rect.Bottom -gt $area.Bottom) { throw 'Installed window outside desktop work area' }
    if (-not $p.WaitForExit(110000)) { throw 'Installed native responsiveness timed out' }
    if ($p.ExitCode -ne 0) { throw "Installed native responsiveness failed: $($p.ExitCode)" }
    Write-Host "Installed native UI passed: $w x $h"
} finally {
    if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
}
