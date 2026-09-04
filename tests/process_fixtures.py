"""Only disposable shell fixtures may substitute the process snapshot."""


def closed_codex_script(script):
    # Keep the real identity/home ownership checks. Never inspect or terminate
    # the developer's running Codex as part of a disposable installation test.
    return ("fixture_ps() { printf '%s /bin/zsh\\n' \"$(/usr/bin/id -u)\"; }\n"
            + script.replace("/bin/ps -axo uid=,comm=", "fixture_ps"))
