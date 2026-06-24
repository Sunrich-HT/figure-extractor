from __future__ import annotations

from pathlib import Path
import json
import re
import zipfile
import fitz

from .contact_sheet import make_contact_sheet

CAPTION_RE = re.compile(r"^(?:Figure|Fig\.?|FIGURE)\s*(\d+)\s*[\.:]", re.I)


def _text_blocks(page):
    d = page.get_text("dict")
    blocks = []
    for b in d.get("blocks", []):
        if b.get("type") != 0:
            continue
        txt = []
        for line in b.get("lines", []):
            for span in line.get("spans", []):
                txt.append(span.get("text", ""))
        t = re.sub(r"\s+", " ", "".join(txt)).strip()
        if t:
            blocks.append((fitz.Rect(b["bbox"]), t))
    return blocks


def _union(rects):
    if not rects:
        return None
    r = fitz.Rect(rects[0])
    for x in rects[1:]:
        r |= fitz.Rect(x)
    return r


def _find_captions(doc):
    captions = []
    for pi, page in enumerate(doc):
        for rect, text in _text_blocks(page):
            m = CAPTION_RE.search(text)
            if m:
                captions.append({"figure": int(m.group(1)), "page_index": pi, "caption_rect": rect, "caption": text})
    # Deduplicate by figure number: keep first block by page/y.
    dedup = {}
    for c in sorted(captions, key=lambda x: (x["figure"], x["page_index"], x["caption_rect"].y0)):
        dedup.setdefault(c["figure"], c)
    return [dedup[k] for k in sorted(dedup)]


def _infer_bbox(page, caption_rect, margin=8):
    blocks = _text_blocks(page)
    cap_y = caption_rect.y0
    page_rect = page.rect
    primitives = []
    for d in page.get_drawings():
        r = fitz.Rect(d["rect"])
        if r.is_empty or r.width < 1 or r.height < 1:
            continue
        if r.y1 < cap_y - 2 and r.y0 > 35:
            # Ignore running header line.
            if r.height < 2 and r.y0 < 60:
                continue
            primitives.append(r)
    for info in page.get_image_info(xrefs=True):
        r = fitz.Rect(info["bbox"])
        if r.y1 < cap_y - 2 and r.y0 > 35:
            primitives.append(r)
    graphic = _union(primitives)
    if graphic is None:
        graphic = fitz.Rect(45, 60, page_rect.width - 45, cap_y - 4)

    # Include text labels likely inside the figure band.
    band = fitz.Rect(
        max(35, graphic.x0 - 25),
        max(40, graphic.y0 - 35),
        min(page_rect.width - 35, graphic.x1 + 25),
        min(cap_y - 2, graphic.y1 + 35),
    )
    text_rects = []
    for r, t in blocks:
        if r.y1 < cap_y - 2 and r.y0 > 35:
            if r.intersects(band):
                # Avoid pulling in paragraphs.
                if len(t) > 140 and r.height < 20:
                    continue
                text_rects.append(r)
    crop = _union([graphic] + text_rects) or graphic
    crop.x0 = max(35, crop.x0 - margin)
    crop.x1 = min(page_rect.width - 35, crop.x1 + margin)
    crop.y0 = max(40, crop.y0 - margin)
    crop.y1 = min(cap_y - 3, crop.y1 + margin)
    return crop


def extract_pdf_figures(pdf_path: Path, out_dir: Path, dpi=300, margin=8, make_sheet=True, make_zip=True):
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    captions = _find_captions(doc)
    figures = []
    image_paths = []
    for c in captions:
        fig_num = c["figure"]
        page = doc[c["page_index"]]
        crop = _infer_bbox(page, c["caption_rect"], margin=margin)
        pix = page.get_pixmap(dpi=dpi, clip=crop, alpha=False)
        out_path = out_dir / f"fig{fig_num:02d}_p{c['page_index'] + 1:02d}.png"
        pix.save(out_path)
        image_paths.append(out_path)
        figures.append({
            "figure": fig_num,
            "page": c["page_index"] + 1,
            "caption": c["caption"],
            "bbox": [round(crop.x0, 2), round(crop.y0, 2), round(crop.x1, 2), round(crop.y1, 2)],
            "output": str(out_path),
            "method": "pdf-caption-bbox-render-crop",
            "dpi": dpi,
            "status": "ok",
        })
    manifest = {"source_pdf": str(pdf_path), "dpi": dpi, "figures": figures}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    if make_sheet and image_paths:
        make_contact_sheet(image_paths, out_dir / "contact_sheet.jpg", title="PDF caption-bbox crops")
    if make_zip:
        zip_path = out_dir / "figures.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for p in image_paths:
                z.write(p, p.name)
            z.write(out_dir / "manifest.json", "manifest.json")
            if (out_dir / "contact_sheet.jpg").exists():
                z.write(out_dir / "contact_sheet.jpg", "contact_sheet.jpg")
        manifest["zip"] = str(zip_path)
    return manifest


def crop_manual(pdf_path: Path, page: int, bbox: str, out_path: Path, dpi=300):
    doc = fitz.open(pdf_path)
    vals = [float(x) for x in bbox.split(",")]
    if len(vals) != 4:
        raise ValueError("bbox must be x0,y0,x1,y1")
    rect = fitz.Rect(*vals)
    pix = doc[page - 1].get_pixmap(dpi=dpi, clip=rect, alpha=False)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pix.save(out_path)
    return {"page": page, "bbox": vals, "output": str(out_path), "dpi": dpi}
