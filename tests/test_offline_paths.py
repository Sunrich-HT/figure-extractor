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
