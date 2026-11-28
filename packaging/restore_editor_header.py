"""Replace precisely the old header/fav icon references in a tested payload."""
import argparse, hashlib, json
from pathlib import Path
from payload_integrity import manifest

OLD="1d65a83e8ab4f479d2102ac23c8484acb5833c17b82c72bb087b155b0c4981cc"
NEW="005e47820db5a6b7e8dde198725d585b49312a2ee521666afed729799c1bbe61"
ASSET="39748d1de80ede7f6aa95f1f1574dfd54ce30c7fc6e2cde1443e777ba55deb09"
REL="_internal/static/index.html"

def sha(data):return hashlib.sha256(data).hexdigest()

def patch(original):
    if sha(original)!=OLD:raise ValueError("Unexpected original index")
    result=original.replace(b'<img src="/static/skull.svg" alt="" />',b'<img src="/static/skelly-skull.png" alt="" />').replace(b'<link rel="icon" href="/static/skull.svg" type="image/svg+xml" />',b'<link rel="icon" href="/static/skellyhub.ico" type="image/x-icon" />')
    if sha(result)!=NEW:raise ValueError("Unexpected HTML changes")
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument("root",type=Path);p.add_argument("source",type=Path);p.add_argument("ledger",type=Path);p.add_argument("evidence",type=Path);a=p.parse_args()
    before=json.loads(a.ledger.read_text(encoding="utf-8"))
    if manifest(a.root)!=before:raise ValueError("Unexpected payload before header fix")
    if sha((a.root/"_internal/static/skelly-skull.png").read_bytes())!=ASSET:raise ValueError("Original header artwork changed")
    index=a.root/REL;fixed=patch(index.read_bytes())
    # Git for Windows may checkout the exact LF blob using CRLF. Normalize
    # only the checkout comparison; retain the exact verified artifact bytes.
    checked_out=a.source.read_bytes()
    normalized=checked_out.replace(b"\r\n",b"\n")
    if normalized!=fixed:raise ValueError(f"Source differs from exact staged HTML: raw={sha(checked_out)} normalized={sha(normalized)} expected={NEW}")
    print("Header source matches exact verified bytes after checkout newline normalization")
    index.write_bytes(fixed)
    after=manifest(a.root)
    if len(before)!=len(after) or [x for x in before if x[0]!=REL]!=[x for x in after if x[0]!=REL]:raise ValueError("Unrelated payload changes")
    a.ledger.write_text(json.dumps(after,indent=2),encoding="utf-8")
    result={"changed_path":REL,"old_index_sha256":OLD,"new_index_sha256":NEW,"original_artwork_sha256":ASSET,"unchanged_layout_markup":True,"unchanged_other_payload_files":True}
    a.evidence.write_text(json.dumps(result,indent=2),encoding="utf-8");print(json.dumps(result,indent=2))

if __name__=="__main__":main()
