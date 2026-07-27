from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

from .html_extractor import extract_html_figures
from .pdf_cropper import crop_manual, extract_pdf_figures
from .utils import HTML, PDF, SourceError, ensure_local_source, is_url

ALL_KINDS = ("figure", "table", "algorithm")
ALL_TIERS = ("A", "B", "C")


def _discover_pdf_link(html_path: Path, base_url: str | None) -> str | None:
    """Find a PDF the HTML page points at, for the HTML -> PDF fallback.

    The previous CLI advertised ``--fallback pdf`` and shipped a ``# TODO``
    where the implementation should have been, so the flag did nothing.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:  # pragma: no cover
        return None
    soup = BeautifulSoup(html_path.read_text(errors="ignore"), "html.parser")

    for link in soup.find_all("link"):
        if (link.get("type") or "").lower() == "application/pdf" and link.get("href"):
            return urljoin(base_url or "", link["href"])
    for meta in soup.find_all("meta"):
        name = (meta.get("name") or meta.get("property") or "").lower()
        if name in {"citation_pdf_url", "eprints.document_url"} and meta.get("content"):
            return urljoin(base_url or "", meta["content"])
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(r"\.pdf($|\?)", href, re.I) or re.search(r"/pdf(/|\?|$)", href, re.I):
            return urljoin(base_url or "", href)
    return None


def _parse_csv(value: str, allowed: tuple[str, ...], what: str) -> tuple[str, ...]:
    items = tuple(v.strip() for v in value.split(",") if v.strip())
    bad = [i for i in items if i not in allowed]
    if bad:
        raise SystemExit(f"unknown {what}: {', '.join(bad)} (choose from {', '.join(allowed)})")
    return items or allowed


def cmd_extract(args) -> int:
    out = Path(args.out)
    work = out / ".work"
    kinds = _parse_csv(args.kinds, ALL_KINDS, "kind")
    tiers = _parse_csv(args.tiers, ALL_TIERS, "tier")

    try:
        src = ensure_local_source(args.source, work)
    except SourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if src.note:
        print(f"note: {src.note}", file=sys.stderr)

    if src.kind == HTML and args.prefer in {"auto", "html"}:
        base = src.resolved_url if is_url(src.resolved_url) else None
        manifest = extract_html_figures(src.path, out, base_url=base, make_sheet=True)
        got = manifest["counts"]["rendered"]
        if got and args.prefer == "html":
            print(json.dumps(manifest, indent=2, ensure_ascii=False))
            return 0
        if got and args.fallback != "pdf":
            print(json.dumps(manifest, indent=2, ensure_ascii=False))
            return 0
        if not got or args.fallback == "pdf":
            pdf_url = _discover_pdf_link(src.path, base)
            if pdf_url and (not got or args.prefer == "auto"):
                print(f"note: falling back to PDF at {pdf_url}", file=sys.stderr)
                try:
                    pdf_src = ensure_local_source(pdf_url, work)
                except SourceError as exc:
                    print(f"note: PDF fallback failed ({exc}); keeping HTML result", file=sys.stderr)
                    print(json.dumps(manifest, indent=2, ensure_ascii=False))
                    return 0 if got else 1
                if pdf_src.kind == PDF:
                    manifest = extract_pdf_figures(
                        pdf_src.path, out, dpi=args.dpi, margin=args.margin,
                        make_sheet=True, make_zip=args.zip, kinds=kinds, tiers=tiers,
                    )
                    print(json.dumps(manifest, indent=2, ensure_ascii=False))
                    return 0
            print(json.dumps(manifest, indent=2, ensure_ascii=False))
            return 0 if got else 1

    if src.kind == PDF:
        manifest = extract_pdf_figures(
            src.path, out, dpi=args.dpi, margin=args.margin,
            make_sheet=True, make_zip=args.zip, kinds=kinds, tiers=tiers,
        )
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
        return 0 if manifest["counts"]["rendered"] else 1

    print(f"error: cannot extract from source of kind {src.kind!r}", file=sys.stderr)
    return 2


def cmd_crop(args) -> int:
    try:
        result = crop_manual(
            Path(args.pdf), page=args.page, bbox=args.bbox, out_path=Path(args.out), dpi=args.dpi
        )
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="figure-extractor",
        description="Extract figures and tables from PDFs, arXiv/OpenReview/ACL links, and HTML articles.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    ex = sub.add_parser("extract", help="Extract from a local PDF/HTML file or a URL")
    ex.add_argument("source", help="PDF/HTML path, or arXiv / OpenReview / ACL / PDF / article URL")
    ex.add_argument("--out", default="figures", help="Output directory")
    ex.add_argument("--dpi", type=int, default=300)
    ex.add_argument("--margin", type=float, default=8)
    ex.add_argument("--prefer", choices=["auto", "html", "pdf"], default="auto")
    ex.add_argument("--fallback", choices=["none", "pdf"], default="pdf")
    ex.add_argument("--kinds", default="figure,table",
                    help=f"Comma-separated subset of {','.join(ALL_KINDS)} (default: figure,table)")
    ex.add_argument("--tiers", default="A,B,C",
                    help="Comma-separated triage tiers to render (default: A,B,C)")
    ex.add_argument("--zip", action="store_true")
    ex.set_defaults(func=cmd_extract)

    cr = sub.add_parser("crop", help="Manually crop a PDF page by bbox")
    cr.add_argument("pdf")
    cr.add_argument("--page", type=int, required=True)
    cr.add_argument("--bbox", required=True, help="x0,y0,x1,y1 in PDF points")
    cr.add_argument("--out", required=True)
    cr.add_argument("--dpi", type=int, default=300)
    cr.set_defaults(func=cmd_crop)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
