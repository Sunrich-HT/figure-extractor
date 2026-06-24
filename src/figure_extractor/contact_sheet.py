from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw
import math


def make_contact_sheet(image_paths, dest: Path, title="Extracted figures", thumb_w=360, cols=2):
    dest.parent.mkdir(parents=True, exist_ok=True)
    items = []
    for p in image_paths:
        p = Path(p)
        try:
            im = Image.open(p).convert("RGB")
        except Exception:
            continue
        scale = thumb_w / im.width
        im = im.resize((thumb_w, max(1, int(im.height * scale))))
        items.append((p, im))
    if not items:
        return None
    pad, label_h = 16, 32
    rows = math.ceil(len(items) / cols)
    row_heights = []
    for r in range(rows):
        row_heights.append(max((items[i][1].height for i in range(r * cols, min((r + 1) * cols, len(items)))), default=0) + label_h + pad)
    width = cols * thumb_w + (cols + 1) * pad
    height = 46 + sum(row_heights) + pad
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)
    draw.text((pad, 12), title, fill="black")
    y = 46
    for idx, (path, im) in enumerate(items):
        row, col = divmod(idx, cols)
        x = pad + col * (thumb_w + pad)
        draw.text((x, y), path.name[:55], fill="black")
        sheet.paste(im, (x, y + label_h))
        if col == cols - 1 or idx == len(items) - 1:
            y += row_heights[row]
    sheet.save(dest)
    return dest
