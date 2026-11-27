"""Stage an explicit decoder candidate, leaving the verified root intact."""
import argparse,hashlib,importlib.util,io,shutil,subprocess,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent

def stage(root,dest):
    root,dest=Path(root).resolve(),Path(dest).resolve()
    if dest.exists():raise ValueError("Staging already exists")
    dest.mkdir()
    with zipfile.ZipFile(io.BytesIO(subprocess.check_output(["git","-C",str(root),"archive","--format=zip","HEAD"]))) as z:z.extractall(dest)
    server=dest/"server.py";text=server.read_text(encoding="utf-8")
    if hashlib.sha256(text.encode()).hexdigest()!="9fba12c0e5c8f5928bd4537eb995b8ff9622a3940911ec7e70244b010ec02983":
        raise ValueError("Unexpected original server")
    start=text.index("def media_duration(path: Path) -> float:");end=text.index("async def save_upload(",start)
    replacement='''def media_duration(path: Path) -> float:
    from studio_media_runtime import media_duration as read_duration
    return read_duration(path)


def video_stream_width(path: Path) -> int:
    from studio_media_runtime import video_stream_width as read_width
    return read_width(path)


'''
    server.write_text(text[:start]+replacement+text[end:],encoding="utf-8",newline="\n")
    launcher=dest/"desktop_launcher.py";text=launcher.read_text(encoding="utf-8")
    if hashlib.sha256(text.encode()).hexdigest()!="23609dde2bdc073a0dfa67c20a039043f1f1b6a7eec91bfd2fed32ccc323d7c2":
        raise ValueError("Unexpected original launcher")
    old='    import av\n    assert callable(WhisperModel) and VadOptions is not None\n    assert get_supported_compute_types("cpu")\n    assert av.__version__\n    print("SkellyMotion bundled Whisper/CTranslate2/PyAV import passed", flush=True)'
    new='    from studio_media_runtime import tools, decode_audio\n    assert callable(WhisperModel) and VadOptions is not None\n    assert get_supported_compute_types("cpu")\n    tools()\n    check_subtitle_renderer()\n    assert callable(decode_audio)\n    print("SkellyMotion bundled Whisper/CTranslate2/verified media tools passed", flush=True)'
    if text.count(old)!=1:raise ValueError("AI self-test anchor missing")
    launcher.write_text(text.replace(old,new),encoding="utf-8",newline="\n")
    for name in ("studio_probe_delta.py","studio_media_runtime.py","direct_entry.py"):shutil.copy2(HERE/name,dest/name)
    proof=(root/"packaging/shared-media/shared_media_proof.py").read_text(encoding="utf-8")
    proof=proof.replace("    import av\n","    av = None\n").replace('"av_version":av.__version__,"libraries":{k:list(v) for k,v in av.library_versions.items()},','"av_version":"explicit-native-ffmpeg","libraries":{},')
    if "av.__version__" in proof:raise ValueError("Unpatched reference-only proof")
    (dest/"shared_media_proof.py").write_text(proof,encoding="utf-8",newline="\n")
    # Preserve all original inference logic and the original Mel padding.
    audio=Path(importlib.util.find_spec("faster_whisper").origin).parent/"audio.py"
    original=audio.read_bytes().replace(b"\r\n",b"\n")
    if hashlib.sha256(original).hexdigest()!="60a1d8638f718cbf6d245aed3e5a5aa61c1f822a0b0fe9b48a7c928d47c23909":raise ValueError("Wrong Faster Whisper audio source")
    tail=original.decode().split("def pad_or_trim(",1)[1]
    audio.write_text('"""SkellyMotion candidate native decoder; Mel padding unchanged."""\nimport numpy as np\nfrom studio_media_runtime import decode_audio\n\ndef pad_or_trim('+tail,encoding="utf-8",newline="\n")
    print("Staged explicit media backend; release source unchanged.")

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("root");p.add_argument("dest");a=p.parse_args();stage(a.root,a.dest)
