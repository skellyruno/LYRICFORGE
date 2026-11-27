"""Change only native icon resources of the verified frozen executable.

Windows resource APIs operate on the PE stub, never on the PyInstaller
archive. Prove the archive and all executable sections remain unchanged.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import tempfile
from payload_integrity import manifest
from append_icon_resources import append_resources

ICON_SHA = "c472c19bbf94f3fdac172c1eeff7322d5e7dc2093e98cc095f2380a3e9bd82bb"
MAGIC = b"MEI\x0c\x0b\x0a\x0b\x0e"
def sha(b):
    return hashlib.sha256(b).hexdigest()

def pe(data):
    u16=lambda o:struct.unpack_from("<H",data,o)[0]
    u32=lambda o:struct.unpack_from("<I",data,o)[0]
    if data[:2]!=b"MZ":raise ValueError("Not PE")
    p=u32(60);opt=p+24
    if data[p:p+4]!=b"PE\0\0" or u16(opt) not in (0x10b,0x20b):raise ValueError("Not PE32 or PE32+")
    n=u16(p+6);st=opt+u16(p+20);dirs=opt+(112 if u16(opt)==0x20b else 96)
    if u32(dirs+32) or u32(dirs+36):raise ValueError("Refuse to alter signed PE")
    sections={}
    spans=[]
    for i in range(n):
        o=st+40*i;name=data[o:o+8].rstrip(b"\0")
        v,va,size,ptr=struct.unpack_from("<IIII",data,o+8)
        if ptr+size>len(data):raise ValueError("Invalid section bounds")
        sections[name]=(va,v,u32(o+36),data[ptr:ptr+size]);spans.append((va,max(size,v),ptr,size))
    end=max(ptr+size for va,v,ptr,size in spans)
    def offset(rva):
        for va,v,ptr,size in spans:
            if va<=rva<va+size:return ptr+rva-va
        raise ValueError("Invalid resource RVA")
    base=offset(u32(dirs+16));resources={}
    def walk(o,path):
        if len(path)>3:raise ValueError("Invalid resource tree")
        for i in range(u16(base+o+12)+u16(base+o+14)):
            key,b=struct.unpack_from("<II",data,base+o+16+i*8)
            if key&0x80000000:
                q=base+(key&0x7fffffff)
                key=data[q+2:q+2+2*u16(q)].decode("utf-16le")
            if b&0x80000000:walk(b&0x7fffffff,path+(key,))
            else:
                r,l=struct.unpack_from("<II",data,base+b)
                a=offset(r);resources[path+(key,)]=data[a:a+l]
    walk(0,())
    return sections,resources,data[end:],end

def ico(data):
    zero,kind,n=struct.unpack_from("<HHH",data)
    if zero or kind!=1 or n!=7:raise ValueError("Wrong ICO")
    out=[]
    for i in range(n):
        d=data[6+i*16:22+i*16];size,pos=struct.unpack_from("<II",d,8)
        b=data[pos:pos+size]
        if len(b)!=size:raise ValueError("Invalid icon bounds")
        out.append((d[:12],b))
    return out

def group_images(resources,key):
    group=resources[key];n=struct.unpack_from("<H",group,4)[0]
    result=[]
    for i in range(n):
        e=group[6+14*i:20+14*i];rid=struct.unpack_from("<H",e,12)[0]
        matches=[v for k,v in resources.items() if k[:2]==(3,rid) and k[2]==key[2]]
        if len(matches)!=1:raise ValueError("Unexpected icon resource")
        result.append((e[:12],matches[0]))
    return result

def verify_icon(path,asset):
    _,rs,_,_=pe(Path(path).read_bytes());expected=ico(asset)
    keys=[k for k in rs if k[0]==14]
    # Setup may contain additional internal icon groups; at least the main
    # published icon must have all seven original images.
    want=sorted(sha(b) for _,b in expected)
    if not any(sorted(sha(b) for _,b in group_images(rs,k))==want for k in keys):
        raise ValueError("Embedded icon does not match original image resources")

def patch_exe(path,asset):
    original=path.read_bytes();sections,rs,overlay,end=pe(original)
    if overlay.rfind(MAGIC)<0:raise ValueError("Missing PyInstaller archive")
    groups=[k for k in rs if k[0]==14]
    if groups!=[(14,1,0)]:raise ValueError("Unexpected frozen app icon layout")
    key=groups[0];old=rs[key];items=ico(asset)
    if struct.unpack_from("<H",old,4)[0]!=len(items):raise ValueError("Icon count changed")
    ids=[struct.unpack_from("<H",old,6+14*i+12)[0] for i in range(len(items))]
    if len(set(ids))!=len(items):raise ValueError("Duplicate icon IDs")
    expected=dict(rs)
    group=old[:6]
    for (entry,image),rid in zip(items,ids):
        expected[(3,rid,0)]=image
        group+=entry+struct.pack("<H",rid)
    expected[key]=group
    final=append_resources(original,expected,end)
    new_sections,new_rs,new_overlay,_=pe(final)
    if set(new_sections)!=set(sections)|{b".skicon"}:raise ValueError("Unexpected section layout")
    if any(new_sections[k]!=v for k,v in sections.items()):raise ValueError("Original executable section changed")
    if new_rs!=expected:raise ValueError("Unrelated resource or icon image changed")
    if new_overlay!=overlay:raise ValueError("Frozen Python archive changed")
    with tempfile.TemporaryDirectory(dir=path.parent) as td:
        stub=Path(td)/"SkellyMotion.exe";stub.write_bytes(final)
        verify_icon(stub,asset)
        stub.replace(path)
    return {"original_exe_sha256":sha(original),"patched_exe_sha256":sha(final),"frozen_archive_sha256":sha(overlay),"frozen_archive_bytes":len(overlay),"non_resource_sections_identical":True,"unrelated_resources_identical":True}

def main():
    p=argparse.ArgumentParser();p.add_argument("mode",choices=["stage","verify"]);p.add_argument("path",type=Path);p.add_argument("asset",type=Path);p.add_argument("--ledger",type=Path);p.add_argument("--evidence",type=Path);a=p.parse_args()
    asset=a.asset.read_bytes()
    if sha(asset)!=ICON_SHA:raise ValueError("Original icon hash mismatch")
    if a.mode=="verify":
        verify_icon(a.path,asset);print("Verified original embedded SkellHub icon");return
    if not a.ledger or not a.evidence:raise ValueError("Ledger/evidence required")
    before=json.loads(a.ledger.read_text(encoding="utf-8"))
    if manifest(a.path)!=before:raise ValueError("Incorrect tested baseline")
    result=patch_exe(a.path/"SkellyMotion.exe",asset)
    (a.path/"_internal/static/skull.ico").write_bytes(asset)
    after=manifest(a.path)
    changed={"SkellyMotion.exe","_internal/static/skull.ico"}
    if len(before)!=len(after) or [r for r in before if r[0] not in changed]!=[r for r in after if r[0] not in changed]:
        raise ValueError("Unrelated package files changed")
    result["changed_paths"]=sorted(changed)
    result["icon_sha256"]=ICON_SHA
    a.ledger.write_text(json.dumps(after,indent=2),encoding="utf-8")
    a.evidence.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))
if __name__=="__main__":main()
