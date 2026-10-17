"""Offline acceptance package for the two reconstruction previews (issue #16).

Seam under test: ``src.core.mineru.acceptance.build_acceptance_package``.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from src.core.mineru.acceptance import build_acceptance_package
from src.core.mineru.cache import load_cache
from src.core.mineru.epub_preview import build_epub_preview
from src.core.mineru.export import MineruExportError
from src.core.mineru.pdf_preview import build_pdf_preview
from tests.test_mineru.mineru_fixture import build_cache, default_pages


def _previews(tmp_path: Path):
    cache = load_cache(build_cache(tmp_path / "cache", source_pages=[1, 19]))
    pdf_dir = tmp_path / "pdf"
    epub_dir = tmp_path / "epub"
    build_pdf_preview(cache, pdf_dir)
    build_epub_preview(cache, epub_dir, language="de")
    return cache, pdf_dir, epub_dir


def _checks(package: Path) -> dict:
    return json.loads((package / "checks.json").read_text(encoding="utf-8"))


def test_acceptance_package_collects_artifacts_and_checks(tmp_path):
    cache, pdf_dir, epub_dir = _previews(tmp_path)

    result = build_acceptance_package(cache, pdf_dir, epub_dir, tmp_path / "package")

    assert result.passed is True
    assert result.failures == ()
    for name in ("report.md", "checks.json", "manifest.json", "contact-sheet.jpg",
                 "pdf/preview.pdf", "epub/preview.epub"):
        assert (tmp_path / "package" / name).is_file(), name

    payload = _checks(tmp_path / "package")
    assert payload["schema_version"] == 1
    assert payload["status"] == "passed"
    statuses = {check["id"]: check["status"] for check in payload["checks"]}
    assert statuses["reader_check"] == "pending"
    assert all(status in {"pass", "pending"} for status in statuses.values())
    assert statuses["reading_order"] == "pass"
    assert statuses["block_coverage"] == "pass"
    assert statuses["image_integrity"] == "pass"

    report = (tmp_path / "package" / "report.md").read_text(encoding="utf-8")
    assert "not a complete book" in report
    assert "Human review" in report
    assert "Reconstructed PDF page(s)" in report
    assert "reader" in report.lower()

    manifest = json.loads((tmp_path / "package" / "manifest.json").read_text(encoding="utf-8"))
    for name, digest in manifest["files"].items():
        assert len(digest) == 64
        assert (tmp_path / "package" / name).is_file()


def test_acceptance_fails_when_a_provenance_describes_another_sample(tmp_path):
    cache, pdf_dir, epub_dir = _previews(tmp_path)
    provenance_path = epub_dir / "preview.provenance.json"
    payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    payload["source"]["sample_sha256"] = "0" * 64
    provenance_path.write_text(json.dumps(payload), encoding="utf-8")

    result = build_acceptance_package(cache, pdf_dir, epub_dir, tmp_path / "package")

    assert result.passed is False
    assert "provenance_identity" in result.failures
    payload = _checks(tmp_path / "package")
    assert payload["status"] == "failed"
    assert "provenance_identity" in payload["failures"]


def test_acceptance_detects_a_modified_cache_file(tmp_path):
    cache, pdf_dir, epub_dir = _previews(tmp_path)
    image = cache.root / "result" / "images" / "fig1.png" if (cache.root / "result").is_dir() \
        else cache.root / "images" / "fig1.png"
    image.write_bytes(image.read_bytes() + b"\x00")

    result = build_acceptance_package(cache, pdf_dir, epub_dir, tmp_path / "package")

    assert result.passed is False
    assert "cache_unmodified" in result.failures


def test_acceptance_never_opens_a_network_socket(tmp_path, monkeypatch):
    import socket

    def _refuse(*args, **kwargs):
        raise AssertionError("acceptance attempted network access")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    cache, pdf_dir, epub_dir = _previews(tmp_path)

    result = build_acceptance_package(cache, pdf_dir, epub_dir, tmp_path / "package")

    assert result.passed is True


def test_acceptance_refuses_to_write_inside_the_cache(tmp_path):
    cache, pdf_dir, epub_dir = _previews(tmp_path)

    with pytest.raises(MineruExportError, match="inside the cache"):
        build_acceptance_package(cache, pdf_dir, epub_dir, cache.root / "package")


def test_cli_both_builds_the_acceptance_package(tmp_path, capsys):
    from src.core.mineru.__main__ import main

    root = build_cache(tmp_path / "cache", source_pages=[1, 19])

    exit_code = main(["--cache", str(root), "--output-dir", str(tmp_path / "out"),
                      "--format", "both", "--language", "de"])

    assert exit_code == 0
    package = tmp_path / "out"
    for name in ("report.md", "checks.json", "manifest.json", "contact-sheet.jpg",
                 "pdf/preview.pdf", "epub/preview.epub"):
        assert (package / name).is_file(), name
    output = capsys.readouterr().out
    assert "Acceptance package" in output
    assert "reader-open check" in output.lower() or "reader check" in output.lower()


def test_acceptance_report_escapes_block_text(tmp_path):
    pages = default_pages()
    pages[1]["blocks"][0]["text"] = "Chapter | <One>"
    cache = load_cache(build_cache(tmp_path / "cache", pages=pages, source_pages=[1, 19]))
    pdf_dir, epub_dir = tmp_path / "pdf", tmp_path / "epub"
    build_pdf_preview(cache, pdf_dir)
    build_epub_preview(cache, epub_dir, title="Sample")

    build_acceptance_package(cache, pdf_dir, epub_dir, tmp_path / "package")

    report = (tmp_path / "package" / "report.md").read_text(encoding="utf-8")
    assert "Chapter \\| &lt;One&gt;" in report


def test_acceptance_fails_without_a_source_pdf(tmp_path):
    cache, pdf_dir, epub_dir = _previews(tmp_path)
    (cache.root / "sample.pdf").unlink()

    result = build_acceptance_package(cache, pdf_dir, epub_dir, tmp_path / "package")

    assert result.passed is False
    assert "contact_sheet" in result.failures


def test_acceptance_flags_structural_review_as_pending(tmp_path):
    cache, pdf_dir, epub_dir = _previews(tmp_path)
    provenance_path = pdf_dir / "preview.provenance.json"
    payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    payload["review_required"] = True
    provenance_path.write_text(json.dumps(payload), encoding="utf-8")

    result = build_acceptance_package(cache, pdf_dir, epub_dir, tmp_path / "package")

    assert result.passed is True
    assert "review_status" in result.pending
    assert "review_status" in _checks(tmp_path / "package")["pending"]
