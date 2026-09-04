# Getting help without exposing your workspace

Use **Help / Email support** in native setup, browser setup, or the migration
dashboard. Email Joshua Segeren at **joshua@segeren.com**. If you do not have a
desktop email app configured, copy that address into your usual email service.
Opening the email link creates a draft; it does not send a message.

## Include the diagnostic event log

In browser setup or the migration dashboard:

1. Open Help and choose **Prepare diagnostic report**.
2. Review the report shown on screen.
3. Choose **Save report to attach**.
4. Attach `codex-migrate-diagnostics.json` to your support email. Explain what
   you were trying to do and what happened.

The report is generated locally. Nothing is uploaded or emailed automatically.
It includes app/macOS versions, packaged build identity when available,
processor architecture, migration mode, size
estimates, verification flags, and up to 60 timestamped status/phase/failure
category changes. Expand **Recent migration events** on the dashboard to see
that history. Ordinary
byte-progress updates do not flood the history. Recorded transitions survive
helper restarts; earlier versions did not record this history.

This is a structured event log, **not a raw console dump**. It does not include
conversation text, credentials, hostnames, usernames, private paths, filenames,
raw commands, exception messages, or arbitrary configuration fields. Failure
categories are troubleshooting hints, not a diagnosis. Missing verification
evidence is shown as unknown, not success. Review sizes and timestamps too if
they are sensitive to you.

The report does not capture every SSH packet, browser-console event, native
launcher error, or power-loss event. If the helper cannot open or cannot read
its migration state, email without a report. Do not delete state or backups to
make reporting work. We may ask for a specific additional diagnostic after
reviewing your issue; do not send an entire `.codex` folder or raw terminal log.

## While you wait

Keep the old Mac's data, staging, and destination backups. During copying,
choose Stop safely and wait before quitting. During installation, let the
protected phase finish. If installation fails or power is lost, keep Codex
closed on the destination and ask for help before replacing anything.

Support is best-effort and case by case. We aim for an initial reply within a
few business days, depending on availability and complexity; response times,
fixes, and resolution deadlines are not guaranteed. The paid app is not yet
released, and this contact path does not change its release status.
