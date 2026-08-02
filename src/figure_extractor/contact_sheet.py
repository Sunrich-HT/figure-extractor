from __future__ import annotations

import math
from pathlib import Path

import fitz

# Same signal the Pillow sheet carried: a bad crop should be visible at a glance.
STATUS_COLOURS = {
    "[failed]": (0.75, 0.0, 0.0),
    "[suspect]": (0.69, 0.38, 0.0),
}
BLACK = (0.0, 0.0, 0.0)


def make_contact_sheet(
    image_paths,
    dest: Path,
    title: str = "Extracted figures",
    thumb_w: int = 360,
    cols: int = 2,
    labels: list[str] | None = None,
):
    """Render a QA sheet so a human can spot bad crops in one glance.

    Composed with PyMuPDF rather than Pillow so that cropping a PDF needs only
    the one dependency — sandboxes often ship PyMuPDF and nothing else.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    items = []
    for i, p in enumerate(image_paths):
        p = Path(p)
        try:
            pix = fitz.Pixmap(str(p))
        except Exception:
            continue
        if pix.width <= 0 or pix.height <= 0:
            continue
        caption = labels[i] if labels and i < len(labels) else p.name
        items.append((caption, p, thumb_w, max(1, round(pix.height * thumb_w / pix.width))))
    if not items:
        return None

    pad, label_h, header = 16, 32, 46
    rows = math.ceil(len(items) / cols)
    row_heights = [
        max(h for _, _, _, h in items[r * cols:(r + 1) * cols]) + label_h + pad
        for r in range(rows)
    ]
    width = cols * thumb_w + (cols + 1) * pad
    height = header + sum(row_heights) + pad

    doc = fitz.open()
    try:
        page = doc.new_page(width=width, height=height)
        page.draw_rect(page.rect, color=None, fill=(1, 1, 1))
        page.insert_text((pad, header - 20), title[:160], fontsize=9)

        y = header
        for idx, (caption, path, tw, th) in enumerate(items):
            row, col = divmod(idx, cols)
            x = pad + col * (thumb_w + pad)
            low = caption.lower()
            colour = next((c for token, c in STATUS_COLOURS.items() if token in low), BLACK)
            page.insert_text((x, y + 12), caption[:60], fontsize=8, color=colour)
            page.insert_image(fitz.Rect(x, y + label_h, x + tw, y + label_h + th), filename=str(path))
            if col == cols - 1 or idx == len(items) - 1:
                y += row_heights[row]
        # 72 dpi renders the page one pixel per point, matching the layout above.
        page.get_pixmap(dpi=72).save(dest)
    finally:
        doc.close()
    return dest
