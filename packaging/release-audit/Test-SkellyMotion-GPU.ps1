param([string]$InstallPath=(Join-Path $env:LOCALAPPDATA 'Programs/SkellyMotion'),[string]$Output=(Join-Path (Get-Location) 'SkellyMotion-GPU-Report.json'))
$ErrorActionPreference='Stop'
$ffmpeg=Join-Path $InstallPath '_internal/tools/ffmpeg.exe'
$ffprobe=Join-Path $InstallPath '_internal/tools/ffprobe.exe'
if (-not (Test-Path $ffmpeg) -or -not (Test-Path $ffprobe)) { throw 'Use an installed half-size SkellyMotion build or specify -InstallPath.' }
if ((Get-FileHash $ffmpeg).Hash.ToLowerInvariant() -ne '861fe956cca8c442eeac82e5971fff0273a166e6410e98269fefbdf6731ae117') { throw 'Not the verified FFmpeg runtime' }
if ((Get-FileHash $ffprobe).Hash.ToLowerInvariant() -ne 'f04d1654ac6c2016b1654c8634cdaf39fd367b919c417b38f4d9a9913900312c') { throw 'Not the verified FFprobe runtime' }
$folder=Join-Path ([IO.Path]::GetTempPath()) ('SkellyGPU-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory $folder|Out-Null
$report=[ordered]@{gpu_adapters=@(Get-CimInstance Win32_VideoController|Select-Object Name,DriverVersion);cases=@();scope='Physical H.264 hardware encode and decoded stream validation; not CUDA inference'}
try {
 foreach ($encoder in @('libx264','h264_nvenc','h264_qsv','h264_amf')) {
  $file=Join-Path $folder "$encoder.mp4";$log=Join-Path $folder "$encoder.log"
  $sw=[Diagnostics.Stopwatch]::StartNew()
  $info=[Diagnostics.ProcessStartInfo]::new();$info.FileName=$ffmpeg;$info.UseShellExecute=$false;$info.CreateNoWindow=$true;$info.RedirectStandardError=$true
  $launch=@('-hide_banner','-nostdin','-v','error','-y','-f','lavfi','-i','testsrc2=size=1280x720:rate=30:duration=2','-an','-c:v',$encoder,'-pix_fmt','yuv420p',$file)
  if ($launch | Where-Object { $_ -match '"' }) {throw 'Unexpected quote in argument'}
  $info.Arguments=($launch|ForEach-Object {'"'+$_+'"'}) -join ' '
  $p=[Diagnostics.Process]::Start($info);$read=$p.StandardError.ReadToEndAsync()
  if (-not $p.WaitForExit(90000)) {$p.Kill();$p.WaitForExit();$status='timeout'} else {$status=if ($p.ExitCode -eq 0) {'encoded'} else {'failed_or_unsupported'}}
  $sw.Stop();$stderr=$read.GetAwaiter().GetResult()
  $row=[ordered]@{encoder=$encoder;seconds=$sw.Elapsed.TotalSeconds;status=$status;frames=0;valid=$false;diagnostic=$stderr}
  if ($status -eq 'encoded') {
   $probe=& $ffprobe -v error -count_frames -select_streams v:0 -show_entries stream=codec_name,width,height,nb_read_frames -of json $file
   if ($LASTEXITCODE -eq 0) {
    $s=($probe|ConvertFrom-Json).streams[0];$row.frames=[int]$s.nb_read_frames
    $row.valid=($s.codec_name -eq 'h264' -and $s.width -eq 1280 -and $s.height -eq 720 -and $row.frames -eq 60)
   }
  }
  $row.diagnostic=$row.diagnostic.Replace($folder,'[test-folder]')
  $report.cases+=@($row)
 }
} finally { Remove-Item -LiteralPath $folder -Recurse -Force }
$report|ConvertTo-Json -Depth 6|Set-Content -LiteralPath $Output -Encoding utf8
$report.cases|Format-Table encoder,status,frames,valid,seconds
Write-Host "Local report saved: $Output (no upload)"
