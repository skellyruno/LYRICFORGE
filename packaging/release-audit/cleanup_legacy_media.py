"""Narrow cleanup of exact, obsolete app-owned PyAV bytes, never user data.

Only explicit --apply changes files. Designed for the isolated upgrade gate;
not invoked by the public installer yet.
"""
import argparse,hashlib,json,os,stat
from pathlib import Path,PurePosixPath

PREFIXES=("_internal/av/","_internal/av.libs/","_internal/av-18.1.1.dist-info/")
REPARSE=0x400

def sha(path):
    with path.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()

def read(path):
    rows=json.loads(Path(path).read_text(encoding="utf-8-sig"))
    result={}
    for k,size,digest in rows:
        p=PurePosixPath(k)
        if p.is_absolute() or ".." in p.parts or "\\" in k or ":" in k or k in result:
            raise ValueError("Unsafe manifest path")
        if not isinstance(size,int) or size<0 or len(digest)!=64:raise ValueError("Invalid manifest")
        result[k]=(size,digest)
    return result

def safe_path(root,name):
    path=root
    for part in PurePosixPath(name).parts:
        path=path/part
        try:s=path.lstat()
        except FileNotFoundError:return None
        if stat.S_ISLNK(s.st_mode) or getattr(s,"st_file_attributes",0)&REPARSE:return None
    if not stat.S_ISREG(s.st_mode):return None
    return path

def cleanup(root,old_ledger,new_ledger,out,apply=False):
    root=Path(root).absolute()
    rs=root.lstat()
    if not root.is_dir() or stat.S_ISLNK(rs.st_mode) or getattr(rs,"st_file_attributes",0)&REPARSE:
        raise ValueError("Unsafe application root")
    old,new=read(old_ledger),read(new_ledger)
    exe=safe_path(root,"SkellyMotion.exe")
    if exe is None or "SkellyMotion.exe" not in new or (exe.stat().st_size,sha(exe))!=new["SkellyMotion.exe"]:
        raise ValueError("Target does not match exact installed new application")
    targets={k:v for k,v in old.items() if k not in new and k.startswith(PREFIXES)}
    report={"apply":apply,"eligible":len(targets),"removed":[],"retained":[],"missing":[],"eligible_bytes":sum(v[0] for v in targets.values())}
    for name,(size,digest) in sorted(targets.items()):
        p=safe_path(root,name)
        if p is None:
            report["missing"].append(name);continue
        before=p.stat()
        if before.st_size!=size or sha(p)!=digest:
            report["retained"].append({"path":name,"reason":"changed"});continue
        if not apply:
            report["removed"].append({"path":name,"bytes":size});continue
        try:
            after=p.stat()
            if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):
                report["retained"].append({"path":name,"reason":"changed during check"});continue
            p.unlink()
            report["removed"].append({"path":name,"bytes":size})
        except OSError as exc:
            report["retained"].append({"path":name,"reason":"locked or unavailable","error_type":type(exc).__name__})
    report["removed_bytes"]=sum(x["bytes"] for x in report["removed"])
    Path(out).write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in ("removed","retained","missing")}),flush=True)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    for name in ("root","old","new","out"):p.add_argument(name)
    p.add_argument("--apply",action="store_true")
    a=p.parse_args();cleanup(a.root,a.old,a.new,a.out,a.apply)
