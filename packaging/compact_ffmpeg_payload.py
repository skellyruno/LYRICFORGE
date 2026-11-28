"""A compact runtime may replace exactly one file; no silent dependency deletions."""
import argparse,json
from pathlib import Path
from payload_integrity import manifest,digest,compare,EXPECTED,sha

FFMPEG='_internal/tools/ffmpeg.exe'
def stage(root,candidate,ledger):
    before=manifest(root)
    if digest(before)!=EXPECTED or len(before)!=643:raise ValueError('Original package does not match verified payload')
    old=root/FFMPEG
    if candidate.stat().st_size>=old.stat().st_size:raise ValueError('Replacement is not smaller')
    candidate_hash=sha(candidate)
    old.write_bytes(candidate.read_bytes())
    after=manifest(root)
    if len(after)!=len(before):raise ValueError('File count changed')
    if [r for r in before if r[0]!=FFMPEG]!=[r for r in after if r[0]!=FFMPEG]:raise ValueError('Unrelated payload changed')
    if sha(old)!=candidate_hash:raise ValueError('Replacement copy changed')
    ledger.write_text(json.dumps(after,indent=2),encoding='utf-8')
    print('Verified all other 642 files unchanged; candidate FFmpeg SHA256',candidate_hash)
def installed(root,ledger):
    compare(json.loads(ledger.read_text(encoding='utf-8')),manifest(root))
    print('Installed payload matches exact replacement ledger')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['stage','installed']);p.add_argument('root',type=Path);p.add_argument('ledger',type=Path);p.add_argument('--candidate',type=Path);a=p.parse_args()
    if a.mode=='stage':
        if not a.candidate:raise ValueError('Missing replacement binary')
        stage(a.root,a.candidate,a.ledger)
    else:installed(a.root,a.ledger)
