"""Background analytics refresher (data-model.md §Refresh rules).

A daemon thread separate from the publishing scheduler: every `interval` (5 min)
or when woken by a manual request, it runs one `run_refresh_cycle`. Unlike the
scheduler it does not run a cycle at start-up, so starting the application never
contacts a platform by itself. It keeps the
platform pauses across cycles and ignores the automation pause (FR-017); publishing
always wins because each cycle yields to it. Logs carry only exception class names.
"""

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from app.analytics.adapters.base import MetricsAdapter
from app.analytics.refresh import (
    MAX_PER_CYCLE,
    CycleReport,
    PlatformPauses,
    run_refresh_cycle,
)
from app.db import utc_now
from app.models import Platform

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalyticsRefresherSettings:
    clock: Callable[[], datetime] = utc_now
    # Seconds between two cycles.
    interval: float = 300.0
    # Waits up to the given seconds; returns early when woken. Defaults to an
    # interruptible wait on the refresher's own events.
    wait: Callable[[float], object] | None = None
    autostart: bool = True
    limit: int = MAX_PER_CYCLE
    stop_timeout: float = 5.0


class AnalyticsRefresher:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        adapters: Mapping[Platform, MetricsAdapter],
        settings: AnalyticsRefresherSettings,
    ) -> None:
        self.session_factory = session_factory
        self.adapters = adapters
        self.settings = settings
        self.pauses = PlatformPauses()
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._cycle_lock = threading.Lock()
        self._start_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.last_report: CycleReport | None = None

    # --- Lifecycle ------------------------------------------------------------------

    def start(self) -> None:
        """Idempotent: there is never more than one worker thread."""
        with self._start_lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(
                target=self._loop, name="analytics-refresher", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._thread is not None:
            self._thread.join(self.settings.stop_timeout)

    def wake(self) -> None:
        """Run the next cycle now instead of waiting for the interval."""
        self._wake_event.set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            self._wait()
            if self._stop_event.is_set():
                break
            self._tick()

    def _wait(self) -> None:
        if self.settings.wait is not None:
            self.settings.wait(self.settings.interval)
            return
        self._wake_event.wait(self.settings.interval)
        self._wake_event.clear()

    def _tick(self) -> None:
        try:
            self.run_once()
        except Exception as exc:  # A failed cycle never stops the refresher.
            logger.error("Analytics refresh cycle failed (%s).", type(exc).__name__)

    # --- One cycle ------------------------------------------------------------------

    def run_once(self) -> CycleReport:
        """One cycle; never two at the same time (the thread and a direct call)."""
        with self._cycle_lock:
            report = run_refresh_cycle(
                self.session_factory,
                self.adapters,
                self.settings.clock(),
                pauses=self.pauses,
                limit=self.settings.limit,
            )
            self.last_report = report
            return report
