"""Restore the original SkellHub icon; never draw a substitute at build time."""
from pathlib import Path
from hashlib import sha256
from io import BytesIO
from PIL import Image

root = Path(__file__).resolve().parent / "static"
EXPECTED = "c472c19bbf94f3fdac172c1eeff7322d5e7dc2093e98cc095f2380a3e9bd82bb"
data = (root / "skellyhub.ico").read_bytes()
if sha256(data).hexdigest() != EXPECTED:
    raise RuntimeError("Original SkellHub icon hash mismatch")
with Image.open(BytesIO(data)) as image:
    if image.ico.sizes() != {(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)}:
        raise RuntimeError("Missing original Windows icon resolutions")
target = root / "skull.ico"
if not target.exists() or target.read_bytes() != data:
    temporary = target.with_suffix(".ico.tmp")
    temporary.write_bytes(data)
    temporary.replace(target)
print("Original SkellHub icon verified:", EXPECTED)
