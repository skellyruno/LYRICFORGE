"""CI-only Python DLL loader for source regression tests; never bundled."""
import os
from pathlib import Path

_handle=None
if os.name=="nt" and os.environ.get("SKELLY_CI_SHARED_DLL_DIR"):
    directory=Path(os.environ["SKELLY_CI_SHARED_DLL_DIR"]).resolve(strict=True)
    _handle=os.add_dll_directory(str(directory))
