"""Offline EPUB export of a cached MinerU sample (issue #15).

Seam under test: ``src.core.mineru.epub_preview.build_epub_preview`` — an EPUB 3
package built from the same ``Reconstruction`` the PDF preview uses.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

from src.core.mineru.cache import load_cache
from src.core.mineru.epub_preview import MineruExportError, build_epub_preview
from tests.test_mineru.mineru_fixture import (
    build_cache,
    default_pages,
    tree_fingerprint,
)

OPF = "http://www.idpf.org/2007/opf"
DC = "http://purl.org/dc/elements/1.1/"
XHTML = "http://www.w3.org/1999/xhtml"
EPUB = "http://www.idpf.org/2007/ops"
CONTAINER = "urn:oasis:names:tc:opendocument:xmlns:container"


def _load(tmp_path: Path, **kwargs):
    return load_cache(build_cache(tmp_path / "cache", **kwargs))


def _package(epub_path: Path) -> dict:
    """Return parsed package parts plus the raw archive names."""
    with zipfile.ZipFile(epub_path) as archive:
        names = archive.namelist()
        container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
        opf = ElementTree.fromstring(archive.read("OEBPS/content.opf"))
        nav = ElementTree.fromstring(archive.read("OEBPS/nav.xhtml"))
        documents = {name: ElementTree.fromstring(archive.read(name))
                     for name in names if name.startswith("OEBPS/text-")}
    return {"names": names, "container": container, "opf": opf, "nav": nav,
            "documents": documents}


def test_build_epub_preview_writes_a_valid_package(tmp_path):
    result = build_epub_preview(_load(tmp_path, source_pages=[1, 19]), tmp_path / "epub")

    assert result.epub_path.is_file() and result.provenance_path.is_file()
    parts = _package(result.epub_path)

    with zipfile.ZipFile(result.epub_path) as archive:
        assert archive.namelist()[0] == "mimetype"
        mimetype = archive.getinfo("mimetype")
        assert mimetype.compress_type == zipfile.ZIP_STORED
        assert archive.read("mimetype") == b"application/epub+zip"

    rootfile = parts["container"].find(f".//{{{CONTAINER}}}rootfile")
    assert rootfile.get("full-path") == "OEBPS/content.opf"

    opf = parts["opf"]
    assert opf.get("version") == "3.0"
    metadata = opf.find(f"{{{OPF}}}metadata")
    assert metadata.find(f"{{{DC}}}title").text == "SAMPLE BOOK"
    assert metadata.find(f"{{{DC}}}language").text == "und"
    assert metadata.find(f"{{{OPF}}}meta").get("property") == "dcterms:modified"

    manifest = {item.get("id"): item for item in opf.find(f"{{{OPF}}}manifest")}
    spine = [ref.get("idref") for ref in opf.find(f"{{{OPF}}}spine")]
    assert spine and all(idref in manifest for idref in spine)
    assert manifest["nav"].get("properties") == "nav"
    for item in manifest.values():
        assert f"OEBPS/{item.get('href')}" in parts["names"]

    nav_links = [link.get("href") for link in parts["nav"].findall(f".//{{{XHTML}}}a")]
    assert nav_links
    for link in nav_links:
        target = link.partition("#")[0]
        assert f"OEBPS/{target}" in parts["names"]
    assert "SAMPLE BOOK" in "".join(parts["nav"].itertext())

    text = "\n".join("".join(document.itertext()) for document in parts["documents"].values())
    assert "Untranslated MinerU reconstruction preview" in text
    assert "SAMPLE BOOK" in text
    assert "The first body paragraph." in text
    assert "Figure 1: a caption" in text
    assert "A substantive footnote." in text
    assert "Chapter One" not in text

    images = [image for document in parts["documents"].values()
              for image in document.findall(f".//{{{XHTML}}}img")]
    assert len(images) == 2
    for image in images:
        assert f"OEBPS/{image.get('src')}" in parts["names"]


def test_epub_package_is_deterministic(tmp_path):
    cache = _load(tmp_path, source_pages=[1, 19])

    first = build_epub_preview(cache, tmp_path / "first")
    second = build_epub_preview(cache, tmp_path / "second")

    assert first.epub_path.read_bytes() == second.epub_path.read_bytes()


def test_epub_uses_explicit_language_and_title(tmp_path):
    result = build_epub_preview(_load(tmp_path, source_pages=[1, 19]), tmp_path / "epub",
                                language="de", title="Expliziter Titel")

    parts = _package(result.epub_path)
    metadata = parts["opf"].find(f"{{{OPF}}}metadata")
    assert metadata.find(f"{{{DC}}}title").text == "Expliziter Titel"
    assert metadata.find(f"{{{DC}}}language").text == "de"
    assert result.language == "de"


def test_epub_navigation_follows_recognized_headings(tmp_path):
    pages = default_pages()
    pages[1]["blocks"].insert(
        1, {"type": "title", "level": 1, "text": "SECOND CHAPTER",
            "bbox": [60, 80, 500, 110]})

    result = build_epub_preview(
        _load(tmp_path, pages=pages, source_pages=[1, 19]), tmp_path / "epub")

    assert result.section_count == 2
    package = _package(result.epub_path)
    nav_text = "".join(package["nav"].itertext())
    assert "SECOND CHAPTER" in nav_text
    assert "SAMPLE BOOK" in nav_text


def test_epub_records_that_no_reader_check_occurred(tmp_path):
    result = build_epub_preview(_load(tmp_path, source_pages=[1, 19]), tmp_path / "epub")

    provenance = json.loads(result.provenance_path.read_text(encoding="utf-8"))
    assert provenance["artifact"]["format"] == "epub"
    assert provenance["artifact"]["translated"] is False
    assert provenance["reader_check"]["performed"] is False
    assert provenance["counts"]["blocks_accounted"] == provenance["counts"]["blocks_seen"]
    assert provenance["epub"]["sections"] == result.section_count
    assert provenance["epub"]["bytes"] > 0


def test_epub_never_opens_a_network_socket(tmp_path, monkeypatch):
    import socket

    def _refuse(*args, **kwargs):
        raise AssertionError("reconstruction attempted network access")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)

    result = build_epub_preview(_load(tmp_path, source_pages=[1, 19]), tmp_path / "epub")

    assert result.epub_path.is_file()


def test_epub_leaves_the_cache_byte_identical(tmp_path):
    root = build_cache(tmp_path / "cache", source_pages=[1, 19])
    before = tree_fingerprint(root)
    cache = load_cache(root)

    build_epub_preview(cache, tmp_path / "epub")

    assert tree_fingerprint(root) == before


def test_epub_refuses_to_write_inside_the_cache(tmp_path):
    cache = _load(tmp_path, source_pages=[1, 19])

    with pytest.raises(MineruExportError, match="inside the cache"):
        build_epub_preview(cache, cache.root / "epub")


def test_epub_does_not_invent_a_front_matter_section(tmp_path):
    result = build_epub_preview(_load(tmp_path, source_pages=[1, 19]), tmp_path / "epub")

    package = _package(result.epub_path)
    nav_items = package["nav"].findall(f".//{{{XHTML}}}li")
    assert len(nav_items) == 1
    assert "Front matter" not in "".join(package["nav"].itertext())
    first_document = package["documents"]["OEBPS/text-1.xhtml"]
    assert "Untranslated MinerU reconstruction preview" in "".join(first_document.itertext())


def test_epub_requires_a_trusted_title(tmp_path):
    pages = default_pages()
    pages[0]["blocks"] = [block for block in pages[0]["blocks"] if block["type"] != "title"]
    cache = _load(tmp_path, pages=pages, source_pages=[1, 19])

    with pytest.raises(MineruExportError, match="no recognised level-1 heading"):
        build_epub_preview(cache, tmp_path / "epub")

    result = build_epub_preview(cache, tmp_path / "epub", title="Explicit title")
    metadata = _package(result.epub_path)["opf"].find(f"{{{OPF}}}metadata")
    assert metadata.find(f"{{{DC}}}title").text == "Explicit title"


def test_epub_navigation_anchors_resolve(tmp_path):
    pages = default_pages()
    pages[1]["blocks"].insert(
        2, {"type": "title", "level": 2, "text": "Second level",
            "bbox": [60, 90, 500, 110]})

    result = build_epub_preview(
        _load(tmp_path, pages=pages, source_pages=[1, 19]), tmp_path / "epub")

    package = _package(result.epub_path)
    for link in package["nav"].findall(f".//{{{XHTML}}}a"):
        target, _, anchor = link.get("href").partition("#")
        if anchor:
            document = package["documents"][f"OEBPS/{target}"]
            assert document.find(f".//*[@id='{anchor}']") is not None


def test_cli_builds_epub_from_the_cache(tmp_path, capsys):
    from src.core.mineru.__main__ import main

    root = build_cache(tmp_path / "cache", source_pages=[1, 19])

    exit_code = main(["--cache", str(root), "--output-dir", str(tmp_path / "out"),
                      "--format", "epub", "--language", "de", "--title", "CLI Title"])

    assert exit_code == 0
    epub_path = tmp_path / "out" / "preview.epub"
    metadata = _package(epub_path)["opf"].find(f"{{{OPF}}}metadata")
    assert metadata.find(f"{{{DC}}}title").text == "CLI Title"
    assert "Reader-open check: not performed" in capsys.readouterr().out
