"""Only disposable shell fixtures may substitute the process snapshot."""

import re


def fixture_prefix(script, prefix):
    # Fault functions must live in the installer shell, not its lock launcher.
    match = re.search(r"<<'CODEX_MIGRATE_INSTALL_[0-9a-f]{32}'\n", script)
    if match:
        return script[:match.end()] + prefix + script[match.end():]
    return prefix + script


def closed_codex_script(script):
    # Keep the real identity/home ownership checks. Never inspect or terminate
    # the developer's running Codex as part of a disposable installation test.
    return fixture_prefix(script.replace("/bin/ps -axo uid=,comm=", "fixture_ps"),
                          "fixture_ps() { printf '%s /bin/zsh\\n' \"$(/usr/bin/id -u)\"; }\n")
