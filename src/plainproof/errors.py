"""Exceptions shared across plainproof."""

from __future__ import annotations


class PlainproofError(Exception):
    """Base of plainproof's own errors."""


class ConfigError(PlainproofError):
    """A problem in the user's setup (missing key, unknown model, missing file...).

    The command line reports it as a one-line message, without a traceback, and exits with code 2.
    """
