"""Tests for the background trading scheduler (#1)."""

import tempfile
import time as _time

import pytest

import backend.database as db


@pytest.fixture(autouse=True)
def temp_db():
    prev = db.DB_PATH
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db.DB_PATH = type(prev)(tmp.name)
    db.init_db()
    yield
    db.DB_PATH = prev


from backend.services.scheduler import (  # noqa: E402
    STATE_PAUSED,
    STATE_RUNNING,
    STATE_STOPPED,
    TradingScheduler,
)


class FakeTickResult:
    def __init__(self, n):
        self.session = "regular"
        self.kill_switch_active = False
        self._n = n

    def to_dict(self):
        return {"session": self.session, "tick": self._n}


class FakeRunner:
    def __init__(self):
        self.ticks = 0

    def tick(self):
        self.ticks += 1
        return FakeTickResult(self.ticks)


def _cfg(interval=1):
    return {"scheduler": {"enabled": True, "interval_seconds": interval},
            "stocks_in_play_orb_v1": {}}


class TestRunOnce:
    def test_run_once_updates_status(self):
        runner = FakeRunner()
        sched = TradingScheduler(runner_factory=lambda cfg: runner)
        result = sched.run_once(_cfg())
        assert result["tick"] == 1
        assert sched.status().tick_count == 1
        assert sched.status().last_session == "regular"


class TestLifecycle:
    def test_start_pause_resume_stop(self):
        runner = FakeRunner()
        sched = TradingScheduler(runner_factory=lambda cfg: runner)
        assert sched.status().state == STATE_STOPPED

        sched.start(_cfg(interval=1))
        assert sched.status().state == STATE_RUNNING
        sched.pause()
        assert sched.status().state == STATE_PAUSED
        sched.resume()
        assert sched.status().state == STATE_RUNNING
        sched.stop()
        assert sched.status().state == STATE_STOPPED

    def test_thread_ticks_then_stops(self):
        runner = FakeRunner()
        sched = TradingScheduler(runner_factory=lambda cfg: runner)
        sched.start(_cfg(interval=1))
        _time.sleep(0.8)  # first tick fires immediately
        sched.stop()
        assert runner.ticks >= 1
        # No further ticks after stop.
        ticks_after_stop = runner.ticks
        _time.sleep(0.6)
        assert runner.ticks == ticks_after_stop

    def test_double_start_is_idempotent(self):
        sched = TradingScheduler(runner_factory=lambda cfg: FakeRunner())
        sched.start(_cfg())
        first_thread = sched._thread
        sched.start(_cfg())
        assert sched._thread is first_thread
        sched.stop()
