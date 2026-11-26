import subprocess,sys,threading,time
import pytest
from studio_process_guard import guard_process


@pytest.mark.parametrize('cancel,expected',[(True,'cancelled'),(False,'stalled')])
def test_silent_process_guard(cancel,expected):
    process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],stdout=subprocess.PIPE)
    stop=threading.Event();outcome=[None];start=time.monotonic();progress=[start]
    worker=threading.Thread(target=guard_process,args=(process,stop,lambda:cancel and time.monotonic()-start>.22,progress,outcome,.45))
    worker.start()
    try:
        process.wait(timeout=5)
        assert outcome[0]==expected and process.returncode!=0
    finally:
        stop.set();worker.join(timeout=1)
        if process.poll() is None:process.kill();process.wait(timeout=5)
        process.stdout.close()
