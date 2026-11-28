import unittest
from compact_aac_metadata import priming_from_debug

HEADER = "Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'x':\n"
STREAM = "  Stream #0:0: Audio: aac (LC), 48000 Hz, stereo\n"
SKIP = "[mov,mp4,m4a,3gp,3g2,mj2 @ 000001A] demuxer injecting skip 1024 / discard 0\n"

class MetadataTests(unittest.TestCase):
    def test_exact_skip(self):
        self.assertEqual(priming_from_debug(SKIP+HEADER+STREAM),1024)
    def test_ignore_output_stream(self):
        self.assertEqual(priming_from_debug(SKIP+HEADER+STREAM+"Stream mapping:\n"+STREAM),1024)
    def test_delayed_packet_log(self):
        self.assertEqual(priming_from_debug(HEADER+STREAM+"Stream mapping:\n"+SKIP),1024)
    def test_ambiguous_delayed_skip(self):
        with self.assertRaises(ValueError):
            priming_from_debug(SKIP+HEADER+STREAM+"Stream mapping:\n"+SKIP)
    def test_ffmpeg9_input_prefix(self):
        actual=SKIP.replace("[mov,", "[in#0/mov,")
        self.assertEqual(priming_from_debug(actual+HEADER+STREAM),1024)
    def test_unexpected_input_prefix(self):
        with self.assertRaises(ValueError):
            priming_from_debug(SKIP.replace("[mov,","[in#1/mov,")+HEADER+STREAM)
    def test_fail_closed(self):
        for log in (HEADER+STREAM, SKIP+SKIP+HEADER+STREAM,
                    SKIP+HEADER+STREAM+STREAM.replace('#0:0','#0:1'),
                    SKIP.replace('discard 0','discard 1')+HEADER+STREAM,
                    SKIP.replace('1024','8193')+HEADER+STREAM,
                    SKIP+HEADER+STREAM.replace('aac','mp3')):
            with self.subTest(log=log),self.assertRaises(ValueError):
                priming_from_debug(log)

if __name__=='__main__':unittest.main()
