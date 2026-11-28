import unittest
from stage_direct_candidate import checked_media_region

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
