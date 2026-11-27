"""Exercise the real delta, including corrupted/truncated patch rejection."""
import argparse,io,tempfile
from pathlib import Path
from studio_probe_delta import apply_delta,restore_probe,sha,BASE_SHA,PROBE_SHA,PROBE_SIZE

def audit(tools):
    tools=Path(tools).resolve()
    base=(tools/"ffmpeg.exe").read_bytes();delta=(tools/"ffprobe.delta").read_bytes()
    good=io.BytesIO();apply_delta(base,delta,good)
    assert len(good.getbuffer())==PROBE_SIZE
    assert good.getbuffer()==(tools/"ffprobe.exe").read_bytes()
    for bad in (b"",delta[:1],delta[:-1],delta+b"\0"):
        try:apply_delta(base,bad,io.BytesIO())
        except ValueError:pass
        else:raise AssertionError("Malformed delta accepted")
    with tempfile.TemporaryDirectory() as d:
        root=Path(d);(root/"ffmpeg.exe").write_bytes(base);(root/"ffprobe.delta").write_bytes(delta)
        target=restore_probe(root)
        assert sha(target)==PROBE_SHA
        target.write_bytes(b"damaged")
        assert sha(restore_probe(root))==PROBE_SHA
        target.unlink()
        corrupt=bytearray(delta);corrupt[len(corrupt)//2]^=1;(root/"ffprobe.delta").write_bytes(corrupt)
        try:restore_probe(root)
        except ValueError:pass
        else:raise AssertionError("Tampered delta accepted")
        assert not target.exists()
        assert not list(root.glob(".probe-*.tmp"))
    print("Exact offline reconstruction and corrupt/truncated/extra data guards passed")

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("tools");a=p.parse_args();audit(a.tools)
