"""Generate the Windows skull ICO, using Pillow (already a runtime dependency)."""
from PIL import Image, ImageDraw
from pathlib import Path

root = Path(__file__).resolve().parent
im = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
dark, green = "#111913", "#a0f58c"
d.rounded_rectangle((0, 0, 255, 255), radius=56, fill=dark)
d.ellipse((40, 28, 216, 188), fill=green)
d.rounded_rectangle((84, 144, 172, 220), radius=10, fill=green)
d.ellipse((64, 88, 116, 152), fill=dark)
d.ellipse((140, 88, 192, 152), fill=dark)
d.polygon([(128,144),(112,176),(144,176)], fill=dark)
for x in (104,128,152):
    d.line((x,196,x,220), fill=dark, width=10)
im.save(root / "static" / "skull.ico", sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
