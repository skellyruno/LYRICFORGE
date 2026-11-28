import unittest
from pathlib import Path
from stage_direct_candidate import checked_media_region, git_blob_id, verified_reference

REFERENCE="prefix\ndef media_duration(path: Path) -> float:\n    return 2.\n\n\nasync def save_upload(\n"

class TestMediaRegion(unittest.TestCase):
    def test_unchanged_functions_allow_new_routes(self):
        value="new routes\n"+REFERENCE+"new editor\n"
        a,b=checked_media_region(value,REFERENCE)
        c,d=checked_media_region(REFERENCE,REFERENCE)
        self.assertEqual(value[a:b],REFERENCE[c:d])
        self.assertIn("new editor",value[b:])

    def test_changed_region_rejected(self):
        with self.assertRaises(ValueError):
            checked_media_region(REFERENCE.replace("return 2.","return 3."),REFERENCE)

    def test_duplicate_or_missing_anchors_rejected(self):
        for value in (REFERENCE+REFERENCE,REFERENCE.replace("async def save_upload(",""),"async def save_upload(\n"+REFERENCE.split("async def save_upload(")[0]):
            with self.assertRaises(ValueError):
                checked_media_region(value,REFERENCE)

    def test_git_blob_id_is_exact_bytes(self):
        self.assertEqual(git_blob_id(b""),"e69de29bb2d1d6434b8b29ae775ad8c2e48c5391")
        self.assertNotEqual(git_blob_id(b"a\n"),git_blob_id(b"a\r\n"))

    def test_pinned_repository_reference_preflight(self):
        root=Path(__file__).resolve().parents[2]
        current=(root/"server.py").read_text(encoding="utf-8")
        reference=verified_reference(root)
        checked_media_region(current,reference)
