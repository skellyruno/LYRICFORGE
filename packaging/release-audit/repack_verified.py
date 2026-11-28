"""Copy exactly the verified installed payload; omit only reconstructed FFprobe."""
import argparse,json,re,shutil
from pathlib import Path
from payload_integrity import manifest,compare

def copy_verified(source,ledger,dest):
    source,dest=Path(source),Path(dest)
    expected=json.loads(Path(ledger).read_text(encoding="utf-8-sig"))
    if len(expected)!=391:raise ValueError("Unexpected verified payload")
    compare(expected,manifest(source))
    if dest.exists():raise ValueError("Destination exists")
    dest.mkdir(parents=True)
    staged=[r for r in expected if r[0]!="_internal/tools/ffprobe.exe"]
    if len(staged)!=len(expected)-1:raise ValueError("Wrong probe payload")
    for name,_,_ in staged:
        target=dest/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source/name,target)
    compare(staged,manifest(dest))
    print("Copied exact verified runtime; only generated FFprobe omitted.")

def verify_upgrade(root,old,new,out,changed,unknown):
    root=Path(root)
    old={k:(s,h) for k,s,h in json.loads(Path(old).read_text(encoding="utf-8-sig"))}
    new={k:(s,h) for k,s,h in json.loads(Path(new).read_text(encoding="utf-8-sig"))}
    actual={k:(s,h) for k,s,h in manifest(root)}
    from cleanup_legacy_media import PREFIXES
    targets={k:v for k,v in old.items() if k not in new and k.startswith(PREFIXES)}
    changed=json.loads(Path(changed).read_text(encoding="utf-8-sig"))
    user=json.loads(Path(unknown).read_text(encoding="utf-8-sig"))
    incorrect=[k for k,v in new.items() if actual.get(k)!=v]
    survivors=[k for k in targets if k in actual and k not in changed]
    modified=[k for k,v in {**changed,**user}.items() if actual.get(k)!=tuple(v)]
    unexpected=[k for k,v in actual.items() if k not in new and k not in changed and k not in user and
                not re.fullmatch(r"unins\d{3}\.(exe|dat|msg)",k,re.I) and old.get(k)!=v]
    result={"missing_or_changed_new":incorrect,"unexpected_legacy_survivors":survivors,"user_files_changed":modified,
            "unknown_extra":unexpected,"removed_legacy_bytes":sum(v[0] for k,v in targets.items() if k not in actual),
            "removed_legacy_count":sum(k not in actual for k in targets),"passed":not (incorrect or survivors or modified or unexpected)}
    Path(out).write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result),flush=True)
    if not result["passed"]:raise RuntimeError("Integrated upgrade cleanup gate failed")

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("mode",choices=["copy","upgrade"]);p.add_argument("args",nargs="+");a=p.parse_args()
    {"copy":copy_verified,"upgrade":verify_upgrade}[a.mode](*a.args)
