import hashlib,json,tempfile,unittest
from pathlib import Path
from cleanup_legacy_media import cleanup

class CleanupTests(unittest.TestCase):
    def test_only_exact_obsolete_files(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"app";root.mkdir()
            def create(name,data):
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
                return [name,len(data),hashlib.sha256(data).hexdigest()]
            exe=create("SkellyMotion.exe",b"new")
            stale=create("_internal/av.libs/old.dll",b"obsolete")
            modified=create("_internal/av/changed.py",b"original")
            unrelated=create("user-song.wav",b"private")
            active=create("_internal/av/needed.dll",b"required")
            (root/modified[0]).write_bytes(b"changed!")
            old=Path(td)/"old.json";new=Path(td)/"new.json";out=Path(td)/"out.json"
            old.write_text(json.dumps([stale,modified,unrelated,active]))
            new.write_text(json.dumps([exe,active]))
            dry=cleanup(root,old,new,out)
            self.assertTrue((root/stale[0]).exists())
            result=cleanup(root,old,new,out,True)
            self.assertFalse((root/stale[0]).exists())
            self.assertEqual(result["removed_bytes"],len(b"obsolete"))
            self.assertEqual((root/modified[0]).read_bytes(),b"changed!")
            self.assertEqual((root/unrelated[0]).read_bytes(),b"private")
            self.assertEqual((root/active[0]).read_bytes(),b"required")
            self.assertEqual(cleanup(root,old,new,out,True)["removed_bytes"],0)

if __name__=="__main__":unittest.main()
