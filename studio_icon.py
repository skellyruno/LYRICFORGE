"""Generate the Windows multi-resolution ICO from the SkellyHub ecosystem mark."""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent
SIZES = (16, 24, 32, 48, 64, 128, 256)


def generate(source=ROOT / "static" / "skellyhub-skull.png",
             target=ROOT / "static" / "skull.ico"):
    with Image.open(source) as mark:
        if mark.format != "PNG" or mark.width != mark.height:
            raise ValueError("The shared mark must be a square PNG")
        rgba = mark.convert("RGBA")
        # Explicit resampling keeps the same art across all Windows icon sizes.
        image = rgba.resize((256, 256), Image.Resampling.LANCZOS)
        image.save(target, format="ICO", sizes=[(n, n) for n in SIZES])


if __name__ == "__main__":
    generate()
