"""Figure extraction from HTML article pages.

The failure this module exists to prevent is silent loss. The previous version
derived a filename from ``int(re.search(r'Figure\\s*(\\d+)', caption))``, so
``Figure 2.1`` through ``Figure 2.4`` all became ``fig02_html.png`` and
overwrote one another, while ``Figure B.1`` matched nothing and fell back to a
running index unrelated to the paper's own numbering. On a real arXiv HTML
paper that lost eleven of thirty-two figures, and the manifest still reported
every one of them as ``ok``.

Identity now comes from :mod:`figure_extractor.captions`, filenames are
collision-checked, and anything dropped is counted and named.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

from .minisoup import BeautifulSoup as _MiniSoup

from .captions import parse_label
from .contact_sheet import make_contact_sheet
from .utils import USER_AGENT

IMG_ATTRS = ["src", "data", "data-src", "data-original", "data-lazy-src", "data-hires", "data-full", "data-image"]

IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif", "image/svg+xml", "image/avif"}
EXT_BY_TYPE = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
    "image/avif": ".avif",
}

# Decorative furniture that is never a paper figure.
JUNK_URL_HINTS = ("pixel", "tracking", "beacon", "spacer", "1x1", "logo", "avatar", "icon", "badge", "sprite")


def _soup(markup: str):
    """Prefer beautifulsoup4 when it is installed; fall back to the stdlib.

    bs4 handles broken markup better, but requiring it would put HTML sources
    out of reach of a runtime that cannot install anything — which is precisely
    where a saved page with inline images is the only source available.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return _MiniSoup(markup)
    return BeautifulSoup(markup, "html.parser")


def _short_url(url: str, limit: int = 120) -> str:
    """A URL safe to put in a report.

    Inline `data:` images can be hundreds of kilobytes; echoing one whole into
    the manifest makes the report unreadable and larger than the figure.
    """
    if url.startswith("data:"):
        head = url.split(",", 1)[0]
        return f"{head},<{len(url)} bytes inline>"
    return url if len(url) <= limit else url[: limit - 3] + "..."


def _best_from_srcset(srcset: str) -> str | None:
    """Highest-resolution candidate in a srcset attribute."""
    best: tuple[float, str] | None = None
    for part in srcset.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        url, score = bits[0], 0.0
        if len(bits) > 1:
            token = bits[1]
            digits = re.sub(r"[^\d.]", "", token) or "0"
            try:
                score = float(digits) * (1000 if token.endswith("x") else 1)
            except ValueError:
                score = 0.0
        if best is None or score > best[0]:
            best = (score, url)
    return None if best is None else best[1]


def _download(url: str, timeout: int = 60) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), (r.headers.get("content-type") or "").split(";")[0].strip().lower()


def _pick_url(container, img) -> str | None:
    for source in container.find_all("source"):
        if source.get("srcset"):
            candidate = _best_from_srcset(source["srcset"])
            if candidate:
                return candidate
    if img.get("srcset"):
        candidate = _best_from_srcset(img["srcset"])
        if candidate:
            return candidate
    for attr in IMG_ATTRS:
        if img.get(attr):
            return img[attr]
    return None


def _caption_of(container) -> str:
    el = container.find("figcaption") or container.find(class_=re.compile("caption|legend", re.I))
    return el.get_text(" ", strip=True) if el else ""


def _table_to_markdown(table) -> str:
    """Render an HTML <table> as Markdown, preserving the numbers.

    Tables carry the results a paper actually rests on. When a page ships them
    as text rather than as an image there is nothing to crop, but discarding
    them would throw away the strongest evidence on the page.
    """
    if table is None:
        return ""
    rows = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append(cells)
    if len(rows) < 2:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(out)


def _containers(soup):
    """Figure containers, preferring semantic markup.

    The class-name fallback is deliberately kept out of the way: on content
    sites ``div[class*=fig|image]`` matches banners, thumbnails and layout
    wrappers by the dozen, which is how a single paper ends up "yielding"
    ninety-odd figures.
    """
    figures = soup.find_all("figure")
    if figures:
        return figures, "figure"
    guessed = soup.find_all(
        lambda tag: tag.name in {"div", "section"}
        and any(k in " ".join(tag.get("class", []) or []).lower() for k in ("figure", "fig-", "fig_", "image"))
    )
    return guessed, "class-heuristic"


def extract_html_figures(
    html_path: Path,
    out_dir: Path,
    base_url: str | None = None,
    make_sheet: bool = True,
    min_bytes: int = 3000,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    soup = _soup(html_path.read_text(errors="ignore"))
    containers, strategy = _containers(soup)

    figures: list[dict] = []
    used_names: dict[str, int] = {}
    seen_urls: set[str] = set()
    seen_bytes: set[bytes] = set()
    tables_md: list[dict] = []
    inline_svgs: list[dict] = []
    fallback_index = 0

    # Every container is accounted for. A container that yields no file must say
    # why, otherwise "32 found, 25 written" reads as success instead of a leak.
    dropped: list[dict] = []

    for container in containers:
        img = container.find("img")
        if img is None:
            picture = container.find("picture")
            img = picture.find("img") if picture else None
        if img is None:
            # Inline vector art: the figure is the markup, with no URL to fetch.
            # Serialising it keeps the graphic instead of recording a loss.
            svg = container.find("svg")
            if svg is not None:
                caption = _caption_of(container)
                label = parse_label(caption)
                stem = label.slug if label else f"inlinesvg{len(inline_svgs) + 1:02d}"
                dest = out_dir / f"{stem}.svg"
                dest.write_text(str(svg), encoding="utf-8")
                inline_svgs.append({
                    "label": label.display if label else None,
                    "kind": label.kind if label else "figure",
                    "number": label.number if label else None,
                    "caption": caption,
                    "output": str(dest),
                    "method": "html-inline-svg",
                    "status": "ok",
                    "format": "svg",
                })
                continue
            # <object>/<embed> point at an external asset the same way <img>
            # does, so hand it to the normal download path below.
            embed = container.find(["object", "embed"])
            if embed is not None and (embed.get("data") or embed.get("src")):
                img = embed

        if img is None:
            caption = _caption_of(container)
            label = parse_label(caption)
            table_md = _table_to_markdown(container.find("table"))
            if table_md:
                # A results table rendered as HTML text is evidence, not noise.
                # There is no bitmap to crop, but the numbers are the whole point
                # of the table, so capture them rather than logging a loss.
                stem = label.slug if label else f"htmltable{len(tables_md) + 1:02d}"
                dest = out_dir / f"{stem}.md"
                dest.write_text(
                    (f"# {label.display}\n\n" if label else "") + f"{caption}\n\n{table_md}\n",
                    encoding="utf-8",
                )
                tables_md.append({
                    "label": label.display if label else None,
                    "kind": "table",
                    "number": label.number if label else None,
                    "caption": caption,
                    "output": str(dest),
                    "method": "html-text-table",
                    "status": "ok",
                    "format": "markdown",
                })
                continue
            dropped.append({
                "label": label.display if label else None,
                "caption": caption,
                "reason": "container holds no <img> and no <table>",
            })
            continue

        raw_url = _pick_url(container, img)
        if not raw_url:
            figures.append({"label": None, "status": "failed", "quality_reasons": ["no resolvable image URL"]})
            continue

        img_url = urljoin(base_url, raw_url) if base_url else raw_url
        if not img_url.lower().startswith(("http://", "https://", "data:")):
            figures.append({"image_url": _short_url(img_url), "status": "failed", "quality_reasons": ["unresolved relative URL (no base)"]})
            continue
        if img_url in seen_urls:
            dropped.append({"image_url": _short_url(img_url), "reason": "same image URL already taken by an earlier container"})
            continue
        seen_urls.add(img_url)
        junk = next((h for h in JUNK_URL_HINTS if h in img_url.lower()), None)
        if junk:
            dropped.append({"image_url": _short_url(img_url), "reason": f"URL looks like page furniture (matched {junk!r})"})
            continue

        caption = _caption_of(container)
        label = parse_label(caption)
        if label is not None:
            stem = label.slug
            display = label.display
        else:
            fallback_index += 1
            stem = f"unlabelled{fallback_index:02d}"
            display = f"(unlabelled #{fallback_index})"

        entry: dict = {
            "label": display,
            "kind": label.kind if label else "unknown",
            "number": label.number if label else None,
            "caption": caption,
            "image_url": _short_url(img_url),
            "method": f"html-{strategy}",
        }

        try:
            data, ctype = _download(img_url)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
            entry.update(status="failed", output=None, quality_reasons=[f"download failed: {exc}"])
            figures.append(entry)
            continue

        # A server that answers an image request with HTML is serving an error
        # page or a consent wall. Writing those bytes to a .png would produce a
        # file that only fails much later, somewhere less informative.
        if ctype and ctype not in IMAGE_TYPES and not ctype.startswith("image/"):
            entry.update(status="failed", output=None, quality_reasons=[f"server returned {ctype!r}, not an image"])
            figures.append(entry)
            continue
        if len(data) < min_bytes:
            entry.update(status="failed", output=None, quality_reasons=[f"only {len(data)} bytes (below {min_bytes})"])
            figures.append(entry)
            continue
        if data in seen_bytes:
            entry.update(status="skipped", output=None, quality_reasons=["duplicate of an earlier image"])
            figures.append(entry)
            continue
        seen_bytes.add(data)

        suffix = EXT_BY_TYPE.get(ctype) or (Path(img_url.split("?")[0]).suffix.lower() or ".png")
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".avif"}:
            suffix = ".png"

        # Distinct figures must never share a filename. Anything that would
        # collide gets a suffix and says so, instead of overwriting in silence.
        name = f"{stem}_html"
        used_names[name] = used_names.get(name, 0) + 1
        if used_names[name] > 1:
            name = f"{name}_dup{used_names[name]}"
            entry.setdefault("quality_reasons", []).append("duplicate label in source; filename disambiguated")
        dest = out_dir / f"{name}{suffix}"
        dest.write_bytes(data)

        entry.update(status="ok", output=str(dest), bytes=len(data))
        entry.setdefault("quality_reasons", [])
        figures.append(entry)

    figures.extend(tables_md)
    figures.extend(inline_svgs)
    rendered = [
        f for f in figures
        if f.get("status") == "ok" and f.get("format") not in {"markdown", "svg"}
    ]
    counts = {
        "containers_found": len(containers),
        "considered": len(figures),
        "text_tables": len(tables_md),
        "inline_svgs": len(inline_svgs),
        "rendered": len(rendered),
        "ok": len(rendered),
        "failed": sum(1 for f in figures if f.get("status") == "failed"),
        "skipped": sum(1 for f in figures if f.get("status") == "skipped"),
        "dropped_before_download": len(dropped),
        "unlabelled": fallback_index,
    }
    # Invariant: nothing vanishes without a recorded reason.
    assert counts["containers_found"] == counts["considered"] + counts["dropped_before_download"], (
        f"{counts['containers_found']} containers != "
        f"{counts['considered']} considered + {counts['dropped_before_download']} dropped"
    )
    manifest = {
        "source": str(html_path),
        "kind": "html",
        "base_url": base_url,
        "strategy": strategy,
        "counts": counts,
        "figures": figures,
        "dropped": dropped,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if make_sheet and rendered:
        make_contact_sheet(
            [f["output"] for f in rendered],
            out_dir / "contact_sheet.jpg",
            title=f"HTML figures — {counts['rendered']}/{counts['containers_found']} containers rendered",
            labels=[f"{f['label']}  [{f['status']}]" for f in rendered],
        )
    return manifest
