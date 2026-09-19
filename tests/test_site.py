from html.parser import HTMLParser
from pathlib import Path
import json
import re
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
    def test_home_product_metadata_matches_the_live_paid_offer(self):
        home = (SITE / "index.html").read_text()
        match = re.search(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', home, re.DOTALL)
        self.assertIsNotNone(match)
        product = json.loads(match.group(1))
        self.assertEqual(product["@type"], "Product")
        self.assertEqual(product["name"], "Codex Migrate Mac beta")
        self.assertEqual(product["brand"]["name"], "Codex Migrate")
        self.assertEqual(product["offers"]["url"], "https://migrate.segeren.com/#founding-edition")
        self.assertEqual(product["offers"]["price"], 49)
        self.assertEqual(product["offers"]["priceCurrency"], "USD")
        self.assertEqual(product["offers"]["availability"], "https://schema.org/InStock")
        self.assertEqual(product["offers"]["seller"]["name"], "Segeren Studio")

    def test_home_offer_and_migration_search_copy_are_current(self):
        home = (SITE / "index.html").read_text()
        self.assertIn("Signed &amp; notarized Mac beta", home)
        self.assertIn("<h1>Keep your <br>", home)
        self.assertIn("Back up and search your local Codex conversations", home)
        self.assertIn("Move everything safely when you change Macs", home)
        self.assertIn("Recover one missing conversation", home)
        self.assertIn("30-day refund guarantee", home)
        self.assertIn("Questions before buying? Ask Joshua", home)
        self.assertIn("full refund", home)
        self.assertNotIn("Mac builds by request", home)
        self.assertIn("Why not just do it yourself?", home)
        self.assertIn("The complete engine is MIT licensed and free", home)
        guide = (SITE / "moving-to-a-new-mac.html").read_text()
        self.assertIn("Transfer or move Codex to a new Mac", guide)
        self.assertIn("<h1>Transfer Codex <br>to a new Mac.</h1>", guide)
        self.assertIn("Get the Mac beta — $49", guide)
        self.assertIn("Why signing in on the new Mac is not enough", guide)
        self.assertIn("New-Mac migration checklist", guide)
        missing = (SITE / "codex-history-missing-new-mac.html").read_text()
        self.assertIn("Codex history missing on a new Mac?", missing)
        self.assertIn("Codex history is missing. What now?", missing)
        self.assertIn("Do not blindly replace the new Mac’s Codex folder", missing)
        self.assertIn('href="/codex-vault"', home)
        self.assertIn('href="/compare-codex-migration-tools"', home)
        guide_actions = guide.split('<div class="actions">', 1)[1].split("</div>", 1)[0]
        self.assertLess(guide_actions.index("Get the Mac beta — $49"), guide_actions.index("Read the free CLI setup"))
        recovery = (SITE / "backup-and-recovery.html").read_text()
        recovery_actions = recovery.split('<div class="actions">', 1)[1].split("</div>", 1)[0]
        self.assertLess(recovery_actions.index("Get the Mac beta — $49"), recovery_actions.index("Explore the free source"))

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
        for name in ("privacy", "terms", "refunds", "codex-vault", "moving-to-a-new-mac", "codex-history-missing-new-mac", "backup-and-recovery", "compare-codex-migration-tools", "access-codex-from-another-machine"):
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
        self.assertIn("Macベータ版を購入 — $49", japanese)
        self.assertIn("49米ドルの買い切り", japanese)
        self.assertNotIn("50米ドル", japanese)
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
        for page, asset in (("backup-and-recovery.html", "dashboard-backup-blocked.png"),):
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

    def test_home_has_accessible_real_interface_demos_with_honest_timing(self):
        source = (SITE / "index.html").read_text()
        text = " ".join(self.parse("index.html").text)
        self.assertEqual(source.count('<video controls preload="metadata"'), 2)
        self.assertIn('role="tablist" aria-label="Product walkthroughs"', source)
        self.assertIn('role="tab" id="vault-demo-tab" aria-selected="true"', source)
        self.assertIn('role="tab" id="migration-demo-tab" aria-selected="false"', source)
        self.assertIn('poster="/assets/codex-vault-demo-build14-poster.jpg"', source)
        self.assertIn('src="/assets/codex-vault-demo-build14.webm" type="video/webm"', source)
        self.assertIn('poster="/assets/codex-migrate-demo-build14-poster.jpg"', source)
        self.assertIn('src="/assets/codex-migrate-demo-build14.webm" type="video/webm"', source)
        self.assertIn("Both walkthroughs use the shipped build 14 interface with staged sample data.", text)
        self.assertIn("Watch a migration in 1 minute.", text)
        self.assertIn("Transfer time depends on data size and your connection.", text)
        for name in ("codex-vault-demo-build14.webm", "codex-vault-demo-build14-poster.jpg",
                     "codex-migrate-demo-build14.webm", "codex-migrate-demo-build14-poster.jpg"):
            self.assertTrue((SITE / "assets" / name).is_file())
        for name in ("codex-vault-demo-build14.webm", "codex-migrate-demo-build14.webm"):
            self.assertLess((SITE / "assets" / name).stat().st_size, 2_000_000)

    def test_support_is_best_effort_not_an_sla(self):
        home = " ".join(self.parse("index.html").text)
        self.assertIn("Best-effort help directly from Joshua", home)
        self.assertIn("timing and resolution are not guaranteed", home)
        self.assertNotIn("Founding five", home)

    def test_paid_beta_offer_describes_current_download_and_price(self):
        text = " ".join(self.parse("index.html").text).lower()
        self.assertIn("signed and notarized apple silicon mac beta", text)
        self.assertIn("apple silicon macs", text)
        self.assertIn("30-day refund policy", text)
        self.assertNotIn("not on sale yet", text)
        self.assertIn("$49", text)
        self.assertIn("no subscription", text)
        self.assertIn("free cli", text)

    def test_beta_checkout_is_immediately_visible_and_preserves_limitations(self):
        source = (SITE / "index.html").read_text()
        text = " ".join(self.parse("index.html").text)
        self.assertIn("Request Mac beta access — $49", text)
        self.assertIn("If checkout is unavailable, email Joshua", text)
        self.assertIn("physical Wi-Fi interruption/resume testing", text)
        for limitation in ("Retention controls", "cloud-folder health monitoring",
                           "guided permission recovery", "direct-cable interruption",
                           "pristine-Mac installation", "broader hardware coverage remain ongoing"):
            self.assertIn(limitation, text)
        self.assertIn("Keep your old Mac and an independent backup", text)
        self.assertIn("it does not merge two active workspaces", text)
        self.assertIn('<div id="checkout-panel">', source)
        self.assertIn('<div id="edition-disclosure" hidden>', source)
        self.assertIn('aria-describedby="checkout-platform beta-limits migration-guarantee checkout-status"', source)
        self.assertIn('subject=Codex%20Migrate%20%2449%20beta%20access', source)
        for page in ("index.html", "moving-to-a-new-mac.html", "codex-history-missing-new-mac.html", "backup-and-recovery.html"):
            self.assertNotIn("alpha", (SITE / page).read_text().lower())

    def test_migration_guide_explains_network_choices_and_cable_limit(self):
        text = " ".join(self.parse("moving-to-a-new-mac.html").text)
        self.assertIn("Wi-Fi, Ethernet, and working Thunderbolt networking can all carry SSH", text)
        self.assertIn("moving local Codex workspaces between Macs over SSH", text)
        self.assertIn("A charging-only or limited USB-C cable may be slower", text)

    def test_windows_faq_does_not_imply_current_support(self):
        text = " ".join(self.parse("index.html").text)
        self.assertIn("For OpenAI Codex on Apple silicon Macs", text)
        self.assertIn("Windows and cross-platform transfers are not supported today", text)

    def test_public_founder_name_is_linked_without_cross_promotion(self):
        source = (SITE / "index.html").read_text()
        self.assertIn('<a href="https://x.com/JoshuaSegeren">Joshua Segeren</a>', source)
        self.assertNotIn("Meet Ava at You.one", source)
        form = source.split('<form ', 1)[1].split('</form>', 1)[0]
        self.assertNotIn("you.one", form.lower())

    def test_codex_icon_is_a_separate_attributed_product_reference(self):
        source = (SITE / "index.html").read_text()
        self.assertIn('class="header-compatibility"', source)
        self.assertIn('src="/assets/codex-product-dark-80.png" width="40" height="40" alt=""', source)
        self.assertIn('<strong>For Codex</strong>', source)
        self.assertIn('Not affiliated with or endorsed by OpenAI.', source)
        self.assertIn('Codex product icon and OpenAI marks belong to OpenAI.', source)
        self.assertIn('href="/assets/mark.svg"', source)
        self.assertTrue((SITE / "assets/codex-product-dark.png").is_file())
        for size in (80,):
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

    def test_product_reference_is_small_subordinate_and_disclosed(self):
        source = (SITE / "index.html").read_text()
        header = source.split('<header class="site-header">', 1)[1].split('</header>', 1)[0]
        self.assertIn('class="header-compatibility"', header)
        self.assertIn('For Codex — independent migration tool', header)
        self.assertIn('>For Codex</strong>', header)
        self.assertIn('Independent · not affiliated', header)
        self.assertIn('srcset="/assets/codex-product-dark-80.avif" type="image/avif"', header)
        self.assertIn('src="/assets/codex-product-dark-80.png" width="40" height="40"', header)
        heading_row = source.split('<div class="hero-heading">', 1)[1].split('</div>\n          </div>', 1)[0]
        self.assertIn('<h1>Keep your', heading_row)
        self.assertIn('<span class="accent">Codex work safe.</span>', heading_row)
        self.assertNotIn('class="hero-inline-icon"', source)
        self.assertIn('Independent tool. Not affiliated with or endorsed by OpenAI.', heading_row)
        self.assertNotIn('class="terminal-card"', source)

    def test_hero_is_a_simple_single_column_message(self):
        styles = (SITE / "styles.css").read_text()
        layout = styles.split("\n.hero-copy {", 1)[1].split("}", 1)[0]
        heading = styles.split("\n.hero-heading {", 1)[1].split("}", 1)[0]
        title = styles.split("\n.hero-heading h1 {", 1)[1].split("}", 1)[0]
        self.assertIn("display: block", layout)
        self.assertIn("display: block", heading)
        self.assertIn("max-width: 820px", heading)
        self.assertNotIn("hero-inline-icon", styles)
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
                    self.assertIn('src="/analytics.js?v=20260911-ecommerce"', page.read_text())
                    self.assertIn('name="referrer" content="no-referrer"', page.read_text())
                    continue
                self.assertIn('src="/analytics.js?v=20260911-ecommerce"', page.read_text())
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
        self.assertIn("The app itself has no telemetry", home)
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
        self.assertLess(hero.index("Protect my Codex work — $49"), hero.index("Get the free CLI"))
        self.assertIn('class="button button-primary" id="hero-paid-link" data-analytics-event="select_paid_beta"', hero)
        self.assertIn('class="button button-secondary" data-analytics-event="select_free_cli"', hero)
        self.assertIn('id="checkout-button" class="button button-primary full" data-analytics-event="begin_checkout"', source)
        self.assertIn('<div id="checkout-panel">', source)
        self.assertIn('<div id="edition-disclosure" hidden>', source)

        closing = source.split('<section class="closing">', 1)[1].split("</section>", 1)[0]
        self.assertLess(closing.index("Get the Mac app — $49"), closing.index("Use the free CLI"))
        self.assertIn('class="button button-primary" data-analytics-event="select_paid_beta" href="#founding-edition"', closing)
        self.assertIn('class="button button-secondary light" data-analytics-event="select_free_cli"', closing)

        editions = source.split('<section class="editions shell"', 1)[1].split("</section>", 1)[0]
        self.assertIn("Use the app—or inspect every line.", editions)
        self.assertLess(editions.index('id="founding-edition"'), editions.index("Open-source CLI"))
        self.assertLess(editions.index("Protect my Codex work — $49"), editions.index("View the source and CLI"))

    def test_launch_interest_preserves_consent_and_separate_beta_help_email(self):
        page = self.parse("index.html")
        emails = [href for href in page.hrefs if href.startswith(
            "mailto:joshua@segeren.com?subject=Codex%20Migrate%20%2449%20beta%20access&")]
        self.assertEqual(len(emails), 1)
        text = " ".join(page.text)
        self.assertIn("Your request goes to Joshua’s inbox via SendGrid", text)
        self.assertIn("few business days", text)
        self.assertIn("email Joshua for help with the signed Mac beta", text)
        self.assertIn("Don’t email credentials or workspace contents", text)
        source = (SITE / "index.html").read_text()
        self.assertIn('class="launch-interest" id="launch-email" hidden', source)
        self.assertIn('action="/api/signup" method="post"', source)
        self.assertIn('type="checkbox" value="yes" required', source)
        self.assertIn('type="email"', source)

    def test_guides_are_discoverable_and_do_not_promise_unsafe_backup_bypass(self):
        home = (SITE / "index.html").read_text()
        sitemap = (SITE / "sitemap.xml").read_text()
        for path in ("codex-vault", "moving-to-a-new-mac", "backup-and-recovery", "compare-codex-migration-tools"):
            self.assertIn('href="/' + path + '"', home)
        for path in ("codex-vault", "moving-to-a-new-mac", "codex-history-missing-new-mac", "backup-and-recovery", "compare-codex-migration-tools", "access-codex-from-another-machine"):
            self.assertIn("https://migrate.segeren.com/" + path, sitemap)
        self.assertIn("no skip-backup switch", (SITE / "backup-and-recovery.html").read_text())

    def test_vault_page_matches_the_shipped_local_product_boundary(self):
        source = (SITE / "codex-vault.html").read_text()
        text = " ".join(self.parse("codex-vault.html").text)
        for phrase in ("Search the conversations stored on this Mac",
                       "client-side encrypted snapshot",
            "adds another verified snapshot every 24 hours",
                       "add one missing conversation",
                       "not continuous synchronization",
                       "does not host or receive the backup"):
            self.assertIn(phrase, text)
        for excluded in ("auth.json", "installation_id", "SSH keys", "repositories"):
            self.assertIn(excluded, text)
        self.assertIn("$49", text)
        self.assertIn("30-day refund policy", text)
        self.assertIn('src="/assets/codex-vault-demo-build14-poster.jpg"', source)
        self.assertIn("daily automatic backup selected by default", source)
        self.assertTrue((SITE / "assets" / "codex-vault-demo-build14-poster.jpg").is_file())

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
        self.assertIn("Codex Sync vs Codex Migrate", text)
        self.assertIn("does not transfer source repositories", text)
        self.assertIn("Choose Codex Sync for a small AirDrop record bundle", text)
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
        self.assertIn('href="/#founding-edition">Move to a new Mac — $49', source)
        self.assertIn("Codex Migrate is independent software, not an OpenAI product", text)

    def test_guide_footers_link_the_founder_name_to_x(self):
        founder_link = '<a href="https://x.com/JoshuaSegeren">Joshua Segeren</a>'
        for name in ("moving-to-a-new-mac", "codex-history-missing-new-mac", "backup-and-recovery", "compare-codex-migration-tools", "access-codex-from-another-machine"):
            self.assertIn(founder_link, (SITE / (name + ".html")).read_text())

    def test_recovery_guide_matches_live_beta_without_waiving_safety_limits(self):
        source = (SITE / "backup-and-recovery.html").read_text()
        text = " ".join(self.parse("backup-and-recovery.html").text)
        self.assertIn("signed, notarized Mac beta is $49 one time for Apple silicon Macs", text)
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
        self.assertIn("$49 usd one time", terms)
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
