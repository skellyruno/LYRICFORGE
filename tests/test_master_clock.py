import shutil,subprocess
import pytest
from studio_master_clock import repair_legacy_master,probe


def test_legacy_priming_repair_actual_packets(tmp_path):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):pytest.skip('FFmpeg required')
    old=tmp_path/'old.mp4';new=tmp_path/'new.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=red:s=128x72:r=60:d=1','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=1','-c:v','libx264','-bf','0','-video_track_timescale','60000','-c:a','aac','-use_editlist','0','-t','1',str(old)],check=True,capture_output=True)
    report=repair_legacy_master(old,new);assert report['frames']==60 and report['video_and_audio_packet_payloads_identical']
    with pytest.raises(FileExistsError):repair_legacy_master(old,new)
    with pytest.raises(ValueError):repair_legacy_master(new,tmp_path/'bad.mp4')
