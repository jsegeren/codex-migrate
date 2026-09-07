#!/bin/zsh -f
if [[ "$(/usr/bin/id -un)" != jsegeren ]]; then
  print 'Open this on the OLD Mac from your personal account.'
  read '?Press Return to close.'
  exit 1
fi
print 'Continue the disposable two-Mac test with signed build 4.'
print 'This checks the backup first, then resumes migration only if safe.'
print 'Existing sign-ins, test conversations, staging and backups are retained.'
print 'Enter your OLD Mac administrator password. Input stays invisible.'
/usr/bin/sudo -p 'Old Mac administrator password: ' -u codexmigratesource \
  /usr/bin/python3 -I /Users/Shared/CodexMigrate-Authentic-20260906/resume_build4_acceptance.py --background
task_result=$?
if [[ "$task_result" != 0 ]]; then
  print 'Authorization or launch failed. Tell Codex; do not repeat setup.'
fi
read '?Press Return to close.'
exit "$task_result"
