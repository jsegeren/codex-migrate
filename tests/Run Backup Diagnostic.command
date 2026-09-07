#!/bin/zsh -f
# One exact account-local diagnostic; no persistent privileged worker.
if [[ "$(/usr/bin/id -un)" != jsegeren ]]; then
  print 'Open this on the OLD Mac from your personal jsegeren account.'
  read '?Press Return to close.'
  exit 1
fi
print 'Codex Migrate: read-only backup diagnostic'
print 'This will read the disposable test backup. It will NOT restart migration or repair files.'
print 'Enter your OLD Mac administrator password below. Nothing appears while typing.'
print 'No account switching, password sharing, or copy/paste is needed.'
umask 077
task_report=/Users/Shared/CodexMigrate-Authentic-20260906/backup-probe-launch.txt
if [[ -L "$task_report" || ( -e "$task_report" && ! -O "$task_report" ) ]]; then
  print 'Unsafe diagnostic status file; stopped.'
  exit 1
fi
print 'Diagnostic awaiting local authorization.' > "$task_report"
/usr/bin/sudo -p 'Old Mac administrator password (input hidden): ' -u codexmigratesource \
  /usr/bin/python3 -I /Users/Shared/CodexMigrate-Authentic-20260906/backup_comparison_probe.py \
  >> "$task_report"
task_result=$?
print "Diagnostic exit code: $task_result" >> "$task_report"
if [[ "$task_result" = 0 ]]; then
  print 'Done. The diagnostic report is ready for Codex to read. You can close this window.'
else
  print 'The diagnostic stopped. Codex can read its launch status; do not rerun migration.'
fi
read '?Press Return to close.'
exit "$task_result"
