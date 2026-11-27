"""Create a non-destructive Creator/editorial integration proposal.
The older source snapshot is only a comparison ancestor, not a proven Git merge base.
Divergent text may be cleanly merged for review, never auto-promoted to a branch.
"""
from __future__ import annotations
import argparse,hashlib,json,stat,subprocess,tempfile,zipfile
from pathlib import Path,PurePosixPath


def digest(data):return hashlib.sha256(data).hexdigest()

LEGACY_EVIDENCE = frozenset({
    "verification/python-tests.log", "verification/v5-integration.log",
    "verification/demo-plan.json", "verification/demo-result.json",
    "verification/render-contact.jpg",
})


def archive_files(archive, *, legacy_evidence=False):
    out={}
    with zipfile.ZipFile(archive) as z:
        for member in z.infolist():
            p=PurePosixPath(member.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in member.filename or ':' in member.filename or stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError('Unsafe archive path')
            if member.is_dir():continue
            if legacy_evidence and member.filename in LEGACY_EVIDENCE:
                continue  # evidence stays in the original, hash-pinned archive
            if len(p.parts)<2 or p.parts[0]!='LYRICFORGE-main':raise ValueError('Unexpected archive root: '+member.filename)
            key='/'.join(p.parts[1:])
            if key in out:raise ValueError('Duplicate archive path')
            out[key]=z.read(member)
    return out


def text_merge(local,base,incoming):
    if any(b'\x00' in x for x in (local,base,incoming)):return None
    try:
        for x in (local,base,incoming):x.decode('utf-8')
    except UnicodeDecodeError:return None
    with tempfile.TemporaryDirectory(prefix='skell-merge-') as tmp:
        names=[Path(tmp)/n for n in ('creator','comparison','editorial')]
        for p,data in zip(names,(local,base,incoming)):p.write_bytes(data)
        r=subprocess.run(['git','merge-file','-p',*[str(p) for p in names]],capture_output=True,timeout=30)
        return r.stdout if r.returncode==0 else None


def propose(creator,base,incoming):
    rows=[];output=dict(creator);conflicts={}
    for path in sorted(set(creator)|set(incoming)):
        a=creator.get(path);b=base.get(path);c=incoming.get(path);state=''
        if a==c:state='identical'
        elif c is None:state='creator-only'
        elif a is None:output[path]=c;state='editorial-addition'
        elif path.startswith('.github/workflows/'):
            state='workflow-review';conflicts[path]=c
        elif c==b:state='keep-creator'
        elif a==b:output[path]=c;state='take-editorial'
        elif b is not None:
            merged=text_merge(a,b,c)
            if merged is None:state='conflict';conflicts[path]=c
            else:state='clean-proposal';output[path]=merged
        else:state='conflict';conflicts[path]=c
        rows.append({'path':path,'status':state,'creator_sha256':digest(a) if a is not None else None,'comparison_sha256':digest(b) if b is not None else None,'editorial_sha256':digest(c) if c is not None else None,'proposal_sha256':digest(output[path])})
    return output,rows,conflicts


def main():
    p=argparse.ArgumentParser();p.add_argument('creator',type=Path);p.add_argument('base',type=Path);p.add_argument('incoming',type=Path);p.add_argument('destination',type=Path);a=p.parse_args()
    if a.destination.exists():raise FileExistsError(a.destination)
    files=subprocess.run(['git','-C',str(a.creator),'ls-files','-z'],capture_output=True,check=True).stdout.decode('utf-8').split('\x00')
    creator={n:(a.creator/n).read_bytes() for n in files if n and not n.startswith('field-notes/candidates/') and not (a.creator/n).is_symlink()}
    output,rows,conflicts=propose(creator,archive_files(a.base,legacy_evidence=True),archive_files(a.incoming));a.destination.mkdir(parents=True)
    for dirname,data in [('proposal',output),('unresolved-editorial',conflicts)]:
        for path,content in data.items():
            p=a.destination/dirname/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content)
    counts={}
    for r in rows:counts[r['status']]=counts.get(r['status'],0)+1
    (a.destination/'report.json').write_text(json.dumps({'policy':'Comparison snapshot is not a proven Git merge base. Clean proposals require code review and exact-commit tests. No automatic promotion.','counts':counts,'paths':rows,'legacy_evidence_policy':'Recognized comparison-only verification files remain in the preserved source ZIP.'},indent=2))
    print(json.dumps(counts,indent=2))
if __name__=='__main__':main()
