"""Account-scoped, fail-closed Codex process checks shared by both Macs."""

from pathlib import Path
import shlex
import subprocess

from codex_migrate.errors import MigrationError


def process_state_script(home: str) -> str:
    """Print exactly OPEN/CLOSED; errors must never imply the account is idle.

    Inspect executable names, not arguments or environment (which can contain
    secrets). UID ownership ties the inspected account to the selected home.
    This is a point-in-time guard, not a lock against future process launches.
    """
    return r'''cm_codex_state() {
  local cm_uid cm_real_uid cm_home_uid cm_rows
  cm_uid=$(/usr/bin/id -u) || return 1
  cm_real_uid=$(/usr/bin/id -ru) || return 1
  case "$cm_uid" in ''|*[!0-9]*) return 1 ;; esac
  test "$cm_uid" != 0 && test "$cm_uid" = "$cm_real_uid" || return 1
  test -d HOME_PATH && test ! -L HOME_PATH || return 1
  cm_home_uid=$(/usr/bin/stat -f %u HOME_PATH) || return 1
  test "$cm_home_uid" = "$cm_uid" || return 1
  cm_rows=$(/bin/ps -axo uid=,comm=) || return 1
  test -n "$cm_rows" || return 1
  printf '%s\n' "$cm_rows" | /usr/bin/awk -v account="$cm_uid" '
    {
      if ($1 !~ /^-?[0-9]+$/ || NF < 2) { invalid=1; next }
      if ($1 != account) next
      seen=1
      executable=$0
      sub(/^[[:space:]]*[0-9]+[[:space:]]+/, "", executable)
      sub(/^.*\//, "", executable)
      if (executable == "ChatGPT" || executable == "Codex" || executable == "codex") open=1
    }
    END {
      if (invalid || !seen) exit 1
      print open ? "OPEN" : "CLOSED"
    }'
}
cm_codex_state || { echo 'Cannot verify Codex process state for the migration account. No installation is allowed.' >&2; exit 70; }
'''.replace("HOME_PATH", shlex.quote(home))


def require_codex_closed_script(home: str) -> str:
    return 'cm_checked_state=$(\n' + process_state_script(home) + ''') || exit 70
test "$cm_checked_state" = CLOSED || {
  echo 'Codex is running in the destination migration account. Close its app and CLI sessions before finalizing.' >&2
  exit 70
}
'''


def codex_running(source_home=None) -> bool:
    try:
        result = subprocess.run(
            ["/bin/zsh", "-f", "-s"],
            input=process_state_script(str(source_home or Path.home())),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, check=False, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired, UnicodeError) as error:
        raise MigrationError("Cannot verify local Codex process state; finalization is blocked") from error
    if result.returncode or result.stdout.strip() not in ("OPEN", "CLOSED"):
        raise MigrationError("Cannot verify local Codex process state; finalization is blocked")
    return result.stdout.strip() == "OPEN"
