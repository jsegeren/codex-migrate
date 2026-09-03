# Contributing

Thank you for helping make Mac-to-Mac Codex migration safer.

## Before opening a change

1. Do not use real conversation data, credentials, private repositories, or
   personal paths in tests or examples.
2. Explain the failure mode and rollback behavior.
3. Add or update tests for every affected safety boundary.
4. Run the complete test suite on macOS.

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Change expectations

- Keep the core dependency-free unless a dependency creates clear safety value.
- Preserve Python 3.9 compatibility.
- Use argument arrays for local processes; do not construct local shell
  commands from user input.
- Quote all remote paths and validate SSH targets.
- Never weaken target-auth preservation or SSH host-key checking.
- Keep the dashboard readable at desktop and narrow widths with a 14px minimum
  visible text size.

## Pull requests

Describe:

- the user problem;
- the smallest implemented solution;
- verification performed;
- privacy and security impact;
- interruption and rollback behavior; and
- any Codex versions or macOS versions tested.
