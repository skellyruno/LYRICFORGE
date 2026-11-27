"""Restore welcome branding in a disposable Creator/editorial candidate."""
from pathlib import Path
import argparse
import hashlib
import re
import zipfile

ASSET = 'LYRICFORGE-main/static/skelly-radar.png'
ARCHIVE_SHA = '4ba17dd5cdca24a040a05453706cda1881934d0d1e8704080e292e398ace6462'
LINK = '<link rel="stylesheet" href="/static/welcome-brand.css" />'
ART = '<aside class="welcome-hub-art" aria-hidden="true"><div class="motion-radar"><img src="/static/skelly-radar.png" width="531" height="505" alt="" /></div><span class="welcome-hub-label">SKELLY / CREATIVE STUDIO</span></aside>'
DECOR = '<div class="welcome-decor">SM / CREATIVE TOOLS — 001</div>'

def transform(html):
    if html.count('id="welcome"') != 1 or html.count('<em>YOUR WORDS.</em>') != 1:
        raise ValueError('Unexpected welcome screen')
    if 'class="welcome-hub-art"' not in html:
        if html.count(DECOR) != 1:
            raise ValueError('Unexpected Creator art anchor')
        html = html.replace(DECOR, ART)
    if LINK not in html:
        if html.count('</head>') != 1:
            raise ValueError('Unexpected stylesheet anchor')
        html = html.replace('</head>', '  ' + LINK + '\n</head>')
    return html

def apply(candidate, archive):
    static = Path(candidate) / 'static'
    if hashlib.sha256(Path(archive).read_bytes()).hexdigest() != ARCHIVE_SHA:
        raise ValueError('Wrong original editorial archive')
    with zipfile.ZipFile(archive) as z:
        radar = z.read(ASSET)
        if radar[:8] != b'\x89PNG\r\n\x1a\n':
            raise ValueError('Invalid original radar PNG')
    index = static / 'index.html'
    html = transform(index.read_text(encoding='utf-8'))
    css = Path(__file__).with_name('welcome-brand.css').read_bytes()
    asset = static / 'skelly-radar.png'
    if asset.exists() and asset.read_bytes() != radar:
        raise ValueError('Radar asset differs; preserve and review')
    asset.write_bytes(radar)
    (static / 'welcome-brand.css').write_bytes(css)
    index.write_text(html, encoding='utf-8')
    print('Welcome identity restored; original radar SHA256:', hashlib.sha256(radar).hexdigest())

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('candidate', type=Path)
    p.add_argument('archive', type=Path)
    a = p.parse_args()
    apply(a.candidate, a.archive)
