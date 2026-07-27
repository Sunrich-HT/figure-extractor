from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw


def make_contact_sheet(
    image_paths,
    dest: Path,
    title: str = "Extracted figures",
    thumb_w: int = 360,
    cols: int = 2,
    labels: list[str] | None = None,
):
    """Render a QA sheet so a human can spot bad crops in one glance."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    items = []
    for i, p in enumerate(image_paths):
        p = Path(p)
        try:
            im = Image.open(p).convert("RGB")
        except Exception:
            continue
        scale = thumb_w / im.width
        im = im.resize((thumb_w, max(1, int(im.height * scale))))
        caption = labels[i] if labels and i < len(labels) else p.name
        items.append((caption, im))
    if not items:
        return None

    pad, label_h = 16, 32
    rows = math.ceil(len(items) / cols)
    row_heights = []
    for r in range(rows):
        row_items = [items[i][1].height for i in range(r * cols, min((r + 1) * cols, len(items)))]
        row_heights.append((max(row_items) if row_items else 0) + label_h + pad)
    width = cols * thumb_w + (cols + 1) * pad
    height = 46 + sum(row_heights) + pad
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)
    draw.text((pad, 12), title[:160], fill="black")

    y = 46
    for idx, (caption, im) in enumerate(items):
        row, col = divmod(idx, cols)
        x = pad + col * (thumb_w + pad)
        colour = "black"
        low = caption.lower()
        if "[failed]" in low:
            colour = "#c00000"
        elif "[suspect]" in low:
            colour = "#b06000"
        draw.text((x, y), caption[:60], fill=colour)
        sheet.paste(im, (x, y + label_h))
        if col == cols - 1 or idx == len(items) - 1:
            y += row_heights[row]
    sheet.save(dest)
    return dest
