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

    def test_checkout_closed_until_downloadable_edition_ready(self):
        text = " ".join(self.parse("index.html").text).lower()
        self.assertIn("no pre-orders", text)
        self.assertIn("not on sale yet", text)
        self.assertIn("$50", text)
        self.assertIn("no subscription", text)
        self.assertIn("free cli", text)

    def test_codex_icon_is_a_separate_attributed_product_reference(self):
        source = (SITE / "index.html").read_text()
        self.assertIn('class="product-reference"', source)
        self.assertIn('alt="Codex product icon"', source)
        self.assertIn('>For Codex</a>', source)
        self.assertIn('Not affiliated with or endorsed by OpenAI', source)
        self.assertIn('href="/assets/mark.svg"', source)
        self.assertTrue((SITE / "assets/codex-product.png").is_file())
        self.assertIn("not licensed under", (ROOT / "THIRD_PARTY_NOTICES.md").read_text())

    def test_purple_theme_and_upright_headline(self):
        source = (SITE / "index.html").read_text()
        styles = (SITE / "styles.css").read_text()
        self.assertNotIn("<em>", source)
        self.assertNotIn("font-style: italic", styles)
        self.assertIn("--purple: #6042a6", styles)
        self.assertNotIn("var(--green", styles)

    def test_launch_interest_is_an_honest_email_handoff(self):
        page = self.parse("index.html")
        emails = [href for href in page.hrefs if href.startswith("mailto:joshua@segeren.com?")]
        self.assertEqual(len(emails), 2)
        text = " ".join(page.text)
        self.assertIn("clicking alone does not sign you up", text)
        self.assertIn("case by case", text)
        self.assertIn("unnotarized test builds", text)
        self.assertNotIn("<form", (SITE / "index.html").read_text())

    def test_legal_pages_cover_purchase_basics(self):
        terms = " ".join(self.parse("terms.html").text).lower()
        refunds = " ".join(self.parse("refunds.html").text).lower()
        privacy = " ".join(self.parse("privacy.html").text).lower()
        self.assertIn("no pre-orders", terms)
        self.assertIn("no specific release date", terms)
        self.assertIn("best-effort", terms)
        self.assertIn("no response time, fix, resolution deadline", terms)
        self.assertIn("30-day refund", refunds)
        self.assertIn("stripe", privacy)
        self.assertIn("do not sell personal data", privacy)


if __name__ == "__main__":
    unittest.main()
