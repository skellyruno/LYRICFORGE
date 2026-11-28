"""Promote only the byte-exact, gated application source; never delete tracked files."""
from pathlib import Path,PurePosixPath
import argparse,hashlib,json,os,stat,subprocess,zipfile

ARCHIVE_SHA='4d874c8de450ce1c9fad725b45ce03ed4cf2a41105ab1499dbe574d9e95e4540'
PRODUCER='13d8311ad66f39418110db4785170f5846e8cce2'
BRANCH='feature/field-notes-production-20261126'
PREFIX='LYRICFORGE-main/'

def sha(b):return hashlib.sha256(b).hexdigest()
def git(root,*args):return subprocess.check_output(['git','-C',str(root),*args])

def prepare(root,artifact,report):
    root,artifact,report=map(lambda p:Path(p).resolve(),(root,artifact,report))
    if (artifact/'producer-revision.txt').read_text().strip()!=PRODUCER:raise ValueError('Wrong producer')
    archive=artifact/'candidate.zip'
    if sha(archive.read_bytes())!=ARCHIVE_SHA:raise ValueError('Wrong exact candidate checksum')
    if git(root,'status','--porcelain','--untracked-files=no'):raise ValueError('Tracked worktree is dirty')
    tracked=set(git(root,'ls-files','-z').decode().strip('\0').split('\0'))
    payload={}
    with zipfile.ZipFile(archive) as z:
        for entry in z.infolist():
            if not entry.filename.startswith(PREFIX) or entry.is_dir():raise ValueError('Unexpected archive entry')
            path=entry.filename[len(PREFIX):];parts=PurePosixPath(path).parts
            if not parts or path.startswith('/') or '\\' in path or '..' in parts or '.' in parts or ':' in path or parts[0] in ('.git','field-notes'):raise ValueError('Unsafe archive path')
            if stat.S_ISLNK(entry.external_attr>>16) or path in payload:raise ValueError('Duplicate or symlink entry')
            if entry.file_size>10*1024*1024:raise ValueError('Unexpected large file')
            if Path(path).suffix.lower() in ('.wav','.mp3','.mp4','.zip','.exe','.bin','.onnx','.safetensors'):raise ValueError('Unexpected media or model in source')
            payload[path]=z.read(entry)
    if len(payload)!=291:raise ValueError('Unexpected candidate file count')
    extra=sorted(p for p in tracked if p not in payload and
        (p.startswith(('static/','tests/','packaging/','examples/')) or '/' not in p))
    if extra:raise ValueError('Existing runtime or test files missing from candidate: '+', '.join(extra))
    # Workflows and repository rules were deliberately reconciled separately.
    # Abort instead of letting the automation edit protected files.
    for name,content in payload.items():
        if name.startswith('.github/') or name=='AGENTS.md':
            if not (root/name).is_file() or (root/name).read_bytes()!=content:raise ValueError('Protected source mismatch: '+name)
    changes=[]
    for name,content in sorted(payload.items()):
        if name.startswith('.github/') or name=='AGENTS.md':continue
        dst=root/name
        if dst.is_symlink() or any(parent.is_symlink() for parent in dst.parents if parent!=root.parent):raise ValueError('Symlink destination')
        previous=sha(dst.read_bytes()) if dst.is_file() else None
        if previous==sha(content):continue
        dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(content)
        git(root,'add','-f','--',name)
        changes.append({'path':name,'before_sha256':previous,'after_sha256':sha(content)})
    if git(root,'diff','--cached','--name-only','--diff-filter=D'):raise ValueError('Unexpected file deletion')
    for name,content in payload.items():
        if sha(git(root,'show',':'+name))!=sha(content):raise ValueError('Index differs from tested candidate: '+name)
    report.write_text(json.dumps({'producer':PRODUCER,'archive_sha256':ARCHIVE_SHA,'files':len(payload),
        'changes':changes,'preserved_extra_paths':sorted(tracked-payload.keys()),'deletions':0},indent=2),encoding='utf-8')
    print('Exact application files verified in Git index:',len(payload),'changed:',len(changes))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('artifact');p.add_argument('report');a=p.parse_args();prepare(a.root,a.artifact,a.report)
