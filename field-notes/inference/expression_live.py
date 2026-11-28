"""Optional real expression audition. Only built-in voice; no owner media."""
import hashlib,json,os,sys
from pathlib import Path
from huggingface_hub import HfApi,snapshot_download
from studio_expression_worker import FILES,run

REPO='ResembleAI/chatterbox'
REV='fcdac3112359983a8dd4a798da91ab87b96006ca'
T3_SHA='914cb1696f47527fe8852ca8f1fe1fa63cb34f76f9c715e84e067b744dd0da81'

def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    folder=Path(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
    info=HfApi().model_info(REPO,revision=REV,files_metadata=True)
    if info.sha!=REV:raise ValueError('Model revision mismatch')
    metadata={x.rfilename:x for x in info.siblings}
    snapshot_download(REPO,revision=REV,allow_patterns=list(FILES),local_dir=folder)
    verified={}
    for name in FILES:
        p=folder/name;s=metadata[name];sha=digest(p)
        if p.stat().st_size!=s.size:raise ValueError('Unexpected model size '+name)
        if s.lfs is not None:
            if sha!=s.lfs.sha256:raise ValueError('Unexpected model LFS digest '+name)
        else:
            raw=p.read_bytes()
            if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!=s.blob_id:raise ValueError('Unexpected model Git blob '+name)
        verified[name]={'bytes':s.size,'sha256':sha}
    if verified['t3_cfg.safetensors']['sha256']!=T3_SHA:raise ValueError('Pinned speech model changed')
    (out/'provenance.json').write_text(json.dumps({'repo':REPO,'revision':REV,'files':verified},indent=2))
    text='Shape the sound. Every choice is yours.'
    rows=run(folder,out,{'phrases':[text]*3,'directions':['detail','reveal','close']})
    hashes=[digest(out/r['file']) for r in rows]
    if len(set(hashes))!=3:raise ValueError('Expression conditions generated identical audio')
    (out/'report.json').write_text(json.dumps({'passed':True,'text':text,'takes':rows,'hashes':hashes,'scope':'Actual native emotion-conditioning audition; different signals are not proof of better perceptual acting.'},indent=2))
if __name__=='__main__':main()
