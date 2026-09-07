#!/bin/zsh -f
if [[ "$(/usr/bin/id -un)" != codexmigratesource ]]; then
  print 'Open this file on the OLD Mac in Codex Migrate Source.'
  print 'This only reads test diagnostics. No password or Codex sign-in is needed.'
  read '?Press Return to close.'
  exit 1
fi
/usr/bin/python3 /Users/Shared/CodexMigrate-Authentic-20260906/authentic_mac_handoff.py --diagnose
read '?Press Return to close. You can switch back to your personal account.'
