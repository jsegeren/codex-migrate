# Search indexing and community discovery — September 5, 2026

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
[release readiness](release-readiness.md). No additional comment, direct
message, signup, or account creation occurred in this discovery pass.

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
chats on a new Mac. Search rendering exposed that comment; the live logged-out
page did not load it in the inspected state. The original post is about
Windows/Mac synchronization, so our tool is not a substitute for its full goal.

The Founder requested a separate public founder Reddit account as part of this
project, explicitly lower priority than release readiness. Account creation and
profile setup are authorized project work, but remain pending. Do not use,
identify, or link the Founder's personal Reddit account. Do not imply an
independent recommendation by saying the maintainer merely found this tool.

September 5 signup preparation: opened Reddit's normal signed-out registration
flow with the professional `joshua@segeren.com` email. The requested email
verification succeeded without exposing or retaining its one-time code.
`JoshuaSegerenFounder` is entered and Reddit displays that it is available.
This is **not a reserved handle or a created account**: signup is waiting at
the password step. No password was generated, saved or submitted, no personal
Reddit account was opened, and no profile or post was published. The prepared
Chrome tab was retained for the Founder to set a password in their own password
manager. Do not restart email verification or create a duplicate account while
that signup is pending.

Next actions: finish the password/signup and any required human verification
checkpoints, configure
a truthful founder profile, and read current subreddit rules. Then load the
exact Mac-specific comment, check for an existing reply, and respond there at
most once from the new account with maintainer disclosure. Do not bypass
CAPTCHA, manufacture account reputation, hijack the original author's showcase,
send unsolicited DMs, or imply Windows/continuous-sync support. No completed
account creation or Reddit post has occurred yet.

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
