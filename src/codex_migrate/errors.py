"""Shared migration failure type, without transport or engine dependencies."""


class MigrationError(RuntimeError):
    pass
