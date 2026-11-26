"""Optional public-domain / CC0 illustrative visuals for the local scene director.

Only short text queries are sent, never audio, files or full transcripts. Unknown
licenses, redirects, oversized media and arbitrary hosts are rejected.
"""
from __future__ import annotations

import hashlib
import html
import io
import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from uuid import uuid4

from PIL import Image, ImageOps
import studio_performance as perf

API = 'https://commons.wikimedia.org/w/api.php'
AGENT = 'SkellyMotion/1.0 (https://github.com/skellyruno/LYRICFORGE; optional image sourcing)'
LICENSES = {'public domain', 'cc0', 'cc0 1.0', 'cc zero'}
MAX_IMAGE = 8 * 1024 * 1024
MAX_SEARCHES = 6
INDEX_LOCK = threading.RLock()
STOP = set('the a an am and or but for with from this that these those there here when where what why how who which whose your you our we they their them she her him his he was were are is be been being it its not no yes can could would should will shall have has had do did does just really very more most some then than into onto over under about like now also because so my me i to of in on as at by if out up down make get see know want think going gonna im dont changes change compare result use used using show shows showing work works working explains explain demonstrating demonstrated tells tell says said look looks looking'.split())


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def trusted_url(url, host):
    try:
        p = urlsplit(url)
        return p.scheme == 'https' and p.netloc == host and not p.fragment and not p.username and not p.password
    except (TypeError, ValueError):
        return False


def read_url(url, host, cap):
    if not trusted_url(url, host):
        raise ValueError('Untrusted image source')
    with build_opener(NoRedirect()).open(Request(url, headers={'User-Agent': AGENT}), timeout=5) as response:
        if not trusted_url(response.geturl(), host):
            raise ValueError('Untrusted response URL')
        size = response.headers.get('Content-Length')
        if size and int(size) > cap:
            raise ValueError('Response too large')
        end = time.monotonic() + 10
        data = bytearray()
        while True:
            if time.monotonic() > end:
                raise TimeoutError('Image source timed out')
            chunk = response.read(min(65536, cap + 1 - len(data)))
            if not chunk:
                return bytes(data)
            data.extend(chunk)
            if len(data) > cap:
                raise ValueError('Response too large')


def clean(value, limit=300):
    return ' '.join(html.unescape(re.sub(r'<[^>]*>', ' ', str(value or ''))).split())[:limit]


def keywords(text):
    return list(dict.fromkeys(w for w in re.findall(r'[^\W\d_]{3,}', text.casefold()) if w not in STOP))


def query_for(scene):
    text = ' '.join(str(c.get('text', '')) for c in scene.get('captions', []))
    words = keywords(text)
    # A few keywords, not a complete line/verse or any media payload.
    return ' '.join(words[:3])[:80] if len(words) >= 2 else ''


def candidates(payload, query):
    pages = payload.get('query', {}).get('pages', [])
    if not isinstance(pages, list):
        return []
    found = []
    wanted = set(keywords(query))
    for page in pages:
        if not isinstance(page, dict):
            continue
        try:
            info = page['imageinfo'][0]; meta = info.get('extmetadata', {})
            def field(key): return clean(meta.get(key, {}).get('value'))
            license_name = field('LicenseShortName')
            if (license_name.casefold() not in LICENSES or field('Restrictions') or
                    field('AttributionRequired').casefold() not in ('', 'false', '0')):
                continue
            url = info.get('thumburl', '')
            source = info.get('descriptionurl', '')
            if not trusted_url(url, 'upload.wikimedia.org') or not trusted_url(source, 'commons.wikimedia.org'):
                continue
            if info.get('mime') not in ('image/jpeg', 'image/png'):
                continue
            w, h = int(info['thumbwidth']), int(info['thumbheight'])
            if w < 480 or h < 300 or w*h > 12_000_000:
                continue
            title = clean(page['title'].removeprefix('File:'), 120)
            overlap = len(wanted & set(keywords(title + ' ' + field('ImageDescription'))))
            if overlap < min(2, len(wanted)):
                continue
            page_id = int(page['pageid'])
            if page_id <= 0:
                continue
            found.append({'id': page_id, 'url': url, 'title': title, 'source': {
                'provider': 'Wikimedia Commons', 'page': source, 'creator': field('Artist') or 'See source page',
                'license': license_name, 'license_url': ('https://creativecommons.org/publicdomain/zero/1.0/' if license_name.casefold() != 'public domain' else 'https://commons.wikimedia.org/wiki/Commons:Licensing'),
                'query': query, 'use': 'illustrative; verify subject and rights before publishing'},
                'score': (overlap, int(w>=h), min(w*h, 1280*720))})
        except (KeyError, TypeError, ValueError, AttributeError, IndexError):
            continue
    return sorted(found, key=lambda a:a['score'], reverse=True)


def search(query):
    args = {'action':'query','generator':'search','gsrsearch':query,'gsrnamespace':6,'gsrlimit':12,
            'prop':'imageinfo','iiprop':'url|mime|extmetadata','iiurlwidth':1280,'format':'json','formatversion':2}
    data = read_url(API+'?'+urlencode(args),'commons.wikimedia.org',2*1024*1024)
    return candidates(json.loads(data),query)


def reusable_picture(target, meta):
    """Never revive disabled entries or trust incomplete cached provenance."""
    if not target.is_file() or target.is_symlink() or not isinstance(meta, dict) or meta.get('disabled'):
        return False
    source = meta.get('source')
    return (isinstance(source, dict) and isinstance(meta.get('name'), str)
            and source.get('provider') == 'Wikimedia Commons'
            and str(source.get('license', '')).casefold() in LICENSES
            and trusted_url(source.get('page', ''), 'commons.wikimedia.org'))


def import_picture(folder, item):
    key = hashlib.sha256(('commons:'+str(item['id'])).encode()).hexdigest()[:32]+'.jpg'
    target = folder/key
    if folder.is_symlink() or target.is_symlink():
        raise ValueError('Linked image path')
    with INDEX_LOCK:
        index = perf.read_cache(folder/'index.json')
        if reusable_picture(target, index.get(key)):
            return key, index[key]
        if key in index or target.exists():
            raise ValueError('Existing image is disabled or has invalid provenance')
        if len(index)>=40:
            raise ValueError('Asset library full')
    raw = read_url(item['url'],'upload.wikimedia.org',MAX_IMAGE)
    with Image.open(io.BytesIO(raw)) as image:
        if image.format not in ('JPEG','PNG') or image.width*image.height > 12_000_000 or image.width < 480 or image.height < 300:
            raise ValueError('Unsupported or oversized image')
        tile = ImageOps.exif_transpose(image).convert('RGB')
        tile.thumbnail((1280,1280), Image.Resampling.LANCZOS)
    folder.mkdir(exist_ok=True)
    temp = folder/('.picture-'+uuid4().hex+'.tmp')
    try:
        tile.save(temp,format='JPEG',quality=90,optimize=True)
        with INDEX_LOCK:
            index=perf.read_cache(folder/'index.json')
            if reusable_picture(target, index.get(key)):
                return key,index[key]
            if len(index)>=40 or key in index or target.exists() or target.is_symlink():
                raise ValueError('Asset library full or image already exists')
            meta={'name':item['title'],'description':item['source']['query'],'source':item['source']}
            perf.publish_staged_file(temp,target)
            try:
                index[key]=meta
                perf.atomic_write_json(folder/'index.json',index)
            except Exception:
                target.unlink(missing_ok=True)
                raise
            return key,meta
    finally:
        temp.unlink(missing_ok=True)


def fill_missing(plan, folder: Path, allow_network=False, check_cancel=lambda:None, progress=lambda done,total:None):
    """Fill missing shots, preferring exact query cache. Network failures fall back to cards."""
    if folder.is_symlink():
        raise ValueError('Linked asset folder')
    pending=[s for s in plan['scenes'] if s['type'] in ('big_text','visualizer') and not s.get('asset')]
    searched={}; used=set(); fetched=0; reused=0; failed=0; count=0
    for i,scene in enumerate(pending):
        check_cancel()
        progress(i,len(pending))
        query=query_for(scene)
        if not query:
            continue
        match=None
        index=perf.read_cache(folder/'index.json')
        for key,meta in index.items():
            if not re.fullmatch(r'[a-f0-9]{32}\.jpg',key) or not isinstance(meta,dict):
                continue
            if reusable_picture(folder/key, meta) and meta['source'].get('query')==query:
                match=(key,meta);break
        if match:
            reused+=1
        elif allow_network and query not in searched and count<MAX_SEARCHES:
            count+=1
            try:
                options=search(query)
                check_cancel()
                for item in options[:2]:
                    if item['id'] in used:
                        continue
                    try:
                        match=import_picture(folder,item)
                        used.add(item['id']);fetched+=1;break
                    except (OSError,ValueError,Image.DecompressionBombError):
                        continue
            except (OSError,ValueError,TimeoutError,TypeError,AttributeError):
                failed+=1
            searched[query]=match
        elif query in searched:
            match=searched[query]
        check_cancel()
        if match:
            key,meta=match
            scene.update(type='broll',asset=key,asset_name=meta['name'],source=meta['source'],text='',camera='push' if i%2==0 else 'pull')
    plan['visual_sources']={'downloaded':fetched,'cached':reused,'queries':count,'remaining_cards':sum(s['type']=='big_text' for s in plan['scenes'])}
    if pending:
        plan['warnings']=[w for w in plan.get('warnings',[]) if not w.startswith('No visual assets supplied')]
    if plan['visual_sources']['remaining_cards']:
        plan.setdefault('warnings',[]).append('Missing or uncertain visuals use transcript cards.')
    if failed:
        plan.setdefault('warnings',[]).append('Some image searches were unavailable; local visuals were preserved.')
    return plan
