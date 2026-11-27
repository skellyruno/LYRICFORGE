param([Parameter(Mandatory=$true)][string]$Vendor)
$ErrorActionPreference='Stop'
$vendor=(Resolve-Path $Vendor).Path
$root=(Resolve-Path "$PSScriptRoot/../..").Path
Set-Location $root
python studio_icon.py
if ($LASTEXITCODE -ne 0) { throw 'Original icon guard failed' }
$flags=@('--noconfirm','--clean','--onedir','--windowed','--name','SkellyMotion',
    '--paths',$root,'--paths',(Join-Path $root 'packaging/shared-media'),
    '--icon','static/skull.ico','--add-data','static;static',
    '--add-data','studio_ai_worker.py;.', '--add-data','studio_kokoro_worker.py;.',
    '--add-binary',"$vendor/bin/ffmpeg.exe;tools",
    '--hidden-import','clr','--hidden-import','webview','--collect-all','webview',
    '--collect-all','pythonnet','--collect-all','clr_loader',
    '--hidden-import','faster_whisper','--collect-all','faster_whisper',
    '--collect-all','ctranslate2','--collect-all','tokenizers','--collect-all','av')
foreach ($module in @('onnxruntime','tkinter','_tkinter','turtle','idlelib','lib2to3','pydoc_data','PIL.ImageTk','PIL._imagingtk','PIL._avif','PIL._webp','PIL._imagingcms','watchfiles','websockets','httptools')) {
    $flags+=@('--exclude-module',$module)
}
foreach ($file in Get-ChildItem "$vendor/bin" -Filter '*.dll' -File) { $flags+=@('--add-binary',"$($file.FullName);.") }
$flags+='packaging/shared-media/desktop_entry.py'
& python -m PyInstaller @flags
if ($LASTEXITCODE -ne 0) { throw 'Shared runtime frozen build failed' }
$bundle=(Resolve-Path 'dist/SkellyMotion').Path
foreach ($helper in @('Repair-SkellyMotion.cmd','SkellyMotion-SafeMode.cmd','SkellyMotion-BrowserMode.cmd')) { Copy-Item $helper $bundle }
# Fail if PyInstaller silently duplicates native libraries or imports the old
# binary wheel. Do not delete any file from the newly frozen candidate.
foreach ($file in Get-ChildItem "$vendor/bin" -Filter '*.dll' -File) {
    $copies=@(Get-ChildItem "$bundle/_internal" -Recurse -File -Filter $file.Name)
    if ($copies.Count -ne 1 -or $copies[0].DirectoryName -ne (Join-Path $bundle '_internal') -or
        (Get-FileHash $copies[0].FullName).Hash -ne (Get-FileHash $file.FullName).Hash) {
        throw "Duplicate or wrong native library: $($file.Name)"
    }
}
if (Test-Path "$bundle/_internal/av.libs") { throw 'Unexpected old private FFmpeg stack' }
if (Test-Path "$bundle/_internal/tools/ffprobe.exe") { throw 'Redundant probe tool included' }
$models=@(Get-ChildItem $bundle -Recurse -File | Where-Object {$_.Name -in @('model.bin','pytorch_model.bin','model.safetensors') -or $_.Extension -in @('.gguf','.ggml','.safetensors')})
if ($models.Count) { throw 'Do not bundle model weights' }
Write-Host "Single native media stack, $((Get-ChildItem $bundle -Recurse -File | Measure-Object Length -Sum).Sum) unpacked bytes."
