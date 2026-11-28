"""Installer payload identity checks. No deletion or mutation of installed files."""
import argparse
import hashlib
import json
from pathlib import Path
import re

EXPECTED = '01c8245266c36f5edfdc689331e7fbd450ec467e5d4b50b4ec3f4967242743af'
SOURCE = '13d8311ad66f39418110db4785170f5846e8cce2'

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def manifest(root):
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError('Missing or unsafe payload root')
    rows = []
    names = set()
    for p in sorted(root.rglob('*'), key=lambda f: f.relative_to(root).as_posix()):
        if p.is_symlink():
            raise ValueError('Unexpected symlink: ' + str(p))
        if p.is_file():
            name = p.relative_to(root).as_posix()
            if name.casefold() in names:
                raise ValueError('Case-colliding payload path: ' + name)
            names.add(name.casefold())
            rows.append([name, p.stat().st_size, sha(p)])
    return rows

def digest(rows):
    return hashlib.sha256(json.dumps(rows, ensure_ascii=True, separators=(',', ':')).encode('ascii')).hexdigest()

def compare(expected, installed):
    before = {r[0]: r[1:] for r in expected}
    after = {r[0]: r[1:] for r in installed}
    missing = sorted(before.keys() - after.keys())
    changed = sorted(k for k in before.keys() & after.keys() if before[k] != after[k])
    extra = sorted(k for k in after.keys() - before.keys() if not re.fullmatch(r'unins\d{3}\.(?:exe|dat|msg)', k, re.I))
    if missing or changed or extra:
        raise ValueError(f'Installed payload mismatch: missing={missing}, changed={changed}, unexpected={extra}')

def main():
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['baseline', 'installed'])
    p.add_argument('root', type=Path)
    p.add_argument('ledger', type=Path)
    a = p.parse_args()
    rows = manifest(a.root)
    if a.mode == 'baseline':
        if digest(rows) != EXPECTED or len(rows) != 643:
            raise ValueError('Not the verified Windows payload')
        if (a.root/'Source-Revision.txt').read_text().strip() != SOURCE:
            raise ValueError('Wrong producer revision')
        a.ledger.write_text(json.dumps(rows, indent=2), encoding='utf-8')
    else:
        before = json.loads(a.ledger.read_text(encoding='utf-8'))
        if digest(before) != EXPECTED:
            raise ValueError('Baseline ledger changed')
        compare(before, rows)
    print(f'{a.mode}: {len(rows)} files, manifest {digest(rows)}')

if __name__ == '__main__':
    main()
