from html.parser import HTMLParser
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


class _DocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs = []
        self.has_h1 = False
        self.text = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "a" and attributes.get("href"):
            self.hrefs.append(attributes["href"])
        if tag == "h1":
            self.has_h1 = True

    def handle_data(self, data):
        self.text.append(data)


class SiteTests(unittest.TestCase):
    def parse(self, filename: str) -> _DocumentParser:
        parser = _DocumentParser()
        parser.feed((SITE / filename).read_text(encoding="utf-8"))
        return parser

    def test_every_page_has_title_h1_and_no_broken_local_link(self):
        for page in SITE.glob("*.html"):
            with self.subTest(page=page.name):
                source = page.read_text(encoding="utf-8")
                parser = self.parse(page.name)
                self.assertIn("<title>", source)
                self.assertTrue(parser.has_h1)
                for href in parser.hrefs:
                    if not href.startswith("/") or href == "/":
                        continue
                    local_path = href.split("#", 1)[0].split("?", 1)[0]
                    if not local_path:
                        continue
                    target = SITE / local_path.removeprefix("/")
                    if target.suffix == "":
                        target = target.with_suffix(".html")
                    self.assertTrue(target.exists(), f"{page.name}: missing {href}")

    def test_paid_offer_is_unambiguously_a_preorder(self):
        text = " ".join(self.parse("index.html").text).lower()
        self.assertIn("this is a pre-order", text)
        self.assertIn("not available today", text)
        self.assertIn("$49", text)
        self.assertIn("no subscription", text)
        self.assertIn("free cli", text)

    def test_legal_pages_cover_purchase_basics(self):
        terms = " ".join(self.parse("terms.html").text).lower()
        refunds = " ".join(self.parse("refunds.html").text).lower()
        privacy = " ".join(self.parse("privacy.html").text).lower()
        self.assertIn("pre-order", terms)
        self.assertIn("no specific release date", terms)
        self.assertIn("30 days", refunds)
        self.assertIn("stripe", privacy)
        self.assertIn("do not sell personal data", privacy)


if __name__ == "__main__":
    unittest.main()
