"""Deterministic CLI failure categories and process exit codes."""

from enum import IntEnum


class ExitCode(IntEnum):
    SUCCESS = 0
    INTERNAL_ERROR = 1
    INVALID_INPUT = 2
    NOT_FOUND = 3
    DOMAIN_CONFLICT = 4
    TRANSPORT_FAILURE = 5


class CliError(Exception):
    exit_code = ExitCode.INTERNAL_ERROR


class CliInvalidInput(CliError):
    exit_code = ExitCode.INVALID_INPUT


class CliNotFound(CliError):
    exit_code = ExitCode.NOT_FOUND


class CliDomainConflict(CliError):
    exit_code = ExitCode.DOMAIN_CONFLICT
