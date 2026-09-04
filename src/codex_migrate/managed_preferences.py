"""Presence-only macOS preference check; never decode or change policy."""
import shlex


PRESENT_MESSAGE = (
    "Managed Codex preferences were detected. Full migration needs administrator "
    "and support review. Keep data and policy settings intact; do not disable "
    "management to bypass this check."
)
UNKNOWN_MESSAGE = (
    "Managed Codex preferences could not be checked. Keep data and policy "
    "settings intact and contact support before full migration."
)

# NSUserDefaults searches the named app's preferences for the executing user.
# Check the returned object's presence without converting or logging its value.
# This is not a policy resolver, MDM enrollment detector or cloud-policy check.
PROBE = r'''
function run() {
    try {
        ObjC.import("Foundation");
        const prefs = $.NSUserDefaults.alloc.initWithSuiteName("com.openai.codex");
        if (prefs.isNil()) return "UNKNOWN";
        const keys = ["config_toml_base64", "requirements_toml_base64"];
        for (const key of keys) {
            if (!prefs.objectForKey(key).isNil()) return "PRESENT";
        }
        return "ABSENT";
    } catch (_) {
        return "UNKNOWN";
    }
}
'''


def managed_preferences_script():
    """Run for the already-validated local/SSH account with a fixed deadline.

    OSA/Foundation diagnostics are discarded. Only fixed classifications cross
    the probe boundary; callers' normal process-group cancellation still applies.
    The alarm survives exec, bounding this check even inside final installation.
    """
    command = (
        "/usr/bin/env -u PERL5OPT -u PERL5LIB -u PERLLIB -u PERLIO -u PERL_UNICODE "
        "/usr/bin/perl -e " + shlex.quote("alarm 10; exec @ARGV; exit 69;")
        + " -- /usr/bin/osascript -l JavaScript -e " + shlex.quote(PROBE)
    )
    return (
        "cm_managed_preference_result=$(" + command + " 2>/dev/null) || cm_managed_preference_result=UNKNOWN\n"
        'case "$cm_managed_preference_result" in\n'
        "  ABSENT) ;;\n"
        "  PRESENT) printf '%s\\n' " + shlex.quote(PRESENT_MESSAGE) + " >&2; exit 68 ;;\n"
        "  *) printf '%s\\n' " + shlex.quote(UNKNOWN_MESSAGE) + " >&2; exit 69 ;;\n"
        "esac\nunset cm_managed_preference_result\n"
    )
