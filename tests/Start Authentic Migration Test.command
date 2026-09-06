#!/bin/zsh -f
if [[ "$(/usr/bin/id -un)" != codexmigratesource ]]; then
  print 'Open this file on the OLD Mac while logged into Codex Migrate Source.'
  print 'No administrator password is needed. Do not run it from your personal account.'
  read '?Press Return to close.'
  exit 1
fi
/usr/bin/python3 /Users/Shared/CodexMigrate-Authentic-20260906/authentic_mac_handoff.py --background
read '?Press Return to close this window. The background test keeps running.'
