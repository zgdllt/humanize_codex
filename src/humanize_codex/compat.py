"""Compatibility with Codex startup; no workflow algorithm lives here."""

import functools
import threading

_startup = threading.Lock()


def guard_codex_startup() -> None:
    """Avoid shared epic SQLite migration races in hmz 0.2.1 / Codex 0.163.

    Only the app-server initialize handshake is serialized. Model turns remain concurrent.
    Applied by the worker and native bridge, independent of the selected flow algorithm.
    No installed SDK file or user database is modified.
    """
    from hmz.coganchor.agents.codex import _AppServer

    original = _AppServer.__init__
    if getattr(original, "_humanize_codex_guarded", False):
        return

    @functools.wraps(original)
    def initialize(self, *args, **kwargs):
        with _startup:
            original(self, *args, **kwargs)

    initialize._humanize_codex_guarded = True
    _AppServer.__init__ = initialize
