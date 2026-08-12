"""Background thread that repeatedly fetches the option chain and caches the
latest normalized snapshot. Decoupling the fetch cadence from HTTP requests
means a slow or rate-limited Nubra call never blocks a page load -- callers
just get the last good snapshot.
"""

import threading
import traceback
from datetime import datetime, timezone

from backend import nubra_client
from backend.metrics import normalize_chain


class ChainPoller:
    def __init__(self, instrument, poll_interval_sec):
        self.instrument = instrument
        self.poll_interval_sec = poll_interval_sec
        self._lock = threading.Lock()
        self._expiry = None
        self._snapshot = None
        self._last_updated = None
        self._last_error = None
        self._stop = threading.Event()
        self._thread = None

    def set_expiry(self, expiry):
        with self._lock:
            self._expiry = expiry or None

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                with self._lock:
                    expiry = self._expiry
                raw = nubra_client.fetch_raw_option_chain(self.instrument, expiry)
                normalized = normalize_chain(raw)
                with self._lock:
                    self._snapshot = normalized
                    self._last_updated = datetime.now(timezone.utc)
                    self._last_error = None
            except Exception as exc:  # keep polling even if one cycle fails
                with self._lock:
                    self._last_error = str(exc)
                traceback.print_exc()
            self._stop.wait(self.poll_interval_sec)

    def get_snapshot(self):
        with self._lock:
            return self._snapshot, self._last_updated, self._last_error
