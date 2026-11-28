param([Parameter(Mandatory=$true)][string]$Tools)
$ErrorActionPreference='Stop'
$tools=(Resolve-Path $Tools).Path
python studio_icon.py
if ($LASTEXITCODE -ne 0) { throw 'Original icon guard failed' }
$flags=@('--noconfirm','--clean','--onedir','--windowed','--name','SkellyMotion',
 '--icon','static/skull.ico','--add-data','static;static','--add-data','studio_ai_worker.py;.',
 '--add-data','studio_kokoro_worker.py;.','--add-data','studio_expression_worker.py;.',
 '--add-binary',"$tools/ffmpeg.exe;tools",'--add-data',"$tools/ffprobe.delta;tools",
 '--hidden-import','clr','--hidden-import','webview','--collect-all','webview','--collect-all','pythonnet','--collect-all','clr_loader',
 '--hidden-import','faster_whisper','--collect-all','faster_whisper','--collect-all','ctranslate2','--collect-all','tokenizers',
 '--exclude-module','av')
foreach ($module in @('onnxruntime','tkinter','_tkinter','turtle','idlelib','lib2to3','pydoc_data','PIL.ImageTk','PIL._imagingtk','PIL._avif','PIL._webp','PIL._imagingcms','watchfiles','websockets','httptools')) { $flags+=@('--exclude-module',$module) }
$flags+='direct_entry.py'
& python -m PyInstaller @flags
if ($LASTEXITCODE -ne 0) { throw 'Direct-media frozen build failed' }
$bundle=(Resolve-Path 'dist/SkellyMotion').Path
foreach ($name in @('Repair-SkellyMotion.cmd','SkellyMotion-SafeMode.cmd','SkellyMotion-BrowserMode.cmd')) { Copy-Item $name $bundle }
foreach ($name in @('_internal/av','_internal/av.libs','_internal/tools/ffprobe.exe')) {
 if (Test-Path (Join-Path $bundle $name)) { throw "Unexpected redundant dependency $name" }
}
if (-not (Test-Path "$bundle/_internal/tools/ffprobe.delta")) { throw 'Missing probe delta' }
$models=@(Get-ChildItem $bundle -Recurse -File | Where-Object {$_.Name -in @('model.bin','pytorch_model.bin','model.safetensors') -or $_.Extension -in @('.gguf','.ggml','.safetensors')})
if ($models.Count) { throw 'Model weights must not be bundled' }
