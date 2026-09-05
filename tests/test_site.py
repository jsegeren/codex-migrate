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
    def test_indexed_pages_have_canonical_urls(self):
        for name in ("privacy", "terms", "refunds", "moving-to-a-new-mac", "backup-and-recovery"):
            self.assertIn('<link rel="canonical" href="https://migrate.segeren.com/' + name + '">',
                          (SITE / (name + ".html")).read_text())

    def test_closing_actions_can_wrap_when_text_is_enlarged(self):
        styles = (SITE / "styles.css").read_text()
        closing = styles.split("\n.closing-inner {", 1)[1].split("}", 1)[0]
        actions = styles.split("\n.closing .actions {", 1)[1].split("}", 1)[0]
        self.assertIn("flex-wrap: wrap", closing)
        self.assertIn("max-width: 100%", actions)
        self.assertNotIn("flex: 0 0 auto", actions)

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
                    if not local_path or local_path == "/":
                        continue
                    target = SITE / local_path.removeprefix("/")
                    if target.suffix == "":
                        target = target.with_suffix(".html")
                    self.assertTrue(target.exists(), f"{page.name}: missing {href}")

    def test_real_dashboard_screenshots_are_labeled_as_sample_data(self):
        for page, asset in (("index.html", "dashboard-transfer.png"),
                            ("backup-and-recovery.html", "dashboard-backup-blocked.png")):
            with self.subTest(page=page):
                source = (SITE / page).read_text()
                self.assertIn('src="/assets/' + asset + '"', source)
                self.assertIn('loading="lazy"', source)
                self.assertIn("sample data", source.lower())
                self.assertIn("View full size", source)
                self.assertTrue((SITE / "assets" / asset).is_file())
                stem = asset.removesuffix(".png")
                self.assertIn(f'srcset="/assets/{stem}-720.avif 720w, /assets/{stem}-1120.avif 1120w"', source)
                self.assertTrue((SITE / "assets" / f"{stem}-720.avif").is_file())
                self.assertTrue((SITE / "assets" / f"{stem}-1120.avif").is_file())

    def test_checkout_closed_until_downloadable_edition_ready(self):
        text = " ".join(self.parse("index.html").text).lower()
        self.assertIn("no pre-orders", text)
        self.assertIn("not on sale yet", text)
        self.assertIn("$50", text)
        self.assertIn("no subscription", text)
        self.assertIn("free cli", text)

    def test_transfer_copy_explains_network_choices_and_cable_limit(self):
        text = " ".join(self.parse("index.html").text)
        self.assertIn("Wi-Fi or a compatible USB-C/Thunderbolt network connection", text)
        self.assertIn("Both use secure SSH", text)
        self.assertIn("USB-C cables vary in capability and speed", text)

    def test_windows_faq_does_not_imply_current_support(self):
        text = " ".join(self.parse("index.html").text)
        self.assertIn("Does it work on Windows?", text)
        self.assertIn("Mac-to-Mac migration only, including the open-source CLI", text)
        self.assertIn("Windows and cross-platform transfers are not supported today", text)

    def test_founder_cross_promotion_is_separate_from_launch_signup(self):
        source = (SITE / "index.html").read_text()
        note = source.split('<aside class="founder-note"', 1)[1].split('</aside>', 1)[0]
        self.assertIn('href="https://you.one/"', note)
        self.assertIn("I’m building You.one, with Ava at its heart", note)
        self.assertIn("Meet Ava at You.one", note)
        form = source.split('<form ', 1)[1].split('</form>', 1)[0]
        self.assertNotIn("you.one", form.lower())
        self.assertLess(source.index('</form>'), source.index('<aside class="founder-note"'))

    def test_codex_icon_is_a_separate_attributed_product_reference(self):
        source = (SITE / "index.html").read_text()
        self.assertIn('class="product-reference"', source)
        self.assertIn('alt="Codex product icon"', source)
        self.assertIn('>For Codex</a>', source)
        self.assertIn('Not affiliated with or endorsed by OpenAI', source)
        self.assertIn('href="/assets/mark.svg"', source)
        self.assertTrue((SITE / "assets/codex-product-dark.png").is_file())
        for size in (80, 288, 560):
            self.assertTrue((SITE / f"assets/codex-product-dark-{size}.png").is_file())
            self.assertTrue((SITE / f"assets/codex-product-dark-{size}.avif").is_file())
        self.assertIn("not licensed under", (ROOT / "THIRD_PARTY_NOTICES.md").read_text())

    def test_purple_theme_and_upright_headline(self):
        source = (SITE / "index.html").read_text()
        styles = (SITE / "styles.css").read_text()
        self.assertNotIn("<em>", source)
        self.assertNotIn("font-style: italic", styles)
        self.assertIn("--purple: #6042a6", styles)
        self.assertNotIn("var(--green", styles)

    def test_product_reference_is_prominent_in_hero_and_separate_in_header(self):
        source = (SITE / "index.html").read_text()
        header = source.split('<header class="site-header">', 1)[1].split('</header>', 1)[0]
        self.assertIn('class="header-compatibility"', header)
        self.assertIn('For Codex — independent migration tool', header)
        self.assertIn('>For Codex</span>', header)
        self.assertIn('width="280" height="280" fetchpriority="high" decoding="async" alt="Codex product icon"', source)
        self.assertIn('srcset="/assets/codex-product-dark-288.png 288w, /assets/codex-product-dark-560.png 560w"', source)
        self.assertIn('srcset="/assets/codex-product-dark-288.avif 288w, /assets/codex-product-dark-560.avif 560w"', source)
        self.assertIn('sizes="(max-width: 760px) 144px, (max-width: 980px) 160px, 280px"', source)
        self.assertIn('srcset="/assets/codex-product-dark-80.avif" type="image/avif"', header)
        self.assertIn('src="/assets/codex-product-dark-80.png" width="40" height="40"', header)
        heading_row = source.split('<div class="hero-heading">', 1)[1].split('</div>', 1)[0]
        self.assertIn('<h1>Keep the work.', heading_row)
        self.assertIn('class="hero-inline-icon"', heading_row)
        self.assertNotIn('class="terminal-card"', source)

    def test_hero_copy_gap_is_not_inflated_by_taller_icon(self):
        styles = (SITE / "styles.css").read_text()
        layout = styles.split("\n.hero-copy {", 1)[1].split("}", 1)[0]
        heading = styles.split("\n.hero-heading {", 1)[1].split("}", 1)[0]
        title = styles.split("\n.hero-heading h1 {", 1)[1].split("}", 1)[0]
        icon = styles.split("\n.hero-inline-icon {", 1)[1].split("}", 1)[0]
        self.assertIn("display: block", layout)
        self.assertIn("display: grid", heading)
        self.assertIn("minmax(0, 560px) 280px", heading)
        self.assertIn("grid-row: 1", icon)
        self.assertIn("align-self: start", icon)
        self.assertNotIn("align-items: flex-end", styles)
        self.assertIn("margin-bottom: 16px", title)

    def test_website_analytics_is_explicitly_opt_in_and_separate_from_app(self):
        analytics = (SITE / "analytics.js").read_text()
        privacy = " ".join(self.parse("privacy.html").text)
        home = " ".join(self.parse("index.html").text)
        vercel = (ROOT / "vercel.json").read_text()
        for page in SITE.glob("*.html"):
            with self.subTest(page=page.name):
                self.assertIn('src="/analytics.js?v=20260904"', page.read_text())
        self.assertIn('const GRANTED = "granted"', analytics)
        self.assertIn('const PUBLIC_HOSTS = new Set(["migrate.segeren.com", "codex-migrate.vercel.app"]);', analytics)
        self.assertIn('!PUBLIC_HOSTS.has(window.location.hostname)', analytics)
        self.assertIn('script.src = `https://www.googletagmanager.com/gtag/js?id=', analytics)
        self.assertIn("Accept analytics", analytics)
        self.assertIn("No thanks", analytics)
        self.assertIn("clearAnalyticsCookies();", analytics)
        self.assertIn("if (tagLoaded) window.location.reload();", analytics)
        self.assertIn('cookie_domain: "none"', analytics)
        self.assertIn('cookie_prefix: "cm"', analytics)
        self.assertIn('cookie_expires: 60 * 60 * 24 * 425', analytics)
        self.assertIn('cookie_update: true', analytics)
        self.assertIn("No app telemetry", home)
        self.assertIn("The Google tag is not loaded until you select “Accept analytics.”", privacy)
        self.assertIn("It does not receive your name, email address, Codex conversations", privacy)
        self.assertIn("Google Signals may add aggregate", privacy)
        self.assertIn("https://www.googletagmanager.com", vercel)

    def test_modern_headings_and_black_text_on_light_surfaces(self):
        styles = (SITE / "styles.css").read_text()
        self.assertNotIn("Georgia", styles)
        self.assertNotIn("Times New Roman", styles)
        self.assertIn("--ink: #000;", styles)
        self.assertIn("--muted: #000;", styles)
        headline = styles.split("\nh1 {", 1)[1].split("}", 1)[0]
        self.assertIn("font-weight: 800", headline)
        self.assertIn(".legal p, .legal li { color: var(--ink); }", styles)

    def test_body_and_hero_copy_have_readable_weight(self):
        styles = (SITE / "styles.css").read_text()
        body = styles.split("\nbody {", 1)[1].split("}", 1)[0]
        lede = styles.split("\n.lede {", 1)[1].split("}", 1)[0]
        self.assertIn("font-size: 17px", body)
        self.assertIn("font-weight: 500", body)
        self.assertIn("font-weight: 600", lede)

    def test_launch_interest_uses_consented_form_and_separate_early_build_email(self):
        page = self.parse("index.html")
        emails = [href for href in page.hrefs if href.startswith("mailto:joshua@segeren.com?")]
        self.assertEqual(len(emails), 1)
        text = " ".join(page.text)
        self.assertIn("Your request goes to Josh’s inbox via SendGrid", text)
        self.assertIn("case by case", text)
        self.assertIn("unnotarized test builds", text)
        source = (SITE / "index.html").read_text()
        self.assertIn('action="/api/signup" method="post"', source)
        self.assertIn('type="checkbox" value="yes" required', source)
        self.assertIn('type="email"', source)

    def test_guides_are_discoverable_and_do_not_promise_unsafe_backup_bypass(self):
        home = (SITE / "index.html").read_text()
        sitemap = (SITE / "sitemap.xml").read_text()
        for path in ("moving-to-a-new-mac", "backup-and-recovery"):
            self.assertIn('href="/' + path + '"', home)
            self.assertIn("https://migrate.segeren.com/" + path, sitemap)
        self.assertIn("no skip-backup switch", (SITE / "backup-and-recovery.html").read_text())

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
