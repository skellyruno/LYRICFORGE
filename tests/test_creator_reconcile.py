from tools.reconcile_creator import propose

def test_reconcile_preserves_creator_and_nonoverlapping_changes():
    base={'both.py':b'first\nsecond\nthird\nfourth\nfifth\n','bad.py':b'x=1\n','.github/workflows/test.yml':b'base\n'}
    creator={'both.py':b'FIRST\nsecond\nthird\nfourth\nfifth\n','bad.py':b'x=2\n','.github/workflows/test.yml':b'creator\n','creator_only.py':b'ok\n'}
    editorial={'both.py':b'first\nsecond\nthird\nfourth\nFIFTH\n','bad.py':b'x=3\n','.github/workflows/test.yml':b'editorial\n','new.py':b'new\n'}
    output,rows,conflicts=propose(creator,base,editorial)
    assert output['both.py']==b'FIRST\nsecond\nthird\nfourth\nFIFTH\n'
    assert output['creator_only.py']==b'ok\n' and output['new.py']==b'new\n'
    assert output['bad.py']==b'x=2\n' and conflicts['bad.py']==b'x=3\n'
    assert output['.github/workflows/test.yml']==b'creator\n'
    assert creator['both.py']==b'FIRST\nsecond\nthird\nfourth\nfifth\n'
