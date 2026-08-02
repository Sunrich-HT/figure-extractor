"""The paths that must survive a runtime with no network and no pip.

A sandbox typically ships PyMuPDF and nothing else, cannot reach PyPI or GitHub,
and cannot install this package. Cropping a PDF has to work anyway, so these
tests deny Pillow and beautifulsoup4 and check the tool still delivers crops.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import fitz
import pytest

ROOT = Path(__file__).resolve().parent.parent
STANDALONE = ROOT / "standalone" / "figure_extractor_standalone.py"
BUILDER = ROOT / "tools" / "build_standalone.py"

# Installed in the child interpreter to make the optional dependencies vanish.
BLOCK_OPTIONAL_DEPS = """
import sys

class _Deny:
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in {'PIL', 'bs4'}:
            raise ImportError(f'{name} is unavailable in this test runtime')
        return None

sys.meta_path.insert(0, _Deny())
"""


def _make_pdf(path):
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.draw_rect(fitz.Rect(80, 60, 500, 220), color=(0, 0, 0), fill=(0.2, 0.4, 0.9))
    page.insert_text((80, 250), "Figure 1: A synthetic figure.", fontsize=9)
    page.insert_text((80, 300), "We refer to Figure 1 throughout this paragraph, "
                                "which is long enough to read as running prose.", fontsize=9)
    doc.save(path)
    doc.close()


def _run(code):
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)


def _one_png(out: Path):
    pngs = [p for p in out.glob("*.png") if p.name != "contact_sheet.jpg"]
    assert pngs, f"no crops written to {out}"
    return pngs[0]


def test_standalone_matches_the_package():
    """The committed single-file build must not drift from src/."""
    r = subprocess.run([sys.executable, str(BUILDER), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_standalone_crops_without_pillow_or_bs4(tmp_path):
    pdf = tmp_path / "paper.pdf"
    _make_pdf(pdf)
    out = tmp_path / "out"
    r = _run(BLOCK_OPTIONAL_DEPS + f"""
import runpy, sys
sys.argv = ['fe', 'extract', {str(pdf)!r}, '--out', {str(out)!r}, '--dpi', '72']
runpy.run_path({str(STANDALONE)!r}, run_name='__main__')
""")
    assert r.returncode == 0, r.stderr
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["rendered"] >= 1
    assert _one_png(out).stat().st_size > 0
    assert (out / "contact_sheet.jpg").exists(), "contact sheet must render without Pillow"


def test_package_pdf_path_imports_without_bs4(tmp_path):
    """`extract paper.pdf` must not be blocked by the HTML path's dependency."""
    pdf = tmp_path / "paper.pdf"
    _make_pdf(pdf)
    out = tmp_path / "out"
    r = _run(BLOCK_OPTIONAL_DEPS + f"""
import sys
sys.path.insert(0, {str(ROOT / 'src')!r})
from figure_extractor.cli import main
sys.exit(main(['extract', {str(pdf)!r}, '--out', {str(out)!r}, '--dpi', '72']))
""")
    assert r.returncode == 0, r.stderr
    assert _one_png(out).exists()


def test_runs_as_a_module_without_being_installed(tmp_path):
    """PYTHONPATH=src python -m figure_extractor, for runtimes that cannot pip."""
    pdf = tmp_path / "paper.pdf"
    _make_pdf(pdf)
    out = tmp_path / "out"
    r = subprocess.run(
        [sys.executable, "-m", "figure_extractor", "extract", str(pdf),
         "--out", str(out), "--dpi", "72"],
        capture_output=True, text=True,
        env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"},
    )
    assert r.returncode == 0, r.stderr
    assert _one_png(out).exists()


def test_download_failure_explains_the_remedy(tmp_path, monkeypatch):
    """A DNS failure should tell the caller what to do, not just what broke."""
    import urllib.error
    import urllib.request

    from figure_extractor.utils import SourceError, download_url

    def no_dns(*a, **k):
        raise urllib.error.URLError("[Errno -2] Name or service not known")

    monkeypatch.setattr(urllib.request, "urlopen", no_dns)
    with pytest.raises(SourceError) as excinfo:
        download_url("https://arxiv.org/pdf/2607.28146v1", tmp_path / "x.pdf")
    message = str(excinfo.value)
    assert "local file" in message and "PyMuPDF" in message


# --------------------------------------------------------------------------
# The rung that has to work when the repo itself is unreachable
# --------------------------------------------------------------------------

SKILL = ROOT / "SKILL.md"
BOOTSTRAP = ROOT / "bootstrap" / "minimal_extractor.py"


def _embedded_extractor() -> str:
    """The Python block SKILL.md tells an agent to write out and run."""
    text = SKILL.read_text(encoding="utf-8")
    start = text.index("<!-- BEGIN EMBEDDED EXTRACTOR")
    end = text.index("<!-- END EMBEDDED EXTRACTOR -->")
    block = text[start:end]
    body = block.split("```python", 1)[1]
    return body.rsplit("```", 1)[0].strip("\n")


def test_skill_carries_the_extractor_verbatim():
    """A no-network runtime only ever sees SKILL.md, so the code must be in it."""
    assert _embedded_extractor() == BOOTSTRAP.read_text(encoding="utf-8").rstrip("\n")


def test_extractor_taken_from_skill_md_actually_crops(tmp_path):
    """Write out what SKILL.md prints, deny every optional dep, and run it.

    This is the whole point of embedding it: an agent that can read the skill
    can extract figures without fetching anything.
    """
    pdf = tmp_path / "paper.pdf"
    _make_pdf(pdf)
    script = tmp_path / "fe_min.py"
    script.write_text(_embedded_extractor(), encoding="utf-8")
    out = tmp_path / "out"

    r = _run(BLOCK_OPTIONAL_DEPS + f"""
import runpy, sys
sys.argv = ['fe_min', {str(pdf)!r}, {str(out)!r}, '72']
runpy.run_path({str(script)!r}, run_name='__main__')
""")
    assert r.returncode == 0, r.stderr
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["extractor"] == "skill-embedded-reduced"
    assert manifest["counts"]["ok"] >= 1, manifest
    crop = out / "fig1_p01.png"
    assert crop.exists() and crop.stat().st_size > 0


def test_embedded_extractor_flags_what_it_cannot_judge(tmp_path):
    """Reduced fidelity is fine; a confidently wrong crop is not.

    A caption with nothing beside it must come back failed, never as a figure.
    """
    pdf = tmp_path / "bare.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((70, 400), "Figure 1: A caption with no artwork anywhere near it.",
                     fontsize=9)
    doc.save(pdf)
    doc.close()

    script = tmp_path / "fe_min.py"
    script.write_text(_embedded_extractor(), encoding="utf-8")
    out = tmp_path / "out"
    r = _run(f"""
import runpy, sys
sys.argv = ['fe_min', {str(pdf)!r}, {str(out)!r}, '72']
runpy.run_path({str(script)!r}, run_name='__main__')
""")
    assert r.returncode == 0, r.stderr
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    item = manifest["figures"][0]
    assert item["status"] != "ok", item
    assert item.get("quality_reasons"), item


def test_html_is_parsed_without_beautifulsoup(tmp_path):
    """A saved page with inline images needs no network and no bs4.

    That combination is the sandbox case exactly: the user pastes a page they
    already have, and nothing can be fetched.
    """
    import base64

    doc = fitz.open()
    page = doc.new_page(width=420, height=260)
    page.draw_rect(fitz.Rect(20, 20, 400, 240), color=(0, 0, 0), fill=(0.3, 0.5, 0.8))
    # Enough detail that the PNG clears the icon-size filter honestly: a flat
    # rectangle compresses to under a kilobyte and is dropped as a spacer.
    for i in range(12):
        page.draw_rect(fitz.Rect(30 + i * 30, 220 - i * 15, 55 + i * 30, 235),
                       color=(0, 0, 0), fill=(0.9, 0.35, 0.2))
        page.insert_text((32 + i * 30, 215 - i * 15), f"m{i}", fontsize=7)
    png = page.get_pixmap(dpi=200).tobytes("png")
    doc.close()
    b64 = base64.b64encode(png).decode()

    html = tmp_path / "saved.html"
    html.write_text(
        "<!doctype html><html><body>"
        f'<figure><img src="data:image/png;base64,{b64}">'
        "<figcaption>Figure 2: An inlined bitmap.</figcaption></figure>"
        "<figure><table><tr><th>Model</th><th>WR</th></tr>"
        "<tr><td>GPT-5.4</td><td>81%</td></tr></table>"
        "<figcaption>Table 1: Win rates.</figcaption></figure>"
        "</body></html>",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    r = _run(BLOCK_OPTIONAL_DEPS + f"""
import sys, json
sys.path.insert(0, {str(ROOT / 'src')!r})
from pathlib import Path
from figure_extractor.html_extractor import extract_html_figures
m = extract_html_figures(Path({str(html)!r}), Path({str(out)!r}), base_url=None, make_sheet=False)
assert 'bs4' not in sys.modules, 'the stdlib path must not import bs4'
print(json.dumps(m['counts']))
""")
    assert r.returncode == 0, r.stderr
    counts = json.loads(r.stdout.strip().splitlines()[-1])
    # `ok` counts rendered bitmaps; a text table is reported under text_tables.
    assert counts["ok"] >= 1 and counts["text_tables"] == 1, counts
    assert (out / "fig2_html.png").stat().st_size > 0
    assert (out / "tab1.md").read_text(encoding="utf-8").count("|") > 4


def test_standalone_handles_html_too(tmp_path):
    """The single file is the whole pipeline, not just the PDF half."""
    html = tmp_path / "page.html"
    html.write_text(
        "<html><body><figure><table><tr><th>a</th><th>b</th></tr>"
        "<tr><td>1</td><td>2</td></tr></table>"
        "<figcaption>Table 1: A text table.</figcaption></figure></body></html>",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    r = _run(BLOCK_OPTIONAL_DEPS + f"""
import runpy, sys
sys.argv = ['fe', 'extract', {str(html)!r}, '--out', {str(out)!r}]
runpy.run_path({str(STANDALONE)!r}, run_name='__main__')
""")
    assert r.returncode == 0, r.stderr
    assert (out / "tab1.md").exists()
