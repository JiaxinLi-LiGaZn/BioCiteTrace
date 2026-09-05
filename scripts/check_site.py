"""Check the single-page reading paths, static assets and figure provenance."""

from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'site'


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()
        self.h1_count = 0
        self.pagination = []

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if 'id' in attrs:
            assert attrs['id'] not in self.ids, 'Duplicate HTML ID'
            self.ids.add(attrs['id'])
        if tag == 'h1':
            self.h1_count += 1
        for key in ('href', 'src'):
            if key in attrs:
                self.links.append(attrs[key])
        if attrs.get('rel') in ('next', 'prev'):
            self.pagination.append(attrs['rel'])
        if tag == 'meta' and attrs.get('http-equiv', '').lower() == 'refresh':
            self.links.append(attrs['content'].split('url=', 1)[1])
        if tag == 'img':
            assert attrs.get('alt'), 'Figure needs alternative text'
            assert attrs.get('width') and attrs.get('height'), 'Reserve figure dimensions'


def main():
    pages = {}
    for path in SITE.glob('*.html'):
        page = Page()
        page.feed(path.read_text())
        assert not page.pagination, f'{path.name}: outdated pagination'
        pages[path.resolve()] = page
    homepage = pages[(SITE / 'index.html').resolve()]
    assert homepage.h1_count == 1, 'Expected one main heading'
    assert {'explore', 'story', 'workflow', 'findings'} <= homepage.ids, 'Missing reading destination'
    for path, page in pages.items():
        for link in page.links:
            target = urlsplit(link)
            if target.scheme or target.netloc:
                continue
            resolved = (path.parent / unquote(target.path)).resolve() if target.path else path
            assert resolved.is_relative_to(SITE), f'{path.name}: link escapes published folder'
            assert resolved.is_file(), f'{path.name}: missing {link}'
            if target.fragment and resolved in pages:
                assert target.fragment in pages[resolved].ids, f'{path.name}: missing anchor {link}'
    css = SITE / 'assets/story.css'
    for url in re.findall(r"url\(['\"]?([^)'\"]+)['\"]?\)", css.read_text()):
        asset = (css.parent / url).resolve()
        assert asset.is_relative_to(SITE) and asset.is_file(), f'Missing CSS asset: {url}'
        if asset.suffix == '.woff2':
            assert asset.read_bytes()[:4] == b'wOF2', f'Invalid font file: {url}'
    assert (SITE / 'assets/fonts/OFL.txt').is_file(), 'Missing font license'
    provenance = json.loads((ROOT / 'results/provenance.json').read_text())
    for key in ('full_figure', 'panel_c'):
        entry = provenance[key]
        file = ROOT / 'results' / entry['path']
        assert sha256(file.read_bytes()).hexdigest() == entry['sha256'], f'Changed source figure: {key}'
    print('Single-page links, redirects, font assets, image text and figure hashes verified.')


if __name__ == '__main__':
    main()
