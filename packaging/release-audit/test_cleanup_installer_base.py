import unittest
from generate_cleanup_installer import check_base

class BaseGuardTests(unittest.TestCase):
    def test_comment_does_not_declare_section(self):
        check_base("[Setup]\n; Intentionally no [UninstallDelete] or [InstallDelete]\n[Files]\n")
    def test_actual_sections_rejected(self):
        for name in ("Code","UninstallDelete","installdelete"):
            with self.subTest(name=name),self.assertRaises(ValueError):
                check_base("[Setup]\r\n  ["+name+"] ; existing section\r\n")
    def test_normal_base(self):
        check_base("[Setup]\nAppName=SkellyMotion\n[Files]\n[Run]\n")

if __name__=="__main__":unittest.main()
