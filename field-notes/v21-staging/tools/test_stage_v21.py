import json
from pathlib import Path
import shutil
import sys
import pytest
sys.path.insert(0, str(Path(__file__).parent))
import stage_v21 as s

PATCH = Path(__file__).resolve().parents[2] / 'candidates/SkellyMotion-V21-Reconciliation-Patch.zip'

@pytest.fixture
def proposal(tmp_path):
    root = tmp_path / 'reconciliation'
    source = root / 'proposal'
    source.mkdir(parents=True)
    (root / 'creator-revision.txt').write_text(s.BASE)
    names = (s.UNRESOLVED | s.WORKFLOWS | s.FILES | {'studio_theme.py'}) - {'tests/test_v21_reconciled_components.py'}
    rows = []
    for name in names:
        p = source / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(name)
        rows.append({'path': name, 'proposal_sha256': s.sha(p.read_bytes())})
    (root / 'report.json').write_text(json.dumps({'paths': rows}))
    return root

def test_stage(proposal, tmp_path):
    out = tmp_path / 'candidate'
    evidence = s.stage(proposal, PATCH, out)
    assert set(evidence['remaining_conflicts']) == s.UNRESOLVED
    assert (out / 'studio_theme.py').read_text() == 'studio_theme.py'
    assert (out / 'static/index.html').read_text() == 'static/index.html'
    assert (proposal / 'proposal/server.py').read_text() == 'server.py'
    assert (out / 'server.py').stat().st_size > 200000
    with pytest.raises(ValueError): s.stage(proposal, PATCH, out)

def test_reject_base(proposal,tmp_path):
    (proposal / 'creator-revision.txt').write_text('old')
    with pytest.raises(ValueError, match='Wrong Creator base'): s.stage(proposal,PATCH,tmp_path/'candidate')

def test_reject_archive(proposal,tmp_path):
    copy=tmp_path/'patch.zip';shutil.copyfile(PATCH,copy);copy.write_bytes(copy.read_bytes()+b'x')
    with pytest.raises(ValueError,match='archive hash'):s.stage(proposal,copy,tmp_path/'candidate')

def test_reject_drift(proposal,tmp_path):
    (proposal/'proposal/server.py').write_text('changed')
    with pytest.raises(ValueError,match='Proposal drift'):s.stage(proposal,PATCH,tmp_path/'candidate')

def test_reject_extra(proposal,tmp_path):
    (proposal/'proposal/unknown.py').write_text('changed')
    with pytest.raises(ValueError,match='Unexpected proposal'):s.stage(proposal,PATCH,tmp_path/'candidate')
