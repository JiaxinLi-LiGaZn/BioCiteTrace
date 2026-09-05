"""Check static story links, chapter navigation and cited figure provenance."""

from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
CHAPTERS = ("index.html", "story.html", "workflow.html", "findings.html", "explore.html")


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()
        self.h1_count = 0
        self.current = []
        self.navigation = {}

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if "id" in attrs:
            assert attrs["id"] not in self.ids, "Duplicate HTML ID"
            self.ids.add(attrs["id"])
        if tag == "h1":
            self.h1_count += 1
        for key in ("href", "src"):
            if key in attrs:
                self.links.append(attrs[key])
        if attrs.get("aria-current") == "page":
            self.current.append(attrs.get("href"))
        if attrs.get("rel") in ("next", "prev"):
            self.navigation[attrs["rel"]] = attrs["href"]
        if tag == "img":
            assert attrs.get("alt"), "Figure needs alternative text"
            assert attrs.get("width") and attrs.get("height"), "Reserve figure dimensions"


def main():
    for index, name in enumerate(CHAPTERS):
        path = SITE / name
        page = Page()
        page.feed(path.read_text())
        assert page.h1_count == 1, f"{name}: expected one main heading"
        assert page.current == [name], f"{name}: incorrect current chapter"
        expected = {}
        if index:
            expected["prev"] = CHAPTERS[index - 1]
        if index + 1 < len(CHAPTERS):
            expected["next"] = CHAPTERS[index + 1]
        assert page.navigation == expected, f"{name}: broken reading order"
        for link in page.links:
            target = urlsplit(link)
            if target.scheme or target.netloc:
                continue
            resolved = (path.parent / unquote(target.path)).resolve() if target.path else path
            assert resolved.is_relative_to(SITE), f"{name}: link escapes published folder"
            assert resolved.is_file(), f"{name}: missing {link}"
            if not target.path and target.fragment:
                assert target.fragment in page.ids, f"{name}: missing anchor {link}"
    provenance = json.loads((ROOT / "results/provenance.json").read_text())
    for key in ("full_figure", "panel_c"):
        entry = provenance[key]
        file = ROOT / "results" / entry["path"]
        assert sha256(file.read_bytes()).hexdigest() == entry["sha256"], f"Changed source figure: {key}"
    print("Five chapters: links, reading order, headings, image text and figure hashes verified.")


if __name__ == "__main__":
    main()
