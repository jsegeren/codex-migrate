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
    def test_home_offer_and_migration_search_copy_are_current(self):
        home = (SITE / "index.html").read_text()
        self.assertIn("Signed Mac beta available · Free open-source CLI", home)
        self.assertIn("<h1>Change the Mac. <br>", home)
        self.assertNotIn("Mac builds by request", home)
        self.assertIn("How do I copy Codex to a different Mac?", home)
        self.assertIn("Can I access Codex from another machine without moving it?", home)
        guide = (SITE / "moving-to-a-new-mac.html").read_text()
        self.assertIn("Transfer or move Codex to a new Mac", guide)
        self.assertIn("<h1>Transfer Codex <br>to a new Mac.</h1>", guide)
        self.assertIn("Get the Mac beta — $50", guide)
        self.assertIn("Why signing in on the new Mac is not enough", guide)
        self.assertIn("New-Mac migration checklist", guide)
        missing = (SITE / "codex-history-missing-new-mac.html").read_text()
        self.assertIn("Codex history missing on a new Mac?", missing)
        self.assertIn("Codex history is missing. What now?", missing)
        self.assertIn("Do not blindly replace the new Mac’s Codex folder", missing)
        self.assertIn('href="/codex-history-missing-new-mac"', home)
        self.assertIn('href="/compare-codex-migration-tools"', home)
        self.assertIn('href="/access-codex-from-another-machine"', home)
        guide_actions = guide.split('<div class="actions">', 1)[1].split("</div>", 1)[0]
        self.assertLess(guide_actions.index("Get the Mac beta — $50"), guide_actions.index("Read the free CLI setup"))
        recovery = (SITE / "backup-and-recovery.html").read_text()
        recovery_actions = recovery.split('<div class="actions">', 1)[1].split("</div>", 1)[0]
        self.assertLess(recovery_actions.index("Get the Mac beta — $50"), recovery_actions.index("Explore the free source"))

    def test_openai_chatgpt_names_preserve_local_codex_scope(self):
        for page in ("index.html", "moving-to-a-new-mac.html", "codex-history-missing-new-mac.html"):
            source = (SITE / page).read_text()
            self.assertIn("OpenAI Codex", source)
            self.assertIn("ChatGPT desktop app", source)
            self.assertIn("ordinary ChatGPT cloud chats", source)
            self.assertIn("all ChatGPT modes", source)
        readme = (ROOT / "README.md").read_text()
        self.assertIn("Codex in the ChatGPT desktop app", readme)
        self.assertIn("does not transfer ordinary ChatGPT cloud chats", readme)

    def test_indexed_pages_have_canonical_urls(self):
        for name in ("privacy", "terms", "refunds", "moving-to-a-new-mac", "codex-history-missing-new-mac", "backup-and-recovery", "compare-codex-migration-tools", "access-codex-from-another-machine"):
            self.assertIn('<link rel="canonical" href="https://migrate.segeren.com/' + name + '">',
                          (SITE / (name + ".html")).read_text())
        self.assertIn('<link rel="canonical" href="https://migrate.segeren.com/ja/codex-new-mac">',
                      (SITE / "ja/codex-new-mac.html").read_text())

    def test_japanese_migration_guide_is_discoverable_and_preserves_safety_scope(self):
        english = (SITE / "moving-to-a-new-mac.html").read_text()
        japanese = (SITE / "ja/codex-new-mac.html").read_text()
        sitemap = (SITE / "sitemap.xml").read_text()
        self.assertIn('hreflang="ja" href="https://migrate.segeren.com/ja/codex-new-mac"', english)
        self.assertIn('hreflang="en" href="https://migrate.segeren.com/moving-to-a-new-mac"', japanese)
        self.assertIn('href="/ja/codex-new-mac"', english)
        self.assertIn('href="/moving-to-a-new-mac" lang="en">English</a>', japanese)
        self.assertIn("https://migrate.segeren.com/ja/codex-new-mac", sitemap)
        self.assertIn("Codexを新しいMacへ安全に移行・転送する方法", japanese)
        self.assertIn("~/.codex/auth.json", japanese)
        self.assertIn("~/.codex/installation_id", japanese)
        self.assertIn("通常のChatGPTクラウド会話", japanese)
        self.assertIn("リアルタイムに統合する製品ではありません", japanese)
        self.assertIn("Macベータ版を購入 — $50", japanese)
        self.assertIn("アプリ画面とサポートは現在英語です", japanese)

    def test_closing_actions_can_wrap_when_text_is_enlarged(self):
        styles = (SITE / "styles.css").read_text()
        closing = styles.split("\n.closing-inner {", 1)[1].split("}", 1)[0]
        actions = styles.split("\n.closing .actions {", 1)[1].split("}", 1)[0]
        self.assertIn("flex-wrap: wrap", closing)
        self.assertIn("max-width: 100%", actions)
        self.assertNotIn("flex: 0 0 auto", actions)

    def parse(self, filename) -> _DocumentParser:
        parser = _DocumentParser()
        parser.feed((SITE / filename).read_text(encoding="utf-8"))
        return parser

    def test_every_page_has_title_h1_and_no_broken_local_link(self):
        for page in SITE.rglob("*.html"):
            relative = page.relative_to(SITE)
            with self.subTest(page=str(relative)):
                source = page.read_text(encoding="utf-8")
                parser = self.parse(relative)
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

    def test_paid_beta_offer_describes_current_download_and_price(self):
        text = " ".join(self.parse("index.html").text).lower()
        self.assertIn("signed, notarized mac beta", text)
        self.assertIn("apple silicon macs", text)
        self.assertIn("30-day refund policy", text)
        self.assertNotIn("not on sale yet", text)
        self.assertIn("$50", text)
        self.assertIn("no subscription", text)
        self.assertIn("free cli", text)

    def test_beta_checkout_requires_readiness_and_preserves_limitations(self):
        source = (SITE / "index.html").read_text()
        text = " ".join(self.parse("index.html").text)
        self.assertIn("Request Mac beta access — $50", text)
        self.assertIn("If checkout is unavailable, email Josh", text)
        self.assertIn("physical Wi-Fi interruption/resume testing", text)
        self.assertIn("Guided permission recovery, direct-cable interruption, pristine-Mac installation, and broader hardware coverage remain ongoing", text)
        self.assertIn("Keep your old Mac and an independent backup", text)
        self.assertIn("it does not merge two active workspaces", text)
        self.assertIn('<div id="checkout-panel" hidden>', source)
        self.assertIn('aria-describedby="checkout-platform beta-limits checkout-status"', source)
        self.assertIn('subject=Codex%20Migrate%20%2450%20beta%20access', source)
        for page in ("index.html", "moving-to-a-new-mac.html", "codex-history-missing-new-mac.html", "backup-and-recovery.html"):
            self.assertNotIn("alpha", (SITE / page).read_text().lower())

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
        heading_row = source.split('<div class="hero-heading">', 1)[1].split('<div class="product-reference">', 1)[0]
        self.assertIn('<h1>Change the Mac.', heading_row)
        self.assertIn('<span class="accent">Keep the work.</span>', heading_row)
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
        self.assertIn("minmax(0, 690px) 280px", heading)
        self.assertIn("justify-content: space-between", heading)
        self.assertIn("grid-row: 1", icon)
        self.assertIn("align-self: start", icon)
        self.assertNotIn("align-items: flex-end", styles)
        self.assertIn("margin: 0 0 16px", title)
        self.assertIn('<div class="hero-message">', (SITE / "index.html").read_text())

    def test_website_analytics_is_region_aware_and_separate_from_app(self):
        analytics = (SITE / "analytics.js").read_text()
        privacy = " ".join(self.parse("privacy.html").text)
        home = " ".join(self.parse("index.html").text)
        vercel = (ROOT / "vercel.json").read_text()
        for page in SITE.glob("*.html"):
            with self.subTest(page=page.name):
                if page.name == "purchase.html":
                    self.assertIn('src="/analytics.js?v=20260909-purchase"', page.read_text())
                    self.assertIn('name="referrer" content="no-referrer"', page.read_text())
                    continue
                self.assertIn('src="/analytics.js?v=20260907-deferred"', page.read_text())
        self.assertIn('const GRANTED = "granted"', analytics)
        self.assertIn('const PUBLIC_HOSTS = new Set(["migrate.segeren.com", "codex-migrate.vercel.app"]);', analytics)
        self.assertIn('!PUBLIC_HOSTS.has(window.location.hostname)', analytics)
        self.assertIn('fetch("/api/analytics-region"', analytics)
        self.assertIn('analyticsMode === "default"', analytics)
        self.assertIn('script.src = `https://www.googletagmanager.com/gtag/js?id=', analytics)
        self.assertIn("Analytics cookies?", analytics)
        self.assertIn(">Allow</button>", analytics)
        self.assertIn(">Decline</button>", analytics)
        self.assertIn("clearAnalyticsCookies();", analytics)
        self.assertIn('sendEvent(event.detail);', analytics)
        self.assertIn("records a generic purchase event", privacy)
        self.assertIn('window.gtag("consent", "default", consentValues(granted));', analytics)
        self.assertIn('window.gtag("consent", "update", consentValues(true));', analytics)
        self.assertIn('cookie_domain: "none"', analytics)
        self.assertIn('cookie_prefix: "cm"', analytics)
        self.assertIn('cookie_expires: 60 * 60 * 24 * 425', analytics)
        self.assertIn('cookie_update: true', analytics)
        self.assertIn("No app telemetry", home)
        self.assertIn("In markets where prior consent is not required, analytics cookies are enabled by default.", privacy)
        self.assertIn("European Economic Area, United Kingdom, and Switzerland", privacy)
        self.assertIn("It does not receive your name, email address, Codex conversations", privacy)
        self.assertIn("Google Signals may add aggregate", privacy)
        self.assertIn("https://www.googletagmanager.com", vercel)
        self.assertIn("https://analytics.google.com", vercel)
        self.assertIn("https://stats.g.doubleclick.net", vercel)
        self.assertIn("https://www.google.com", vercel)

    def test_consent_ui_is_compact_and_not_a_global_banner(self):
        styles = (SITE / "styles.css").read_text()
        consent = styles.split("\n.analytics-consent {", 1)[1].split("}", 1)[0]
        self.assertIn("360px", consent)
        self.assertIn("right: 16px", consent)
        self.assertNotIn("left:", consent)
        self.assertNotIn("880px", consent)

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

    def test_primary_cta_uses_dark_purple_blue_and_accessible_white_text(self):
        styles = (SITE / "styles.css").read_text()
        self.assertIn("--cta: #4432b8;", styles)
        self.assertIn("--cta-hover: #35258e;", styles)
        primary = styles.split("\n.button-primary {", 1)[1].split("}", 1)[0]
        self.assertIn("background: var(--cta)", primary)
        self.assertIn("color: #fff", primary)
        self.assertIn("outline-offset: 4px", styles)

    def test_paid_mac_beta_is_primary_but_free_cli_remains_prominent(self):
        source = (SITE / "index.html").read_text()
        hero = source.split('<div class="actions">', 1)[1].split("</div>", 1)[0]
        self.assertLess(hero.index("Get the Mac beta — $50"), hero.index("Get the free CLI"))
        self.assertIn('class="button button-primary" id="hero-paid-link" data-analytics-event="select_paid_beta"', hero)
        self.assertIn('class="button button-secondary" data-analytics-event="select_free_cli"', hero)
        self.assertIn('id="checkout-button" class="button button-primary full" data-analytics-event="begin_checkout"', source)

        closing = source.split('<section class="closing">', 1)[1].split("</section>", 1)[0]
        self.assertLess(closing.index("Get the Mac beta — $50"), closing.index("Use the free CLI"))
        self.assertIn('class="button button-primary" data-analytics-event="select_paid_beta" href="#founding-edition"', closing)
        self.assertIn('class="button button-secondary light" data-analytics-event="select_free_cli"', closing)

        editions = source.split('<section class="editions shell"', 1)[1].split("</section>", 1)[0]
        self.assertIn("The Mac app is the easy way.", editions)
        self.assertLess(editions.index('id="founding-edition"'), editions.index("Open source CLI"))
        self.assertLess(editions.index("Buy the Mac beta — $50"), editions.index("View the source and CLI"))

    def test_launch_interest_preserves_consent_and_separate_beta_help_email(self):
        page = self.parse("index.html")
        emails = [href for href in page.hrefs if href.startswith(
            "mailto:joshua@segeren.com?subject=Codex%20Migrate%20%2450%20beta%20access&")]
        self.assertEqual(len(emails), 1)
        text = " ".join(page.text)
        self.assertIn("Your request goes to Josh’s inbox via SendGrid", text)
        self.assertIn("case by case", text)
        self.assertIn("email Josh for help with the signed Mac beta", text)
        self.assertIn("Don’t email credentials or workspace contents", text)
        source = (SITE / "index.html").read_text()
        self.assertIn('action="/api/signup" method="post"', source)
        self.assertIn('type="checkbox" value="yes" required', source)
        self.assertIn('type="email"', source)

    def test_guides_are_discoverable_and_do_not_promise_unsafe_backup_bypass(self):
        home = (SITE / "index.html").read_text()
        sitemap = (SITE / "sitemap.xml").read_text()
        for path in ("moving-to-a-new-mac", "codex-history-missing-new-mac", "backup-and-recovery", "compare-codex-migration-tools", "access-codex-from-another-machine"):
            self.assertIn('href="/' + path + '"', home)
            self.assertIn("https://migrate.segeren.com/" + path, sitemap)
        self.assertIn("no skip-backup switch", (SITE / "backup-and-recovery.html").read_text())

    def test_comparison_guide_is_disclosed_and_fair(self):
        source = (SITE / "compare-codex-migration-tools.html").read_text()
        text = " ".join(self.parse("compare-codex-migration-tools.html").text)
        self.assertIn("Disclosure:", text)
        self.assertIn("published by Joshua Segeren, the developer of Codex Migrate", text)
        self.assertIn("Migration is not synchronization", text)
        self.assertIn("Manual copy or rsync", text)
        self.assertIn("https://github.com/ChenglongLi777/codex-migrate", source)
        self.assertIn("https://github.com/ademozsayin/codex-history-migrator", source)
        self.assertIn("https://codexsync.org/", source)
        self.assertIn("https://github.com/ToussaintKnight/codex-sync", source)
        self.assertIn("https://github.com/Se1ker/better-codex-rehome", source)
        self.assertIn("current releases are not commercially signed or Apple-notarized", text)
        self.assertIn("Keep the old computer intact", text)

    def test_remote_access_guide_distinguishes_control_ssh_migration_and_sync(self):
        source = (SITE / "access-codex-from-another-machine.html").read_text()
        text = " ".join(self.parse("access-codex-from-another-machine.html").text)
        self.assertIn("Access Codex from another machine", text)
        self.assertIn("Use OpenAI’s Remote experience", text)
        self.assertIn("Use Codex with Remote SSH", text)
        self.assertIn("Use a one-time migration", text)
        self.assertIn("Codex Migrate is not continuous sync", text)
        self.assertIn("ordinary ChatGPT cloud history", text)
        self.assertIn("https://openai.com/index/work-with-codex-from-anywhere/", source)
        self.assertIn("https://help.openai.com/en/articles/11369540", source)
        self.assertIn("https://github.com/openai/codex/issues/33830", source)
        self.assertIn("https://github.com/openai/codex/issues/37106", source)
        self.assertIn('href="/#founding-edition">Move to a new Mac — $50', source)
        self.assertIn("Codex Migrate is independent software, not an OpenAI product", text)

    def test_guide_footers_link_the_founder_name_to_x(self):
        founder_link = '<a href="https://x.com/JoshuaSegeren">Joshua Segeren</a>'
        for name in ("moving-to-a-new-mac", "codex-history-missing-new-mac", "backup-and-recovery", "compare-codex-migration-tools", "access-codex-from-another-machine"):
            self.assertIn(founder_link, (SITE / (name + ".html")).read_text())

    def test_recovery_guide_matches_live_beta_without_waiving_safety_limits(self):
        source = (SITE / "backup-and-recovery.html").read_text()
        text = " ".join(self.parse("backup-and-recovery.html").text)
        self.assertIn("signed, notarized Mac beta is $50 one time for Apple silicon Macs", text)
        self.assertIn("30-day refund policy", text)
        self.assertIn("physical Wi-Fi interruption/resume testing", text)
        self.assertIn("Guided permission recovery, direct-cable interruption, pristine-Mac installation, and broader hardware coverage remain ongoing", text)
        self.assertIn("Keep the old Mac intact and maintain an independent backup", text)
        self.assertIn('href="/#founding-edition">Get the Mac beta', source)
        self.assertNotIn("still in development", text)
        self.assertNotIn('href="/#launch-email"', source)

    def test_legal_pages_cover_purchase_basics(self):
        terms = " ".join(self.parse("terms.html").text).lower()
        refunds = " ".join(self.parse("refunds.html").text).lower()
        privacy = " ".join(self.parse("privacy.html").text).lower()
        self.assertIn("purchase provides the current beta download", terms)
        self.assertIn("not a promise that every configuration has been tested", terms)
        self.assertIn("physical wi-fi interruption/resume testing", terms)
        self.assertIn("guided permission recovery, direct-cable interruption, pristine-mac installation, and broader hardware coverage remain ongoing", terms)
        self.assertIn("$50 usd one time", terms)
        self.assertIn("no subscription", terms)
        self.assertIn("best-effort", terms)
        self.assertIn("no response time, fix, resolution deadline", terms)
        self.assertIn("30-day refund", refunds)
        self.assertIn("stripe", privacy)
        self.assertNotIn("checkout is not open", privacy)
        self.assertIn("do not sell personal data", privacy)
        success = " ".join(self.parse("success.html").text).lower()
        self.assertIn("completed purchases receive a private delivery link by email", success)
        self.assertNotIn("checkout is not open", success)


if __name__ == "__main__":
    unittest.main()
