"""Build the offline probe delta from the exact existing executables."""
import argparse,hashlib,io,subprocess,zlib
from pathlib import Path
from studio_probe_delta import BASE_SHA,PROBE_SHA,MAX_DELTA,sha,apply_delta

def generate(base,probe,out):
    base,probe,out=[Path(x).resolve() for x in (base,probe,out)]
    if sha(base)!=BASE_SHA or sha(probe)!=PROBE_SHA:raise ValueError("Wrong native artifact")
    r=subprocess.run(["git","-c","core.bigFileThreshold=100m","diff","--no-index","--binary","--",str(base),str(probe)],capture_output=True,timeout=120)
    if r.returncode!=1:raise RuntimeError("Git binary diff failed")
    lines=r.stdout.decode("ascii").splitlines();start=lines.index("GIT binary patch")+1
    mode,size=lines[start].split()
    if mode!="delta" or not 0<int(size)<=MAX_DELTA:raise ValueError("Unexpected delta size")
    table={c:i for i,c in enumerate("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!#$%&()*+-;<=>?@^_"+chr(96)+"{|}~")}
    packed=bytearray()
    for line in lines[start+1:]:
        if not line:break
        n=ord(line[0])-(64 if line[0].isupper() else 70);encoded=line[1:]
        if not 1<=n<=52 or len(encoded)%5:raise ValueError("Bad binary patch")
        block=bytearray()
        for i in range(0,len(encoded),5):
            v=0
            for c in encoded[i:i+5]:v=v*85+table[c]
            block.extend(v.to_bytes(4,"big"))
        packed.extend(block[:n])
    delta=zlib.decompress(packed)
    if len(delta)!=int(size):raise ValueError("Wrong delta length")
    output=io.BytesIO();apply_delta(base.read_bytes(),delta,output)
    if hashlib.sha256(output.getbuffer()).hexdigest()!=PROBE_SHA:raise ValueError("Nonidentical reconstruction")
    out.write_bytes(delta)
    print("Exact FFprobe restored; delta bytes",len(delta),"deflated",len(packed),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    for arg in ("base","probe","out"):p.add_argument(arg)
    a=p.parse_args();generate(a.base,a.probe,a.out)
