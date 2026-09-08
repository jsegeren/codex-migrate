# Search indexing and community discovery — September 5, 2026

## September 7 signed-beta launch and channel review

Published from the Founder's `JoshuaSegeren` X account and verified by opening
the resulting conversation:

- [Signed Apple silicon beta announcement](https://x.com/JoshuaSegeren/status/2097103693162430668):
  $50 one time, best-effort maintainer support, free MIT CLI, and an explicit
  reminder to retain the old Mac and an independent backup. Attached the
  Founder-selected `site/og-white-v1.png`, with alt text and its existing
  independent-tool/non-affiliation notice. The destination includes
  `utm_source=x&utm_medium=social&utm_campaign=signed_beta_sep2026`.
- [Source and free CLI reply](https://x.com/JoshuaSegeren/status/2097105215048855675):
  links the repository, explains the paid packaging/support distinction, and
  clarifies that this is a Mac-to-Mac move, not continuous sync.

This is a publication receipt, not proof of purchases or acquired customers.
No paid advertising, unsolicited DMs, likes, reposts, or account changes were
performed. The beta's remaining acceptance work remains open.

Channel review also narrowed the next outreach candidates:

- DEV's [AI guidelines](https://dev.to/guidelines-for-ai-assisted-articles-on-dev)
  prohibit AI-generated comments. The older DEV draft below is **not eligible
  for automated publication**; disclosure alone does not make it eligible.
  The relevant migration article remains useful research, not a posting task.
- [r/macapps' March moderation update](https://www.reddit.com/r/macapps/comments/1ryaeex/rmacapps_mods_went_too_far_whats_changing_phase_3/)
  describes a separate AppPile route for unproven apps, reputation requirements,
  and promotion limits. Inspect the current rules and active megathread before
  considering a submission. No post was made there.
- [Show HN](https://news.ycombinator.com/showhn.html) requires something readers
  can actually try, rather than only a landing page. The runnable free CLI is
  the appropriate candidate, with paid packaging disclosed separately. General
  HN rules and account availability still need checking; no submission was made.

The removed r/codex reply was not reposted. Windows migration requests,
continuous-sync requests and unverified missing-chat repairs were not treated
as problems this Mac-to-Mac beta has demonstrated it can solve.

## September 6 evening visibility recheck

An unauthenticated public read of the exact submitted Reddit permalink
`https://www.reddit.com/r/codex/comments/1tqczl5/comment/p84or8q/`
did not expose our reply text. It showed a deleted-author placeholder and
“Comment removed by moderator” beneath the original Mac-specific question.
Treat Reddit public visibility as unproven/removed, not successfully delivered
outreach. The precise moderation reason was not available. No duplicate post,
alternate account, unsolicited DM or evasion attempt was made. Any further
participation should follow moderator guidance; the earlier logged-in submission
receipt below remains historical evidence only.

Public GitHub readback still shows our original maintainer disclosure and the
contributor exchange at discussion comments 18311565, 18311704 and 18314228.
A bounded authenticated GraphQL read independently confirmed the same authors,
text and links. This is a verified visibility channel, not external acceptance
of the migration build.

Both helpful guide URLs returned HTTP 200 on this recheck. The production
availability endpoint still returned `{"available":false}`. Their earlier
Search Console indexing proof remains the indexing receipt; a successful HTTP
fetch is not a new Google-indexing check. No indexing request, production
deployment, customer charge or new social post was triggered.

Suggested moderator inquiry, **not sent**:

> Hi moderators — I'm Joshua Segeren, the maintainer of Codex Migrate. I posted
> a reply to rgorbie's question about moving chats to a new Mac, and it appears
> to have been removed. It was submitted with Codex assistance. I see the rule
> against bots and won't repost it. Is a personally written, clearly disclosed
> maintainer response appropriate here, or would you prefer no promotion?
> Original reply: https://www.reddit.com/r/codex/comments/1tqczl5/comment/p84or8q/

## September 6 Founder-approved Reddit reply

After reviewing the exact proposed text, the Founder explicitly requested its
publication under rgorbie's Mac-specific question. The reply was submitted once
from `JoshuaSegeren`; the browser showed the posted text, author and permalink:

<https://www.reddit.com/r/codex/comments/1tqczl5/comment/p84or8q/>

It identifies the author as the maintainer, links the free repository, describes
the alpha and Mac-to-Mac scope, and tells readers to retain the old Mac and check
restored work. No independent-customer endorsement, Windows support or completed
paid release is claimed. The earlier unposted draft/status below describes the
discovery pass before this explicit instruction, not the current posting state.
Logged-in readback confirms submission, not moderation approval or visibility to
every reader. No duplicate reply or wider posting campaign was initiated.

## September 6 contributor follow-up

The existing OpenAI Codex discussion received a genuine reply from `d-jiao`,
thanking the maintainer and offering to contribute. A readback confirmed that
reply belonged under our existing comment, rather than a separate promotion.

- Opened [a focused help-wanted test issue](https://github.com/jsegeren/codex-migrate/issues/1)
  for authentic Codex-created chats and projects on two disposable Mac accounts.
  It explains the alpha status, destination replacement rather than merging,
  invented fixtures, expected checks, and redacted evidence requirements.
- [Replied to the volunteer](https://github.com/openai/codex/discussions/14067#discussioncomment-18314228)
  as `jsegeren`, linking that issue and explicitly saying the CLI is alpha and
  the signed app is not released. GitHub readback confirmed the published text
  and author. No duplicate top-level advertisement or unsolicited DM was sent.
- This is contributor outreach, not completed external testing. The authentic
  application-level migration gate remains open until evidence is returned and
  reviewed.

## Indexed pages: verified in Search Console

Fresh URL inspections in the existing verified `https://migrate.segeren.com/`
property returned **URL is on Google** and **Page is indexed** for all three
URLs below. These were new inspections, not the stale indexing-request dialog
that was initially open. No additional indexing requests were submitted.

| URL | Last crawl displayed by Search Console |
| --- | --- |
| <https://migrate.segeren.com/> | September 4, 2026, 3:03:32 AM |
| <https://migrate.segeren.com/moving-to-a-new-mac> | September 5, 2026, 8:23:02 PM |
| <https://migrate.segeren.com/backup-and-recovery> | September 5, 2026, 8:24:39 PM |

Times are transcribed as displayed; no timezone conversion is asserted. For each
URL, the expanded report showed Googlebot smartphone, crawl allowed, successful
fetch, indexing allowed, the canonical site's sitemap, and Google-selected
canonical **Inspected URL**, matching the declared canonical. HTTPS also passed.

This closes the indexing requirement for the homepage and the two helpful
guides at this checkpoint. It does not establish ranking, search impressions,
traffic, conversions, permanent indexing, or indexing of every site page.

## Relevant communities, not a bulk-promotion list

Existing published X and GitHub discussion replies are recorded in
[release readiness](release-readiness.md). The original September 5 discovery
pass made no posts; the September 6 contributor reply is recorded above.

### DEV: directly relevant Mac migration article

[Rob Koch, Moving Codex Threads to a New Mac](https://dev.to/robcube/moving-codex-threads-to-a-new-mac-2n3i)
describes a manual local-state move and separately restoring workspace paths.
The live article showed zero comments and a logged-out browser. A useful reply
can add the distinction between copying history and preserving complete Git
worktrees, destination identity, and changed home paths. Do not claim that our
alpha is certified for the author's managed-enterprise environment.

DEV's [Code of Conduct](https://dev.to/code-of-conduct) requires AI-assistance
disclosure and links its AI guidelines. Read those guidelines before posting;
the draft below is not a posting receipt or a completed policy check.

Draft, not posted:

> The separate-workspace warning is important. In my Mac move, local Git
> worktrees and the changed macOS username needed attention as well as the
> conversation files. I built Codex Migrate around that problem: resumable SSH
> staging, verified destination backups, and preserving the new Mac's Codex
> authentication rather than copying the old login.
>
> Disclosure: I'm the maintainer. The Mac-to-Mac CLI is open-source alpha;
> the packaged paid app is still in testing. It is not continuous sync, and
> managed configurations need separate review. Keep the old Mac and an
> independent backup until you've opened and checked your restored work.
> https://github.com/jsegeren/codex-migrate
>
> Written with AI assistance.

### Reddit: specific unmet Mac request within a broader sync discussion

[r/codex discussion](https://www.reddit.com/r/codex/comments/1tqczl5/made_a_tool_to_sync_codex_chats_and_configs/)
includes repeated requests for a tool and an August 23 comment about missing
chats on a new Mac. The exact [Mac-specific comment by rgorbie](https://www.reddit.com/r/codex/comments/1tqczl5/comment/p5ff7x3/)
was opened and read in the signed-in browser on September 6. It describes
missing chats on a new Mac and asks whether a tool is available. No existing
reply from us appeared under it. The original post is about
Windows/Mac synchronization, so our tool is not a substitute for its full goal.

The Founder completed the public account **JoshuaSegeren**, associated with
their professional email. September 6 browser readback confirmed the signed-in
profile link `/user/JoshuaSegeren/`. This supersedes the earlier incomplete
signup using the proposed handle `JoshuaSegerenFounder`; do not restart signup
or create another account. The personal Reddit account remains outside scope.
Do not imply an independent recommendation by saying the maintainer merely
found the tool.

Current r/codex rule 9 says **Don't use bots. Read up on BotBouncer**. Its
linked [policy explanation](https://www.reddit.com/r/BotBouncer/wiki/index/)
describes moderation of automated/synthetic participation. During the initial
discovery pass, no Reddit comment was submitted. The recommendation was to leave
participation to the Founder personally or obtain
moderator clarification; do not tune wording, timing or accounts to evade
detection. The draft below is for review, not a posting receipt. No profile
changes, reputation-building activity, unsolicited DMs or top-level promotion
occurred in this pass.

Draft for that Mac-specific request only, not posted:

> If you're replacing one Mac with another rather than syncing Windows and
> Mac, I hit this too and built an open-source Mac-to-Mac migration tool:
> https://github.com/jsegeren/codex-migrate
>
> I'm the maintainer. It's alpha, not an official OpenAI tool or continuous
> sync. It stages selected local Codex data and complete selected workspaces
> over SSH, with destination backups before replacement. Keep the old Mac
> intact and check restored chats and projects before relying on the new one.

### Relevant engineering reports, not claims of a fix

- [Codex device identity after cloning, #37106](https://github.com/openai/codex/issues/37106): relevant to our destination-identity preservation boundary, but no proof that our tool resolves this report's complete device-identity behavior. Do not advertise it as a verified fix.
- [Existing chats missing after migration/update, #37853](https://github.com/openai/codex/issues/37853): the reporter can reopen history by ID while the sidebar remains empty. This reinforces the authentic chat-reopening release gate; file counts and SQLite integrity are not enough. Do not present a file transfer as a proven repair for that UI problem.

## Release boundary

### September 7 Reddit discovery and founder-account submission

The Founder authorized further relevant outreach as `u/JoshuaSegeren`.
The signed-in profile was verified before submission; it showed one post karma,
zero comment karma, and only the earlier Codex reply. No reputation-building,
voting, alternate-account activity, unsolicited customer DMs or paid ads were used.

- **r/OpenaiCodex:** read its current two sidebar rules and used the
  Showcase / Highlight flair plus Brand Affiliate disclosure. Submitted
  [the maintainer showcase](https://www.reddit.com/r/OpenaiCodex/comments/1wa9uuq/changing_macs_without_losing_local_codex_work_i/)
  with free MIT source, the $50 signed Apple silicon beta, support/refund details,
  and explicit non-affiliation, no-sync/no-merge and ongoing-testing limits.
  It appeared in the signed-in feed, but an independent logged-out read showed
  **“removed by Reddit's filters.” This is not a public visibility win.**
  Sent one moderator review request and verified it in Reddit's Mod mail chat.
  The request disclosed Codex-assisted preparation/submission and promised no
  reposting or filter evasion. No moderator response yet.
- **r/macapps:** current rules require 10 local karma for promotional comments,
  main-feed qualification, and no more than one developer promotion per 30 days,
  including removed posts. The
  [September App Pile](https://www.reddit.com/r/macapps/comments/1w4brkd/megathread_the_app_pile_september_2026/)
  requires Problem / Comparison / Pricing format, with no direct archive links.
  Its invitation to newer developers does not clearly resolve the comment-karma
  requirement. Sent and verified one Mod mail asking whether the threshold applies
  inside that thread, before posting. No promotion submitted there.
- **r/mac:** current sidebar explicitly prohibits promotion/advertising and
  generative-AI content. No post or comment submitted.
- **r/codex:** retained the existing removed-comment/no-bots boundary; no new
  automated reply or replacement posted.

Additional demand leads found, not contacted:

- [How are people migrating their Codex setup?](https://www.reddit.com/r/codex/comments/1udbz2y/how_are_people_migrating_their_codex_setup_from/)
  is June 23 but has a fresh September 6 Mac-migration guide reply. The original
  asker mentions Windows/SharePoint; do not pitch our Mac-only tool as solving
  their entire setup.
- [Why doesn't Codex remember my setup across computers?](https://www.reddit.com/r/codex/comments/1uirpdp/why_doesnt_codex_remember_my_setup_across/)
  is June 29 and principally asks for ongoing continuity/sync, not just migration.
- [Local chats visible on another computer?](https://www.reddit.com/r/codex/comments/1vskik3/are_local_codex_desktop_chats_visible_on_another/)
  is August 19 and asks about privacy boundaries, not a buying request.
- [Windows to Mac migration](https://www.reddit.com/r/codex/comments/1v0zq59/need_help_moving_codex_from_windows_to_mac/)
  is outside our supported platform scope. Do not advertise compatibility.

Next Reddit action is to read moderator responses, then use the approved format
and channel. Do not duplicate filtered posts, disguise commercial affiliation,
claim approval from a sent message, or manufacture karma to bypass thresholds.

Search indexing is now proved for the requested core pages. The overall product
goal remains open: authentic disposable-account Codex acceptance, remaining
device/failure-mode and assistive-technology checks, Apple activation and exact
signed/notarized download acceptance, and live seller/delivery readiness are
not replaced by discovery evidence.
