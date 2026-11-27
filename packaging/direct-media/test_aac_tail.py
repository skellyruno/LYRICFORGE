"""Regression for the PyAV-compatible AAC priming/tail contract."""
import unittest
from unittest.mock import patch
import studio_media_runtime as media

def meta(skip=1024,discard=128):
    return {"streams":[{"codec_name":"aac"}],"packets":[
        {"side_data_list":[{"side_data_type":"Skip Samples","skip_samples":skip,"discard_padding":0}]},
        {"side_data_list":[{"side_data_type":"Skip Samples","skip_samples":0,"discard_padding":discard}]}]}

class AacTailTests(unittest.TestCase):
    def test_keep_complete_last_frame(self):
        with patch.object(media,"probe_json",return_value=meta()) as probe:
            self.assertEqual(media.aac_trim("fixture.m4a"),1024)
            self.assertEqual(probe.call_count,1)
    def test_zero_priming(self):
        with patch.object(media,"probe_json",return_value=meta(0,0)):
            self.assertEqual(media.aac_trim("fixture.m4a"),0)
    def test_reject_midstream_skip(self):
        d=meta();d["packets"][1]["side_data_list"][0]["skip_samples"]=1024
        with patch.object(media,"probe_json",return_value=d),self.assertRaises(ValueError):
            media.aac_trim("fixture.m4a")
    def test_reject_midstream_discard(self):
        d=meta();d["packets"][0]["side_data_list"][0]["discard_padding"]=256
        with patch.object(media,"probe_json",return_value=d),self.assertRaises(ValueError):
            media.aac_trim("fixture.m4a")

if __name__=="__main__":unittest.main()
