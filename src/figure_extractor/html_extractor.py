from __future__ import annotations

from pathlib import Path
from urllib.parse import urljoin
import re
import urllib.request
from bs4 import BeautifulSoup

from .contact_sheet import make_contact_sheet

IMG_ATTRS = ["src", "data-src", "data-original", "data-lazy-src", "data-hires", "data-full"]


def _best_from_srcset(srcset: str) -> str | None:
    candidates = []
    for part in srcset.split(','):
        bits = part.strip().split()
        if not bits:
            continue
        url = bits[0]
        score = 0
        if len(bits) > 1:
            token = bits[1]
            if token.endswith('w'):
                score = int(re.sub(r'\D', '', token) or 0)
            elif token.endswith('x'):
                score = int(float(token[:-1]) * 1000)
        candidates.append((score, url))
    if not candidates:
        return None
    return sorted(candidates)[-1][1]


def _download(url: str, dest: Path):
    req = urllib.request.Request(url, headers={"User-Agent": "figure-extractor/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
        ctype = r.headers.get("content-type", "")
    dest.write_bytes(data)
    return ctype


def extract_html_figures(html_path: Path, out_dir: Path, base_url: str | None = None, make_sheet=True):
    out_dir.mkdir(parents=True, exist_ok=True)
    html = html_path.read_text(errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    figures = []

    containers = soup.find_all("figure")
    if not containers:
        containers = soup.find_all(lambda tag: tag.name in {"div", "section"} and any(k in " ".join(tag.get("class", [])).lower() for k in ["figure", "fig", "image"]))

    seen = set()
    idx = 0
    for container in containers:
        img = container.find("img")
        if not img:
            pic = container.find("picture")
            img = pic.find("img") if pic else None
        if not img:
            continue
        img_url = None
        for source in container.find_all("source"):
            if source.get("srcset"):
                img_url = _best_from_srcset(source.get("srcset"))
        if not img_url and img.get("srcset"):
            img_url = _best_from_srcset(img.get("srcset"))
        if not img_url:
            for attr in IMG_ATTRS:
                if img.get(attr):
                    img_url = img.get(attr)
                    break
        if not img_url:
            continue
        img_url = urljoin(base_url or "", img_url)
        if img_url in seen:
            continue
        seen.add(img_url)
        caption_el = container.find("figcaption") or container.find(class_=re.compile("caption|legend", re.I))
        caption = caption_el.get_text(" ", strip=True) if caption_el else ""
        m = re.search(r"(?:Figure|Fig\.?|FIGURE)\s*(\d+)", caption)
        fig_num = int(m.group(1)) if m else idx + 1
        suffix = Path(img_url.split("?")[0]).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            suffix = ".png"
        dest = out_dir / f"fig{fig_num:02d}_html{suffix}"
        try:
            _download(img_url, dest)
        except Exception as e:
            figures.append({"figure": fig_num, "image_url": img_url, "caption": caption, "status": "download_failed", "error": str(e)})
            continue
        figures.append({"figure": fig_num, "image_url": img_url, "caption": caption, "output": str(dest), "method": "html-img", "status": "ok"})
        idx += 1

    image_paths = [f["output"] for f in figures if f.get("status") == "ok"]
    if make_sheet and image_paths:
        make_contact_sheet(image_paths, out_dir / "contact_sheet.jpg", title="HTML extracted figures")
    return figures
