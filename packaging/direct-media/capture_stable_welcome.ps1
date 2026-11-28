# Capture the actual installed app without racing the resize/demo self-test.
param([Parameter(Mandatory=$true)][string]$Exe,[Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class StableMotionWindow {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left,Top,Right,Bottom; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h,out RECT r);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
}
'@
$p=Start-Process -FilePath $Exe -WorkingDirectory (Split-Path $Exe) -PassThru
try {
  $h=[IntPtr]::Zero
  for ($i=0;$i -lt 60;$i++) {
    $p.Refresh()
    if ($p.HasExited) { throw 'Editor exited before capture' }
    $h=$p.MainWindowHandle
    if ($h -ne [IntPtr]::Zero) { break }
    Start-Sleep -Seconds 1
  }
  if ($h -eq [IntPtr]::Zero) { throw 'Missing native editor window' }
  [StableMotionWindow]::SetForegroundWindow($h)|Out-Null
  $lastBounds='';$stable=0;$bestSpan=0;$captured=$false
  for ($attempt=0;$attempt -lt 45;$attempt++) {
    $p.Refresh()
    if ($p.HasExited) { throw 'Editor closed during capture' }
    $r=New-Object StableMotionWindow+RECT
    if (-not [StableMotionWindow]::GetWindowRect($h,[ref]$r)) { throw 'Missing window bounds' }
    $w=$r.Right-$r.Left;$height=$r.Bottom-$r.Top
    $area=[System.Windows.Forms.Screen]::FromHandle($h).WorkingArea
    if ($w -lt 400 -or $height -lt 300 -or $r.Left -lt $area.Left -or $r.Top -lt $area.Top -or $r.Right -gt $area.Right -or $r.Bottom -gt $area.Bottom) { throw 'Window bounds invalid' }
    $bounds="$($r.Left),$($r.Top),$w,$height"
    if ($bounds -eq $lastBounds) { $stable++ } else { $stable=0;$lastBounds=$bounds;$bestSpan=0;$captured=$false }
    $bmp=[System.Drawing.Bitmap]::new($w,$height)
    $g=[System.Drawing.Graphics]::FromImage($bmp)
    try {
      $g.CopyFromScreen($r.Left,$r.Top,0,0,$bmp.Size)
      $light=0;$green=0;$radar=0;$minY=$height;$maxY=0
      for ($y=60;$y -lt $height-15;$y+=4) {
        for ($x=12;$x -lt $w-12;$x+=4) {
          $c=$bmp.GetPixel($x,$y)
          if ($c.R -gt 140 -and $c.G -gt 140 -and $c.B -gt 140) { $light++ }
          if ($c.G -gt 100 -and $c.G -gt ($c.R+55) -and $c.G -gt ($c.B+55)) { $green++ }
          if ($x -gt $w*0.62 -and $x -lt $w*0.93 -and $y -gt $height*0.13 -and $y -lt $height*0.53 -and
              $c.G -gt 40 -and $c.G -gt ($c.R+20) -and $c.G -gt ($c.B+20)) {
            $radar++;$minY=[Math]::Min($minY,$y);$maxY=[Math]::Max($maxY,$y)
          }
        }
      }
      $span=$maxY-$minY
      if ($stable -ge 2 -and $light -gt 35 -and $green -gt 15 -and $radar -gt 15 -and $span -gt $height*0.16 -and $span -gt $bestSpan) {
        $bmp.Save($Output,[System.Drawing.Imaging.ImageFormat]::Png)
        $bestSpan=$span;$captured=$true
      }
    } finally { $g.Dispose();$bmp.Dispose() }
    if ($captured -and $stable -ge 5) { break }
    Start-Sleep -Milliseconds 750
  }
  if (-not $captured) { throw 'No stable painted welcome and complete radar captured' }
  Write-Host "Stable native welcome captured, radar vertical span $bestSpan pixels."
} finally {
  if (-not $p.HasExited) {
    $p.CloseMainWindow()|Out-Null
    if (-not $p.WaitForExit(15000)) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
  }
}
# Run the real responsiveness/resize/demo check separately, with its own exit.
$p=Start-Process -FilePath $Exe -ArgumentList '--window-self-test' -WorkingDirectory (Split-Path $Exe) -PassThru
if (-not $p.WaitForExit(110000)) { Stop-Process -Id $p.Id -Force;throw 'Native responsiveness timed out' }
if ($p.ExitCode -ne 0) { throw "Native responsiveness failed: $($p.ExitCode)" }
