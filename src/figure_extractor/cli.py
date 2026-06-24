from __future__ import annotations

import argparse
import json
from pathlib import Path

from .utils import ensure_local_source, is_url
from .pdf_cropper import extract_pdf_figures, crop_manual
from .html_extractor import extract_html_figures


def cmd_extract(args):
    out = Path(args.out)
    work = out / ".work"
    src_path, kind, resolved = ensure_local_source(args.source, work)

    result = {"source": args.source, "resolved": resolved, "kind": kind, "figures": []}

    if kind == "html" and args.prefer in {"auto", "html"}:
        figs = extract_html_figures(src_path, out, base_url=resolved if is_url(resolved) else None, make_sheet=True)
        result["figures"] = figs
        if figs and args.fallback != "pdf":
            (out / "manifest.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return
        # TODO: discover PDF links in HTML and fallback automatically. For now, report HTML extraction.
        if figs:
            (out / "manifest.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return

    if kind == "pdf":
        result = extract_pdf_figures(src_path, out, dpi=args.dpi, margin=args.margin, make_sheet=True, make_zip=args.zip)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return

    raise SystemExit(f"Unsupported or unresolved source kind: {kind}")


def cmd_crop(args):
    result = crop_manual(Path(args.pdf), page=args.page, bbox=args.bbox, out_path=Path(args.out), dpi=args.dpi)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def build_parser():
    p = argparse.ArgumentParser(prog="figure-extractor")
    sub = p.add_subparsers(dest="cmd", required=True)

    ex = sub.add_parser("extract", help="Extract figures from local PDF/HTML or URL")
    ex.add_argument("source", help="PDF/HTML file path or URL")
    ex.add_argument("--out", default="figures", help="Output directory")
    ex.add_argument("--dpi", type=int, default=300)
    ex.add_argument("--margin", type=float, default=8)
    ex.add_argument("--prefer", choices=["auto", "html", "pdf"], default="auto")
    ex.add_argument("--fallback", choices=["none", "pdf"], default="pdf")
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


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
