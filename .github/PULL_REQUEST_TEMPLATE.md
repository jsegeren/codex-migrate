## User problem

<!-- What migration problem does this solve? -->

## Solution

<!-- What is the smallest implemented solution? -->

## Verification

- [ ] Tests pass on macOS with Python 3.9 and a current Python release.
- [ ] New or changed safety boundaries have regression tests.
- [ ] Dashboard changes were inspected at desktop and narrow-mobile widths.
- [ ] Examples and fixtures contain only synthetic data.

## Safety review

- [ ] Source data remains read-only.
- [ ] Destination Codex authentication and installation identity remain protected.
- [ ] Interruption and rollback behavior are documented.
- [ ] SSH host-key verification remains strict.
- [ ] No credentials, private paths, conversation content, or migration logs are included.
