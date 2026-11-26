"""Make-tool jobs honor the Eco / Balanced / Turbo choice: priority and thread count."""
import asyncio
import io

import pytest

import server
import studio_performance as perf
from test_quick_tools import Inline, make_video, needs_ffmpeg, up


@pytest.fixture
def data(tmp_path, monkeypatch):
    """Like the shared fixture, but the performance mode is left as the request asked for it."""
    monkeypatch.setattr(server, "DATA", tmp_path / "data")
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(server, "executor", Inline())
    server.jobs.clear()
    return tmp_path


@needs_ffmpeg
@pytest.mark.parametrize("mode", ["eco", "balanced", "turbo"])
def test_tool_jobs_carry_the_requested_mode(data, mode):
    server.request_perf_mode.set(mode)
    try:
        made = asyncio.run(server.quick_start("mute", {}, {"video": [up(make_video(data / "v.mp4", 2))]}))
    finally:
        server.request_perf_mode.set("balanced")
    assert server.jobs[made["job_id"]]["performance_mode"] == mode and server.jobs[made["job_id"]]["status"] == "done"


def test_an_unknown_mode_falls_back_to_balanced(data):
    server.request_perf_mode.set("warp-speed")
    try:
        job = server.register_job(server.demo_project("mute", "x", {}, {"options": {}}), "mute", server.sanitize_settings({"performanceMode": server.request_perf_mode.get()}))
    finally:
        server.request_perf_mode.set("balanced")
    assert server.jobs[job]["performance_mode"] == "balanced"


class FakeProcess:
    returncode = 0

    def __init__(self):
        self.stdout = io.StringIO("progress=end\n")

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return 0

    def kill(self):
        pass


@pytest.mark.parametrize("mode,low", [("eco", True), ("turbo", False)])
def test_ffmpeg_is_given_a_thread_cap_and_eco_runs_at_low_priority(data, monkeypatch, mode, low):
    seen = {}

    def fake_popen(args, **kw):
        seen["args"], seen["kw"] = args, kw
        return FakeProcess()
    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)
    job = "jobx"
    server.jobs[job] = {"id": job, "performance_mode": mode, "status": "rendering"}
    server.render_with_progress(["ffmpeg", "-y", "-i", "in.mp4", "out.mp4"], data, job, 1.0)
    args = seen["args"]
    assert args[-1] == "out.mp4" and args[-3] == "-threads" and int(args[-2]) == perf.profile_config(mode)["threads"]
    monkeypatch.setattr(perf.os, "name", "nt", raising=False)
    assert bool(perf.windows_child_options(perf.profile_config(mode)["low_priority"]).get("creationflags", 0) & getattr(server.subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x4000)) == low if hasattr(server.subprocess, "CREATE_NO_WINDOW") else True


def test_commands_that_already_set_threads_are_left_alone(data, monkeypatch):
    seen = {}
    monkeypatch.setattr(server.subprocess, "Popen", lambda args, **kw: (seen.update(args=args), FakeProcess())[1])
    server.jobs["jy"] = {"id": "jy", "performance_mode": "balanced", "status": "rendering"}
    server.render_with_progress(["ffmpeg", "-y", "-threads", "3", "out.mp4"], data, "jy", 1.0)
    assert seen["args"].count("-threads") == 1 and seen["args"][seen["args"].index("-threads") + 1] == "3"


def test_a_fresh_upload_is_linked_not_copied_and_other_files_are_copied(data):
    scratch = data / "data" / "upload-abc"
    scratch.mkdir(parents=True)
    fresh = scratch / "input.mp4"
    fresh.write_bytes(b"x" * 1000)
    brand = data / "logo.png"
    brand.write_bytes(b"logo")
    target_a, target_b = data / "a.mp4", data / "b.png"
    server.place_file(fresh, target_a)
    server.place_file(brand, target_b)
    assert target_a.samefile(fresh), "no second copy of an upload"
    assert not target_b.samefile(brand) and target_b.read_bytes() == b"logo"
    import shutil
    shutil.rmtree(scratch)
    assert target_a.read_bytes() == b"x" * 1000, "removing the scratch folder leaves the project's file intact"


def test_a_cancelled_render_kills_then_reaps_ffmpeg_and_closes_its_pipe(data, monkeypatch):
    events = []

    class Hung:
        def __init__(self):
            self.stdout = io.StringIO("frame=1\nout_time=00:00:00.5\n")
            self.reaped = False

        def poll(self):
            return 0 if self.reaped else None

        def kill(self):
            events.append("kill")

        def wait(self, timeout=None):
            events.append("wait")
            self.reaped = True
            return -9
    proc = Hung()
    monkeypatch.setattr(server.subprocess, "Popen", lambda args, **kw: proc)
    server.jobs["jc"] = {"id": "jc", "performance_mode": "balanced", "status": "rendering", "cancel": True}
    monkeypatch.setattr(server, "cancel_requested", lambda job_id: True)
    with pytest.raises(server.JobCancelled):
        server.render_with_progress(["ffmpeg", "-y", "out.mp4"], data, "jc", 1.0)
    assert events[0] == "kill" and events[-1] == "wait" and proc.stdout.closed, events


def test_silent_child_is_cancelled_without_progress(data):
    import sys,threading,time
    job='silent'
    server.jobs[job]={'id':job,'performance_mode':'balanced','status':'rendering'}
    def cancel():
        with server.job_lock:server.jobs[job]['cancel']=True
    timer=threading.Timer(.25,cancel);timer.start()
    started=time.monotonic()
    try:
        with pytest.raises(server.JobCancelled):
            server.render_with_progress([sys.executable,'-c','import time;time.sleep(60)','-threads','1'],data,job,1.)
        assert time.monotonic()-started<5.
    finally:timer.cancel();timer.join()
