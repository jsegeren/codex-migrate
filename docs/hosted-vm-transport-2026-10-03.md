# Independent-Mac protected Preview recovery transport

This is operator acceptance infrastructure, not a shipped client feature or a
successful cloud recovery receipt. The public app's ordinary HTTPS transport
and Vercel's authentication protections are unchanged.

The retained disposable Tart Mac boots as `admin` on macOS 26.6.2, arm64, with
clipboard/audio disabled and no host directory shares. The native guest agent
executes commands without asking the Founder to switch accounts. A native curl
probe reached the actual sandbox Worker with certificate verification enabled
and returned its expected root 404. The VM was stopped afterward. That proves
boot/control/network reachability, not encryption, enrollment or recovery.

`ops/preview_stdio_transport.py` supplies an explicitly selected, recovery-only
process-pipe relay. An operator-owned parent launches the fixed Tart command,
then handles bounded JSON frames from that child. The parent fixes the named
project's Preview origin and uses the existing independently reviewed
`PreviewOpener`; the guest cannot supply a URL. Only enrollment and recovery
POST routes are permitted. The actual service still authenticates the guest's
own native device credential; the relay cannot manufacture an entitlement or
object grant. Provider login caches and the host Keychain are not transferred.

The guest invokes the acceptance driver with `--stdio-preview-recovery`, which
is refused for prepare/publish and cannot be combined with the host CLI mode.
Its device bearer travels only over the owned pipe and into the existing host
CLI transport's stdin. No bearer, recovery key or signed grant belongs in Tart
argv, diagnostics, Git or this document. R2 downloads remain direct guest HTTPS
using the service-issued read grants, not this relay. Upload and object-store
opener constructors are not changed. The context restores the two patched
constructors even after an exception.

Frame reads and writes are bounded, including partial-frame timeouts; JSON
duplicate fields, wrong sequence, extra fields, noncanonical/oversized bodies,
unexpected headers, redirects/foreign paths and header injection are refused.
Response status and selected content headers are preserved; cookies/provider
headers are not forwarded. A parent session is bounded to 15 minutes and 300
API calls. Child failures/diagnostics are redacted and the owned child process
group is terminated/reaped on failure. Success requires the explicit recovery
result and matching zero exit; any extra stdout is refused. This compact signal
always says `complete_release_acceptance: false`. The actual private guest
receipt and encrypted bytes must still be inspected independently.

Local tests exercise a real owned child process over pipes plus rejection,
redaction, timeout, status, constructor restoration and protocol-boundary
checks. These tests use synthetic fake service responses and do not certify
actual R2, the VM transport, billing, scheduled backups or the final app.

Next: independently review the exact source/tests, run enabled CI, provision
the VM's test-only interpreter and exact native crypto helper, then use this
relay through Tart against the actual protected Preview. Complete actual email
pairing and test subscription first; do not invent device or billing rows to
get a passing result. Preserve the original release gates, including saved-key
recovery, corruption/interruption, scheduling, notarization and updates.

## Actual guest-disconnect finding and shutdown guard

An actual disposable-VM probe showed that a guest descendant can remain alive
after its local Tart client fails closed. Killing the local process group is
not remote guest-process containment. The test VM was immediately stopped and
its stopped state verified; no personal or customer data was involved.

`ops/hosted_vm_recovery.py` is the host entrypoint for the actual recovery drill.
It fixes the one dedicated VM, interpreter and guest acceptance-driver path;
it accepts only UUID identities and guest-private file paths, not credentials.
It requires that the owned VM is already running, invokes the pipe relay, and
always stops that VM and rechecks live Tart state in `finally`, including after
failure or operator interruption. Unverified shutdown refuses a success result.
It never starts, changes or stops any other VM. This is disposable-test
containment, not a shipping recovery strategy or a cloud recovery receipt.
