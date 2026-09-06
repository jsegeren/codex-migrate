# Search indexing and community discovery — September 5, 2026

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
describes moderation of automated/synthetic participation. No automated Reddit
comment was submitted. Leave participation to the Founder personally or obtain
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

Search indexing is now proved for the requested core pages. The overall product
goal remains open: authentic disposable-account Codex acceptance, remaining
device/failure-mode and assistive-technology checks, Apple activation and exact
signed/notarized download acceptance, and live seller/delivery readiness are
not replaced by discovery evidence.
