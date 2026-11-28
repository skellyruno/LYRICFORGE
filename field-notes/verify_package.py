"""Verify preserved Field Notes release archives; never overwrite existing output."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile


def digest(stream):
    h = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        h.update(block)
    return h.hexdigest()


def verify(path, expected, members=None, destination=None):
    path = Path(path)
    with path.open('rb') as stream:
        if path.stat().st_size != expected['bytes'] or digest(stream) != expected['sha256']:
            raise ValueError(f'Archive size or SHA-256 mismatch: {path.name}')
    with zipfile.ZipFile(path) as z:
        rows = [i for i in z.infolist() if not i.is_dir()]
        names = [i.filename for i in rows]
        if len(rows) != expected['members'] or len(set(names)) != len(names):
            raise ValueError('Incorrect member count or duplicate paths')
        if members is not None and set(names) != set(members):
            raise ValueError('Unexpected website member list')
        for row in rows:
            name = row.filename
            p = PurePosixPath(name)
            if p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name or not p.parts or stat.S_ISLNK(row.external_attr >> 16):
                raise ValueError(f'Unsafe archive member: {name}')
            with z.open(row) as stream:
                checksum = digest(stream)
            if members is not None and (row.file_size != members[name]['bytes'] or checksum != members[name]['sha256']):
                raise ValueError(f'Member size or SHA-256 mismatch: {name}')
        if destination is not None:
            destination = Path(destination)
            if destination.exists() or destination.is_symlink():
                raise FileExistsError(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temp = Path(tempfile.mkdtemp(prefix='.field-notes-', dir=destination.parent))
            try:
                for row in rows:
                    target = temp.joinpath(*PurePosixPath(row.filename).parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(row) as src, target.open('xb') as dst:
                        shutil.copyfileobj(src, dst)
                if destination.exists() or destination.is_symlink():
                    raise FileExistsError(destination)
                temp.rename(destination)
            finally:
                if temp.exists():
                    shutil.rmtree(temp)
    return {'archive': path.name, 'members': len(rows), 'sha256': expected['sha256']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive_dir', type=Path)
    parser.add_argument('--stage-website', type=Path)
    args = parser.parse_args()
    manifest = json.loads(Path(__file__).with_name('manifest.json').read_text(encoding='utf-8'))
    reports = []
    for name, expected in manifest['archives'].items():
        website = 'Screening-Package' in name
        reports.append(verify(args.archive_dir / name, expected, manifest['website_members'] if website else None))
    if args.stage_website:
        name = 'SkellyMotion-Field-Notes-Screening-Package.zip'
        verify(args.archive_dir / name, manifest['archives'][name], manifest['website_members'], args.stage_website)
    print(json.dumps(reports, indent=2))


if __name__ == '__main__':
    main()
