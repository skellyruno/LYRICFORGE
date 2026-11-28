"""Candidate-only entry point, with offline probe restoration."""
from pathlib import Path
import sys
import desktop_launcher

if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="--restore-ffprobe":
        from studio_probe_delta import restore_probe
        try:restore_probe(Path(sys._MEIPASS)/"tools")
        except Exception:raise SystemExit(8)
        raise SystemExit(0)
    if len(sys.argv)>1 and sys.argv[1]=="--direct-media-proof":
        desktop_launcher.configure()
        from shared_media_proof import main
        try:main(sys.argv[2:],frozen=True)
        except Exception as exc:
            print("Direct media proof failed: "+repr(exc),file=sys.stderr,flush=True)
            raise SystemExit(7)
        raise SystemExit(0)
    raise SystemExit(desktop_launcher.main())
