"""Verify current payload, report only known unchanged old installer leftovers."""
import argparse,json,re
from pathlib import Path
from payload_integrity import manifest

def verify(root,old,new,out):
    old={r[0]:r[1:] for r in json.loads(Path(old).read_text(encoding="utf-8-sig"))}
    new={r[0]:r[1:] for r in json.loads(Path(new).read_text(encoding="utf-8-sig"))}
    actual={r[0]:r[1:] for r in manifest(root)}
    missing=[k for k,v in new.items() if actual.get(k)!=v]
    extra={k:v for k,v in actual.items() if k not in new and k!="user-note.keep" and not re.fullmatch(r"unins\d{3}\.(exe|dat|msg)",k,re.I)}
    unknown=[k for k,v in extra.items() if old.get(k)!=v]
    report={"expected_files":len(new),"missing_or_changed":missing,"unknown_extra":unknown,
            "old_files_retained":len(extra),"old_files_retained_bytes":sum(v[0] for v in extra.values()),
            "old_files_retained_paths":sorted(extra),"passed":not missing and not unknown}
    Path(out).write_text(json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!="old_files_retained_paths"}))
    if not report["passed"]:raise RuntimeError("Upgrade mismatch")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    for n in ("root","old","new","out"):p.add_argument(n)
    a=p.parse_args();verify(a.root,a.old,a.new,a.out)
