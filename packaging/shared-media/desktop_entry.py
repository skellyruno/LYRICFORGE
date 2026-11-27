"""Entry point for the experimental shared-media Windows build only."""
import os
from pathlib import Path
import sys

# Only the app's own trusted installed directory, never an arbitrary user path.
_DLL_HANDLE = None
if os.name=="nt" and getattr(sys,"frozen",False):
    root=Path(sys._MEIPASS).resolve()
    _DLL_HANDLE=os.add_dll_directory(str(root))
    os.environ["PATH"]=str(root)+os.pathsep+os.environ.get("PATH","")

import desktop_launcher

if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="--shared-media-proof":
        desktop_launcher.configure()
        from shared_media_proof import main
        try:
            main(sys.argv[2:],frozen=True)
        except Exception as exc:
            print("Shared media proof failed: "+repr(exc),file=sys.stderr,flush=True)
            raise SystemExit(7)
        raise SystemExit(0)
    raise SystemExit(desktop_launcher.main())
