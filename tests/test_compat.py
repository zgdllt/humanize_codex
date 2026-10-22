"""The Codex migration workaround guards initialization, not model turns."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from hmz.coganchor.agents.codex import _AppServer

from humanize_codex.compat import guard_codex_startup


def test_startup_guard_serializes_constructors_and_is_idempotent(monkeypatch):
    active = peak = 0
    lock = threading.Lock()

    def initialize(self, label):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)
        self.label = label
        with lock:
            active -= 1

    monkeypatch.setattr(_AppServer, "__init__", initialize)
    guard_codex_startup()
    wrapped = _AppServer.__init__
    guard_codex_startup()
    assert _AppServer.__init__ is wrapped
    with ThreadPoolExecutor(max_workers=4) as executor:
        made = list(executor.map(_AppServer, range(4)))
    assert peak == 1
    assert [item.label for item in made] == list(range(4))
