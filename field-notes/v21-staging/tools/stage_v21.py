"""Stage the exact V21 patch over a disposable, pinned Creator proposal only."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

BASE = 'b37a857e4be4cf5dc7f13337452fdbdcb033e29b'
PATCH_SHA = 'f3f4d6ca7294aa55578c216c814966f31533cc0250f3b912a1ec3479e06c5011'
FILES = frozenset({'studio_voice.py', 'studio_creator.py', 'studio_director_intelligence.py',
                   'studio_visual_sources.py', 'server.py', 'tests/test_v21_reconciled_components.py'})
UNRESOLVED = frozenset({'server.py', 'static/autoclip.js', 'static/index.html', 'studio_cinematic.py',
                        'studio_cli.py', 'studio_director.py', 'tests/editor_smoke.mjs'})
WORKFLOWS = frozenset({'.github/workflows/build-minimal-ffmpeg.yml', '.github/workflows/test.yml',
                      '.github/workflows/windows-release.yml'})


def sha(data):
    return hashlib.sha256(data).hexdigest()


def stage(root, patch, destination):
    root, patch, destination = map(Path, (root, patch, destination))
    source = root / 'proposal'
    if destination.exists() or destination.is_relative_to(root) or root.is_relative_to(destination):
        raise ValueError('Destination must be a new separate directory')
    if (root / 'creator-revision.txt').read_text().strip() != BASE:
        raise ValueError('Wrong Creator base')
    if sha(patch.read_bytes()) != PATCH_SHA:
        raise ValueError('Wrong V21 archive hash')
    with zipfile.ZipFile(patch) as z:
        names = z.namelist()
        expected = {'proposal/' + x for x in FILES} | {'report.json', 'verification/tests.log'}
        if len(names) != len(expected) or set(names) != expected:
            raise ValueError('Unexpected archive members')
        report = json.loads(z.read('report.json'))
        if (report['base_creator_commit'] != BASE or report['editorial_archive'] != 'V20'
                or set(report['files']) != FILES or set(report['remaining_conflicts']) != UNRESOLVED
                or set(report['workflow_review']) != WORKFLOWS):
            raise ValueError('V21 report does not match pinned scope')
        updates = {name: z.read('proposal/' + name) for name in FILES}
        if any(sha(data) != report['files'][name] for name, data in updates.items()):
            raise ValueError('Patch member hash mismatch')
    ledger = json.loads((root / 'report.json').read_text())
    paths = {row['path']: row for row in ledger['paths']}
    if not (UNRESOLVED | WORKFLOWS | (FILES - {'tests/test_v21_reconciled_components.py'})) <= paths.keys():
        raise ValueError('Incomplete Creator proposal ledger')
    for name, row in paths.items():
        p = source / name
        if not p.is_file() or p.is_symlink() or not p.resolve().is_relative_to(source.resolve()) or sha(p.read_bytes()) != row['proposal_sha256']:
            raise ValueError('Proposal drift: ' + name)
    actual = {p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()}
    if actual != set(paths) or any(p.is_symlink() for p in source.rglob('*')):
        raise ValueError('Unexpected proposal entries')
    if 'studio_theme.py' not in paths:
        raise ValueError('Creator-only theme dependency missing')
    shutil.copytree(source, destination)
    for name, data in updates.items():
        p = destination / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    for name in (UNRESOLVED | WORKFLOWS) - FILES:
        if sha((destination / name).read_bytes()) != paths[name]['proposal_sha256']:
            raise RuntimeError('Unresolved file was overwritten: ' + name)
    return {'creator_base': BASE, 'patch_sha256': PATCH_SHA, 'applied_files': sorted(FILES),
            'remaining_conflicts': sorted(UNRESOLVED), 'workflow_review': sorted(WORKFLOWS),
            'status': 'test-only; server partial; not a release',
            'file_sha256': {p.relative_to(destination).as_posix(): sha(p.read_bytes())
                            for p in sorted(destination.rglob('*')) if p.is_file()}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reconciliation', type=Path)
    parser.add_argument('patch', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('evidence', type=Path)
    args = parser.parse_args()
    evidence = stage(args.reconciliation.resolve(), args.patch.resolve(), args.destination.resolve())
    args.evidence.write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print('Staged exact V21 patch; seven unresolved files and three workflow differences remain.')
