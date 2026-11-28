import struct

def append_resources(original, resources, end):
    """Append a resource-only section; leave all existing mapped sections in place."""
    data=bytearray(original[:end]); overlay=original[end:]
    u16=lambda o:struct.unpack_from('<H',data,o)[0]
    u32=lambda o:struct.unpack_from('<I',data,o)[0]
    put=lambda o,v:struct.pack_into('<I',data,o,v)
    p=u32(60); opt=p+24; n=u16(p+6); st=opt+u16(p+20)
    if u16(opt)!=0x20b:raise ValueError('Expected x64 application')
    sa,fa=struct.unpack_from('<II',data,opt+32)
    align=lambda n,a:(n+a-1)//a*a
    if not sa or not fa or end%fa:raise ValueError('Unexpected PE alignment')
    slot=st+40*n
    if slot+40>u32(opt+60) or any(data[slot:slot+40]):raise ValueError('No spare section header')
    if u32(p+12) or u32(p+16):raise ValueError('Unexpected COFF symbol table')
    va=align(max(u32(st+40*i+12)+max(u32(st+40*i+8),u32(st+40*i+16)) for i in range(n)),sa)
    tree={}
    for path,payload in resources.items():
        if len(path)!=3 or any(not isinstance(k,int) or not 0<=k<=0xffff for k in path):raise ValueError('Unexpected named resource')
        tree.setdefault(path[0],{}).setdefault(path[1],{})[path[2]]=payload
    blob=bytearray()
    def alloc(size):
        while len(blob)%4:blob.append(0)
        offset=len(blob);blob.extend(b'\0'*size);return offset
    def directory(node):
        off=alloc(16+8*len(node));struct.pack_into('<HH',blob,off+12,0,len(node))
        for i,(key,value) in enumerate(sorted(node.items())):
            if isinstance(value,dict):target=directory(value)|0x80000000
            else:
                target=alloc(16);pos=alloc(len(value));blob[pos:pos+len(value)]=value
                struct.pack_into('<IIII',blob,target,va+pos,len(value),1252,0)
            struct.pack_into('<II',blob,off+16+8*i,key,target)
        return off
    assert directory(tree)==0
    size=align(len(blob),fa)
    struct.pack_into('<8sIIIIIIHHI',data,slot,b'.skicon\0',len(blob),va,size,end,0,0,0,0,0x40000040)
    struct.pack_into('<H',data,p+6,n+1)
    put(opt+8,u32(opt+8)+size)
    put(opt+56,align(va+len(blob),sa))
    put(opt+64,0)
    struct.pack_into('<II',data,opt+112+16,va,len(blob))
    return bytes(data)+bytes(blob)+b'\0'*(size-len(blob))+overlay
