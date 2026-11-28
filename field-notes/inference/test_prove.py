import hashlib
import tempfile
import unittest
from pathlib import Path
from prove import word_error_rate,valid_timing,valid_vision,verify_files

class ProofChecks(unittest.TestCase):
    def test_error_rates(self):
        self.assertEqual(word_error_rate('One two THREE.','one two three'),0)
        self.assertAlmostEqual(word_error_rate('one two three','one three'),1/3)
        self.assertEqual(word_error_rate('one two','one two three four'),1)
    def test_timing_rejects_invalid(self):
        self.assertTrue(valid_timing([{'start':0,'end':1}],1))
        self.assertFalse(valid_timing([],1))
        self.assertFalse(valid_timing([{'start':0,'end':2}],1))
        self.assertFalse(valid_timing([{'start':float('nan'),'end':1}],1))
        self.assertFalse(valid_timing([{'start':.5,'end':.6},{'start':.1,'end':.3}],1))
    def test_vision_checks_both_axes(self):
        self.assertTrue(valid_vision([[3,1,0],[1,3,0],[0,0,3]]))
        self.assertFalse(valid_vision([[1,2,0],[0,3,0],[0,0,3]]))
        self.assertFalse(valid_vision([[3,1,0],[4,5,0],[0,0,3]]))
        self.assertFalse(valid_vision([[3,1,0],[1,3,0],[0,0,float('nan')]]))
    def test_integrity_rejects_missing_and_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);spec={'files':['model.safetensors','config.json'],'weight':'model.safetensors','sha256':hashlib.sha256(b'known').hexdigest()}
            with self.assertRaises(ValueError):verify_files(root,spec)
            (root/'config.json').write_text('{}')
            (root/'model.safetensors').write_bytes(b'wrong')
            with self.assertRaises(ValueError):verify_files(root,spec)
            (root/'model.safetensors').write_bytes(b'known')
            self.assertEqual(verify_files(root,spec),spec['sha256'])
if __name__=='__main__':unittest.main()
