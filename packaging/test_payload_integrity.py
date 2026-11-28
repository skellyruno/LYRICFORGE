import tempfile
import unittest
from pathlib import Path
from payload_integrity import manifest, compare, digest

class PayloadTests(unittest.TestCase):
    def test_actual_changes_and_uninstaller(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'a').write_bytes(b'abc'); before=manifest(root)
            (root/'unins000.exe').write_bytes(b'uninstaller'); compare(before,manifest(root))
            (root/'a').write_bytes(b'def')
            with self.assertRaisesRegex(ValueError,'changed='):compare(before,manifest(root))
            (root/'a').unlink()
            with self.assertRaisesRegex(ValueError,'missing='):compare(before,manifest(root))
    def test_unexpected_file(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'a').write_bytes(b'abc'); before=manifest(root)
            (root/'extra.dll').write_bytes(b'extra')
            with self.assertRaisesRegex(ValueError,'unexpected='):compare(before,manifest(root))
    def test_digest_tracks_names_and_bytes(self):
        self.assertNotEqual(digest([['a',1,'x']]),digest([['b',1,'x']]))
        self.assertNotEqual(digest([['a',1,'x']]),digest([['a',1,'y']]))
if __name__=='__main__':unittest.main()
