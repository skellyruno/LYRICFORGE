import tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import studio_media_runtime as media

class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"sample"
        self.path.write_bytes(b"unknown")
        media.clear_probe_cache()
    def test_probe_reused_and_copied(self):
        with patch.object(media,"probe_json",return_value={"streams":[{"codec_name":"aac"}]}) as p:
            media.media_info(self.path)["streams"].clear()
            self.assertEqual(media.media_info(self.path)["streams"][0]["codec_name"],"aac")
            self.assertEqual(p.call_count,1)
    def test_file_change_invalidates(self):
        with patch.object(media,"probe_json",return_value={}) as p:
            media.media_info(self.path)
            self.path.write_bytes(b"changed size")
            media.media_info(self.path)
            self.assertEqual(p.call_count,2)
    def test_change_during_probe_rejected(self):
        def change(*args):
            self.path.write_bytes(b"changed size")
            return {}
        with patch.object(media,"probe_json",side_effect=change),self.assertRaises(ValueError):
            media.media_info(self.path)
    def test_magic_not_suffix(self):
        for head in (b"RIFF0000WAVE",b"RF640000WAVE",b"fLaC",b"OggS"):
            self.path.write_bytes(head);self.assertTrue(media.direct_container(self.path))
        self.path.write_bytes(b"\0\0\0\x18ftypmp42")
        self.assertFalse(media.direct_container(self.path))

if __name__=="__main__":unittest.main()
