"""Check the single-page reading paths, static assets and figure provenance."""

# Standard-library parsers and hashing utilities validate local site structure and files.
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'site'


class Page(HTMLParser):
    """Collect links, IDs, headings and image metadata from one HTML page."""

    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()
        self.h1_count = 0
        self.pagination = []

    def handle_starttag(self, tag, attributes):
        """Record relevant attributes from one parsed HTML start tag."""

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


def png_dimensions(path):
    """Return ``(width, height)`` in pixels for a PNG at ``path``."""

    header = path.read_bytes()[:24]
    assert header[:8] == b'\x89PNG\r\n\x1a\n', f'Invalid PNG: {path}'
    return int.from_bytes(header[16:20], 'big'), int.from_bytes(header[20:24], 'big')


def main():
    """Validate the published site, its internal links and its recorded artifacts."""

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
    provenance = json.loads((ROOT / 'results/provenance.json').read_text())
    for group in ('figure_files', 'data_files'):
        for key, entry in provenance[group].items():
            file = ROOT / entry['path']
            assert file.is_file(), f'Missing recorded artifact: {group}.{key}'
            digest = sha256(file.read_bytes()).hexdigest()
            assert digest == entry['sha256'], f'Changed recorded artifact: {group}.{key}'
    high_resolution = provenance['figure_files']['high_resolution_png']
    actual_pixels = png_dimensions(ROOT / high_resolution['path'])
    assert list(actual_pixels) == high_resolution['pixels'], 'High-resolution PNG dimensions changed'
    homepage_text = (SITE / 'index.html').read_text()
    assert 'pending' not in homepage_text.lower(), 'Website still reports validation as pending'
    assert 'Macro average' not in homepage_text, 'Website still displays removed macro averages'
    print('Single-page links, redirects, image text, final-result language and artifact hashes verified.')


if __name__ == '__main__':
    main()
