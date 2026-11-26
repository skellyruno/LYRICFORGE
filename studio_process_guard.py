"""Observe cancellation and no-progress deadlines independently of stdout."""
import time


def guard_process(process, stop, cancelled, progress_at, outcome, idle_limit, hard_limit=1800., clock=time.monotonic):
    started=clock()
    while not stop.is_set():
        if process.poll() is not None:return
        now=clock()
        reason='cancelled' if cancelled() else 'deadline' if now-started>=hard_limit else 'stalled' if now-progress_at[0]>=idle_limit else None
        if reason:
            outcome[0]=reason
            try:process.kill()
            except ProcessLookupError:pass
            return
        if stop.wait(.1):return
