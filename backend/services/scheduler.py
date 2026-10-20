"""Background wall-clock scheduler that drives the autonomous trading loop.

A single :class:`TradingScheduler` runs a daemon thread that calls
``AutonomousRunner.tick()`` on a fixed ET wall-clock cadence during tradeable sessions.
It is controlled by the ``/api/bot/start|pause|resume|stop`` routes.

Concurrency / safety:
* One scheduler instance per process (module singleton).
* Start/stop/pause/resume are guarded by a lock.
* The loop sleeps in short slices so stop/pause are responsive.
* On start it rebuilds the runner from current config, which reloads persisted per-day
  state (crash recovery) and reconciles fills before placing new orders (catch-up).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from backend.database import insert_log

logger = logging.getLogger(__name__)

STATE_STOPPED = "stopped"
STATE_RUNNING = "running"
STATE_PAUSED = "paused"


@dataclass
class SchedulerStatus:
    state: str = STATE_STOPPED
    interval_seconds: int = 60
    tick_count: int = 0
    last_tick_at: str | None = None
    last_session: str | None = None
    last_error: str | None = None
    last_result: dict | None = None
    kill_switch_active: bool = False
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.__dict__


class TradingScheduler:
    def __init__(self, runner_factory=None):
        self._runner_factory = runner_factory
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._paused = threading.Event()
        self._status = SchedulerStatus()
        self._runner = None

    # ── lifecycle ───────────────────────────────────────────────────────
    def start(self, cfg: dict) -> SchedulerStatus:
        with self._lock:
            if self._status.state == STATE_RUNNING:
                return self._status
            self._runner = self._build_runner(cfg)
            interval = int(cfg.get("scheduler", {}).get("interval_seconds", 60))
            self._status = SchedulerStatus(state=STATE_RUNNING, interval_seconds=max(1, interval))
            self._stop_event.clear()
            self._paused.clear()
            self._thread = threading.Thread(target=self._loop, name="trading-scheduler", daemon=True)
            self._thread.start()
            insert_log("bot", "Autonomous scheduler started", details={"interval_seconds": interval})
            return self._status

    def pause(self) -> SchedulerStatus:
        with self._lock:
            if self._status.state == STATE_RUNNING:
                self._paused.set()
                self._status.state = STATE_PAUSED
                insert_log("bot", "Autonomous scheduler paused")
            return self._status

    def resume(self, cfg: dict | None = None) -> SchedulerStatus:
        with self._lock:
            if self._status.state == STATE_PAUSED:
                self._paused.clear()
                self._status.state = STATE_RUNNING
                insert_log("bot", "Autonomous scheduler resumed")
                return self._status
            if self._status.state == STATE_STOPPED and cfg is not None:
                return self.start(cfg)
            return self._status

    def stop(self) -> SchedulerStatus:
        with self._lock:
            self._stop_event.set()
            self._paused.clear()
            thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5)
        with self._lock:
            self._status.state = STATE_STOPPED
            self._thread = None
            insert_log("bot", "Autonomous scheduler stopped")
            return self._status

    # ── one-shot tick (used by routes/tests without the thread) ──────────
    def run_once(self, cfg: dict) -> dict:
        runner = self._build_runner(cfg)
        result = runner.tick()
        self._record_tick(result)
        return result.to_dict()

    # ── status ──────────────────────────────────────────────────────────
    def status(self) -> SchedulerStatus:
        with self._lock:
            return self._status

    # ── internals ─────────────────────────────────────────────────────
    def _build_runner(self, cfg: dict):
        if self._runner_factory is not None:
            return self._runner_factory(cfg)
        from backend.services.autonomous_runner import AutonomousRunner

        return AutonomousRunner(cfg)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._paused.is_set():
                try:
                    result = self._runner.tick()
                    self._record_tick(result)
                except Exception as exc:  # never let the loop die silently
                    logger.exception("Scheduler tick failed: %s", exc)
                    with self._lock:
                        self._status.last_error = str(exc)
                    insert_log("bot", f"Scheduler tick error: {exc}", level="error")
            # Sleep in short slices so stop/pause are responsive.
            slept = 0.0
            interval = self._status.interval_seconds
            while slept < interval and not self._stop_event.is_set():
                time.sleep(min(0.5, interval - slept))
                slept += 0.5

    def _record_tick(self, result) -> None:
        from datetime import datetime, timezone

        with self._lock:
            self._status.tick_count += 1
            self._status.last_tick_at = datetime.now(timezone.utc).isoformat()
            self._status.last_session = getattr(result, "session", None)
            self._status.kill_switch_active = bool(getattr(result, "kill_switch_active", False))
            self._status.last_result = result.to_dict() if hasattr(result, "to_dict") else None


_scheduler: TradingScheduler | None = None
_scheduler_lock = threading.Lock()


def get_scheduler() -> TradingScheduler:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is None:
            _scheduler = TradingScheduler()
        return _scheduler
