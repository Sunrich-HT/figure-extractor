from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse, urljoin
import mimetypes
import re
import shutil
import urllib.request


def is_url(source: str) -> bool:
    return source.startswith("http://") or source.startswith("https://")


def normalize_arxiv_url(url: str) -> str:
    # https://arxiv.org/abs/2606.23443 -> https://arxiv.org/pdf/2606.23443
    m = re.match(r"https?://arxiv\.org/abs/([^?#]+)", url)
    if m:
        return f"https://arxiv.org/pdf/{m.group(1)}"
    return url


def sniff_kind(source: str) -> str:
    lower = source.lower().split("?")[0]
    if lower.endswith(".pdf") or "/pdf/" in lower:
        return "pdf"
    if lower.endswith(".html") or lower.endswith(".htm"):
        return "html"
    if is_url(source):
        return "url"
    path = Path(source)
    if path.suffix.lower() == ".pdf":
        return "pdf"
    if path.suffix.lower() in {".html", ".htm"}:
        return "html"
    return "unknown"


def download_url(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "figure-extractor/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
        ctype = r.headers.get("content-type", "")
    dest.write_bytes(data)
    return dest


def ensure_local_source(source: str, workdir: Path) -> tuple[Path, str, str]:
    """Return (local_path, kind, resolved_url_or_path)."""
    workdir.mkdir(parents=True, exist_ok=True)
    if is_url(source):
        url = normalize_arxiv_url(source)
        kind = sniff_kind(url)
        suffix = ".pdf" if kind == "pdf" else ".html"
        local = workdir / ("source" + suffix)
        download_url(url, local)
        if local.read_bytes()[:5] == b"%PDF-":
            return local, "pdf", url
        return local, "html", url
    path = Path(source)
    kind = sniff_kind(source)
    return path, kind, str(path)


def safe_name(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_")
    return text[:120] or "file"
