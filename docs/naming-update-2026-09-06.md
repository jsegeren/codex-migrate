# OpenAI / ChatGPT naming update

The GitHub repository description and topics now identify OpenAI Codex and
Codex in the ChatGPT desktop app. Product branding remains Codex Migrate;
the unofficial relationship and local-data scope remain explicit.

Source `b3fd183` updates the homepage, social/search descriptions and Mac guide.
All 21 site tests pass, including the local Codex versus ordinary ChatGPT cloud
chat distinction. Deployment `dpl_9zSoNYJwU67J4WjRP95XR4NgchLb` was promoted to
the existing Production domains. HTTP checks returned 200 and verified the
new terminology and scope on both changed pages. Checkout availability remains
false; no payment, release-catalog or webhook settings were changed.

The README wording is committed and pushed on the release task branch, not yet
on the default branch. Do not merge unrelated release changes merely to publish
this README update. No new browser accessibility certification is claimed for
this copy-only change.

Official naming reference consulted:
https://learn.chatgpt.com/docs/permission-modes

The temporary exact-source deployment directory was moved to Trash after
publication. The user-owned untracked social assets were excluded and preserved.
